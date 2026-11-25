import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue
from app.handoff import build_handoff

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);
CREATE TABLE IF NOT EXISTS boards (
    id TEXT PRIMARY KEY,
    current_run_id TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS board_runs (
    board_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    PRIMARY KEY (board_id, version),
    UNIQUE (board_id, run_id)
);
CREATE TABLE IF NOT EXISTS group_reviews (
    board_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    reviewed TEXT,
    current_run_id TEXT,
    certificate_id TEXT,
    previous_certificate_id TEXT,
    stale_reason TEXT,
    hold_reason TEXT,
    source_run_id TEXT,
    updated TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (board_id, group_id)
);
CREATE TABLE IF NOT EXISTS certificates (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created TEXT NOT NULL,
    artifact TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_group_reviews (
    run_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    board_id TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    reviewed TEXT,
    certificate_id TEXT,
    stale_reason TEXT,
    updated TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, group_id)
);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            yield db

    def register(self, run_id, report):
        with self.connect() as db:
            db.execute('INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                       (run_id,json.dumps(report,ensure_ascii=False),report['manifest']['created']))
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if row is None:
            raise DomainIssue('RUN_NOT_FOUND')
        result = dict(row)
        result['report'] = json.loads(result['report'])
        result['board_id'] = None
        result['group_reviews'] = {}
        board_id = self.board_for_run(run_id)
        if board_id:
            result['board_id'] = board_id
        result['group_reviews'] = self.list_run_group_reviews(run_id)
        if isinstance(result.get('report'), dict):
            handoff = build_handoff(
                result['report'].get('intake'), result['report'].get('cases'),
                states=result['group_reviews'],
                lineage_data=result['report'].get('lineage'))
            result['report']['handoff'] = handoff
            result['report']['group_handoff'] = handoff
            result['handoff'] = handoff
            result['groups'] = handoff['groups']
            result['group_results'] = handoff['groups']
            result['group_conclusions'] = handoff['groups']
            result['conclusions'] = handoff['conclusions']
        return result

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50')]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute('UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?',
                                (status,note,now,run_id,revision))
            if cursor.rowcount != 1:
                raise DomainIssue('STALE_REVIEW')
        return self.load(run_id)

    # ------------------------------------------------------------------
    # Group hand-off boards
    # ------------------------------------------------------------------
    def attach_run(self, board_id, run_id, source_sha256, now):
        with self.connect() as db:
            db.execute('INSERT INTO boards(id,created,updated) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING',
                       (board_id, now, now))
            previous = db.execute(
                'SELECT run_id,version FROM board_runs WHERE board_id=? ORDER BY version DESC LIMIT 1',
                (board_id,)).fetchone()
            existing = db.execute(
                'SELECT version FROM board_runs WHERE board_id=? AND run_id=?',
                (board_id, run_id)).fetchone()
            if existing is not None:
                return {
                    'inserted': False,
                    'version': existing['version'],
                    'previous_run_id': previous['run_id'] if previous else None,
                    'previous_version': previous['version'] if previous else None,
                }
            version = (previous['version'] if previous else 0) + 1
            db.execute(
                'INSERT INTO board_runs(board_id,run_id,version,source_sha256,created) VALUES(?,?,?,?,?)',
                (board_id, run_id, version, source_sha256, now))
            db.execute('UPDATE boards SET current_run_id=?,updated=? WHERE id=?',
                       (run_id, now, board_id))
            return {
                'inserted': True,
                'version': version,
                'previous_run_id': previous['run_id'] if previous else None,
                'previous_version': previous['version'] if previous else None,
            }

    def board_for_run(self, run_id):
        with self.connect() as db:
            row = db.execute(
                'SELECT board_id FROM board_runs WHERE run_id=? ORDER BY version DESC LIMIT 1',
                (run_id,)).fetchone()
        return row['board_id'] if row else None

    def get_board(self, board_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM boards WHERE id=?', (board_id,)).fetchone()
            if row is None:
                raise DomainIssue('BOARD_NOT_FOUND')
            versions = db.execute(
                'SELECT board_id,run_id,version,source_sha256,created FROM board_runs '
                'WHERE board_id=? ORDER BY version DESC LIMIT 50', (board_id,)).fetchall()
        result = dict(row)
        result['runs'] = [dict(item) for item in versions]
        return result

    def list_boards(self):
        with self.connect() as db:
            rows = db.execute(
                'SELECT b.id,b.current_run_id,b.created,b.updated,COUNT(r.run_id) AS run_count '
                'FROM boards b LEFT JOIN board_runs r ON r.board_id=b.id '
                'GROUP BY b.id ORDER BY b.updated DESC,b.id LIMIT 50').fetchall()
        return [dict(row) for row in rows]

    def sync_groups(self, board_id, group_ids, run_id, now):
        if not group_ids:
            return
        with self.connect() as db:
            for group_id in group_ids:
                db.execute(
                    'INSERT INTO group_reviews(board_id,group_id,status,current_run_id,updated) '
                    'VALUES(?,?,?,?,?) ON CONFLICT(board_id,group_id) DO UPDATE SET current_run_id=excluded.current_run_id',
                    (board_id, group_id, 'PENDING', run_id, now))

    def list_group_reviews(self, board_id):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM group_reviews WHERE board_id=? ORDER BY group_id',
                              (board_id,)).fetchall()
        return {row['group_id']: dict(row) for row in rows}

    def list_run_group_reviews(self, run_id):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM run_group_reviews WHERE run_id=? ORDER BY group_id',
                              (run_id,)).fetchall()
        return {row['group_id']: dict(row) for row in rows}

    def snapshot_run_groups(self, run_id, board_id, now):
        """Copy current board conclusions into an immutable run-scoped view."""
        with self.connect() as db:
            rows = db.execute('SELECT * FROM group_reviews WHERE board_id=?', (board_id,)).fetchall()
            for row in rows:
                db.execute(
                    'INSERT INTO run_group_reviews(run_id,group_id,board_id,status,revision,note,'
                    'reviewed,certificate_id,stale_reason,updated) VALUES(?,?,?,?,?,?,?,?,?,?) '
                    'ON CONFLICT(run_id,group_id) DO NOTHING',
                    (run_id, row['group_id'], board_id, row['status'], row['revision'], row['note'],
                     row['reviewed'], row['certificate_id'], row['stale_reason'], now))

    def save_run_group_review(self, run_id, board_id, group_id, state):
        with self.connect() as db:
            db.execute(
                'INSERT INTO run_group_reviews(run_id,group_id,board_id,status,revision,note,'
                'reviewed,certificate_id,stale_reason,updated) VALUES(?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(run_id,group_id) DO UPDATE SET status=excluded.status,'
                'revision=excluded.revision,note=excluded.note,reviewed=excluded.reviewed,'
                'certificate_id=excluded.certificate_id,stale_reason=excluded.stale_reason,'
                'updated=excluded.updated',
                (run_id, group_id, board_id, state.get('status'), state.get('revision', 0),
                 state.get('note', ''), state.get('reviewed'), state.get('certificate_id'),
                 state.get('stale_reason'), state.get('updated') or ''))

    def get_group_review(self, board_id, group_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM group_reviews WHERE board_id=? AND group_id=?',
                             (board_id, group_id)).fetchone()
        return dict(row) if row else None

    def invalidate_groups(self, board_id, group_ids, run_id, reason, now):
        affected = []
        with self.connect() as db:
            for group_id in sorted(set(group_ids or [])):
                row = db.execute(
                    'SELECT status,certificate_id FROM group_reviews WHERE board_id=? AND group_id=?',
                    (board_id, group_id)).fetchone()
                if row is None or row['status'] != 'APPROVED':
                    continue
                cursor = db.execute(
                    "UPDATE group_reviews SET status='PENDING_REVIEW', revision=revision+1, "
                    'stale_reason=?, source_run_id=?, current_run_id=?, updated=?, '
                    'previous_certificate_id=COALESCE(previous_certificate_id,certificate_id) '
                    'WHERE board_id=? AND group_id=? AND status=?',
                    (reason, run_id, run_id, now, board_id, group_id, 'APPROVED'))
                if cursor.rowcount == 1:
                    affected.append(group_id)
        return affected

    def apply_system_holds(self, board_id, held_groups, now, reasons=None):
        held_groups = set(held_groups or [])
        reasons = reasons or {}
        changed = []
        with self.connect() as db:
            rows = db.execute('SELECT group_id,status,hold_reason FROM group_reviews WHERE board_id=?',
                              (board_id,)).fetchall()
            for row in rows:
                group_id = row['group_id']
                if group_id in held_groups:
                    if row['status'] == 'PENDING':
                        reason = reasons.get(group_id) or 'GROUP_NOT_RECONCILED'
                        db.execute(
                            "UPDATE group_reviews SET status='HELD',hold_reason=?,updated=? "
                            'WHERE board_id=? AND group_id=?',
                            (reason, now, board_id, group_id))
                        changed.append(group_id)
                    elif row['status'] == 'HELD' and row['hold_reason']:
                        reason = reasons.get(group_id) or row['hold_reason']
                        db.execute('UPDATE group_reviews SET hold_reason=?,updated=? WHERE board_id=? AND group_id=?',
                                   (reason, now, board_id, group_id))
                elif row['status'] == 'HELD' and row['hold_reason']:
                    # An automatic hold from an earlier source can clear once
                    # the group is reconciled.  Manual holds have no hold_reason.
                    db.execute(
                        "UPDATE group_reviews SET status='PENDING',hold_reason=NULL,updated=? "
                        'WHERE board_id=? AND group_id=?',
                        (now, board_id, group_id))
        return sorted(changed)

    def revise_group(self, board_id, group_id, revision, status, note, now, certificate_id=None):
        with self.connect() as db:
            cursor = db.execute(
                'UPDATE group_reviews SET status=?,note=?,reviewed=?,revision=revision+1,updated=?,'
                'certificate_id=COALESCE(?,certificate_id), stale_reason=NULL, hold_reason=NULL '
                'WHERE board_id=? AND group_id=? AND revision=?',
                (status, note, now, now, certificate_id, board_id, group_id, revision))
            if cursor.rowcount != 1:
                raise DomainIssue('STALE_REVIEW')
        result = self.get_group_review(board_id, group_id)
        if result is None:  # pragma: no cover - defensive consistency
            raise DomainIssue('GROUP_NOT_FOUND')
        return result

    def save_certificate(self, certificate_id, board_id, group_id, run_id, revision, now, artifact):
        text = artifact.decode('utf-8') if isinstance(artifact, bytes) else str(artifact)
        with self.connect() as db:
            db.execute(
                'INSERT INTO certificates(id,board_id,group_id,run_id,revision,created,artifact) '
                'VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                (certificate_id, board_id, group_id, run_id, revision, now, text))
        return self.load_certificate(certificate_id)

    def load_certificate(self, certificate_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM certificates WHERE id=?', (certificate_id,)).fetchone()
        if row is None:
            raise DomainIssue('CERTIFICATE_NOT_FOUND')
        result = dict(row)
        result['artifact'] = json.loads(result['artifact'])
        return result
