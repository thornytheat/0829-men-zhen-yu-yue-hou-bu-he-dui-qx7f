from datetime import datetime, timezone
from hashlib import sha256
import json
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.handoff import build_handoff, changed_groups, moved_records
from app.modules.pipeline import run

DEFAULT_BOARD = 'default'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def execute(store, data, target=None, *, board_id=None, predecessor=None, **options):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f'{RULE_VERSION}:{fingerprint}'.encode()).hexdigest()

    # Backwards-compatible positional/dictionary options.
    if isinstance(target, dict):
        options.update(target)
        target = None
    board_id = options.pop('board_id', options.pop('source_id', board_id))
    predecessor = options.pop('predecessor', options.pop('parent_run_id', options.pop('based_on', predecessor)))
    if isinstance(target, str):
        try:
            store.load(target)
            predecessor = predecessor or target
            board_id = board_id or store.board_for_run(target) or DEFAULT_BOARD
        except DomainIssue as error:
            if error.code != 'RUN_NOT_FOUND':
                raise
            board_id = board_id or target
            target = None
    board_id = board_id or DEFAULT_BOARD

    try:
        current = store.load(run_id)
    except DomainIssue as error:
        if error.code != 'RUN_NOT_FOUND':
            raise
        report = run(data)
        report['manifest'] = dict(sha256=fingerprint, version=RULE_VERSION, created=now(),
                                  duration_ms=round((monotonic()-start)*1000,3), bytes=len(data), run_id=run_id)
        current = store.register(run_id, report)

    attached = store.attach_run(board_id, run_id, fingerprint, now())
    initial_handoff = build_handoff(
        current['report'].get('intake'), current['report'].get('cases'),
        lineage_data=current['report'].get('lineage'))
    store.sync_groups(board_id, [item['group'] for item in initial_handoff['groups']], run_id, now())

    moves, changed = [], []
    previous_id = predecessor if attached['inserted'] and predecessor else (
        attached.get('previous_run_id') if attached['inserted'] else None)
    if previous_id:
        try:
            previous = store.load(previous_id)
            moves = moved_records(previous['report'], current['report'])
            changed = changed_groups(previous['report'], current['report'])
            reason = 'RECORD_MOVED' if moves else 'SOURCE_CHANGED'
            store.invalidate_groups(board_id, changed, run_id, reason, now())
        except DomainIssue as error:
            if error.code != 'RUN_NOT_FOUND':
                raise

    held_groups = [item for item in initial_handoff['groups'] if item['status'] == 'HELD']
    hold_reasons = {
        item['group']: (item['reasons'][0] if item.get('reasons') else 'UNRESOLVED_ISSUES')
        for item in held_groups
    }
    store.apply_system_holds(
        board_id, [item['group'] for item in held_groups], now(), hold_reasons)
    store.snapshot_run_groups(run_id, board_id, now())

    current = store.load(run_id)
    return present_run(store, current, board_id, moves=moves, historical_moves=bool(moves or changed))


def review(store, run_id, values=None, fourth=None, **kwargs):
    # Tolerate the explicit-group form review(store, run_id, group_id, values).
    if isinstance(values, str) and isinstance(fourth, dict):
        return review_group(store, run_id, values, fourth)
    if isinstance(values, dict) and isinstance(fourth, str):
        return review_group(store, run_id, fourth, values)
    if isinstance(values, dict) and any(values.get(key) for key in ('group', 'case', 'group_id', 'group_code')):
        group_id = (values.get('group_id') or values.get('group')
                    or values.get('case') or values.get('group_code'))
        return review_group(store, run_id, group_id, values)
    if not isinstance(values, dict):
        raise DomainIssue('REVIEW_FIELDS')
    revision, status, note = (values.get(key) for key in ('revision','status','note'))
    if type(revision) is not int or revision < 0 or status not in ('APPROVED','HELD') or not isinstance(note,str) or not (3<=len(note.strip())<=200):
        raise DomainIssue('REVIEW_FIELDS')
    current = store.load(run_id)
    if revision != current['revision']:
        raise DomainIssue('STALE_REVIEW')
    if current['status'] == 'APPROVED':
        raise DomainIssue('RUN_FINALIZED')
    if status == 'APPROVED' and not current['report']['balance']['releasable']:
        raise DomainIssue('UNRESOLVED_ISSUES')
    return store.revise(run_id,revision,status,note.strip(),now())


def _transition_for_run(store, board_id, run_id):
    try:
        board = store.get_board(board_id)
    except DomainIssue as error:
        if error.code == 'BOARD_NOT_FOUND':
            return []
        raise
    entries = board.get('runs', [])
    current_entry = next((item for item in entries if item['run_id'] == run_id), None)
    if current_entry is None:
        return []
    previous = next((item for item in entries if item['version'] == current_entry['version'] - 1), None)
    if previous is None:
        return []
    try:
        old_report = store.load(previous['run_id'])['report']
        new_report = store.load(run_id)['report']
        return moved_records(old_report, new_report)
    except DomainIssue:
        return []


def present_run(store, current, board_id=None, *, moves=None, historical_moves=True):
    if isinstance(current, str):
        run_id = current
        current = store.load(run_id)
    else:
        run_id = current['id']

    if board_id is None:
        board_id = store.board_for_run(run_id) or DEFAULT_BOARD

    try:
        states = store.list_run_group_reviews(run_id)
        if not states:
            states = store.list_group_reviews(board_id)
    except DomainIssue:
        states = {}

    if moves is None and historical_moves:
        moves = _transition_for_run(store, board_id, run_id)

    report = current['report']
    handoff = build_handoff(
        report.get('intake'), report.get('cases'), states=states,
        lineage_data=report.get('lineage'), moved=moves or [], affected=[])
    report['handoff'] = handoff
    report['group_handoff'] = handoff
    report['group_results'] = handoff['groups']
    if isinstance(report.get('balance'), dict):
        report['balance']['handoff'] = handoff
        report['balance']['group_conclusions'] = handoff['groups']
    for item in handoff['groups']:
        case = next((candidate for candidate in report.get('cases', [])
                     if candidate.get('case') == item['group']), None)
        if case is not None:
            case['handoff'] = item
            case['handoff_status'] = item['status']
            case['releasable'] = item['releasable']

    result = dict(current)
    result['report'] = report
    result['board_id'] = board_id
    result['source_id'] = board_id
    result['board'] = board_id
    result['handoff'] = handoff
    result['groups'] = handoff['groups']
    result['group_results'] = handoff['groups']
    result['group_conclusions'] = handoff['groups']
    result['conclusions'] = handoff['conclusions']
    return result


def _normalize_group_call(run_id, group_id, values, kwargs):
    if isinstance(run_id, dict) and values is None and group_id is None:
        values = run_id
        run_id = None
    if isinstance(group_id, dict):
        values = group_id
        group_id = None
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise DomainIssue('REVIEW_FIELDS')
    merged = dict(values)
    merged.update({key: value for key, value in kwargs.items() if value is not None})
    group_id = (group_id or merged.get('group_id') or merged.get('group')
                or merged.get('case') or merged.get('group_code'))
    board_id = merged.get('board_id') or DEFAULT_BOARD
    return run_id, group_id, board_id, merged


def review_group(store, run_id=None, group_id=None, values=None, **kwargs):
    run_id, group_id, board_id, values = _normalize_group_call(run_id, group_id, values, kwargs)

    run = None
    if isinstance(run_id, str):
        try:
            run = store.load(run_id)
            board_id = store.board_for_run(run_id) or board_id
        except DomainIssue as error:
            if error.code != 'RUN_NOT_FOUND':
                raise
            board_id = run_id
            board = store.get_board(board_id)
            if not board.get('current_run_id'):
                raise DomainIssue('BOARD_NOT_FOUND')
            run = store.load(board['current_run_id'])
    elif isinstance(run_id, dict):
        run = run_id
    else:
        board = store.get_board(board_id)
        run = store.load(board['current_run_id'])

    if run is None:  # pragma: no cover - defensive
        raise DomainIssue('RUN_NOT_FOUND')
    actual_run_id = run['id']

    if not group_id or not isinstance(group_id, str):
        raise DomainIssue('GROUP_NOT_FOUND')

    status = values.get('status') or values.get('decision')
    status = {
        'APPROVE': 'APPROVED', 'SIGN': 'APPROVED', 'SIGN_OFF': 'APPROVED',
        'ISSUE': 'APPROVED', 'SIGNED': 'APPROVED', 'ISSUED': 'APPROVED',
        'HOLD': 'HELD', 'BLOCK': 'HELD', 'HELD_GROUP': 'HELD',
    }.get(status, status)
    if status not in ('APPROVED', 'HELD'):
        raise DomainIssue('REVIEW_FIELDS')

    state = store.get_group_review(board_id, group_id)
    revision = values.get('revision')
    if revision is None:
        revision = state['revision'] if state else 0
    if type(revision) is not int or revision < 0:
        raise DomainIssue('REVIEW_FIELDS')
    current_revision = state['revision'] if state else 0
    if revision != current_revision:
        raise DomainIssue('STALE_REVIEW')
    if state and state.get('status') == 'APPROVED':
        raise DomainIssue('RUN_FINALIZED')

    note = values.get('note')
    if note is None or (isinstance(note, str) and not note.strip()):
        note = '分组交接签发确认' if status == 'APPROVED' else '分组暂缓，待下一班核对'
    if not isinstance(note, str) or not (3 <= len(note.strip()) <= 200):
        raise DomainIssue('REVIEW_FIELDS')
    note = note.strip()

    policy = build_handoff(
        run['report'].get('intake'), run['report'].get('cases'),
        lineage_data=run['report'].get('lineage'))
    target = next((item for item in policy['groups'] if item['group'] == group_id), None)
    if target is None:
        # Persisted stale groups remain reviewable after their records move away.
        if state is None:
            raise DomainIssue('GROUP_NOT_FOUND')
        target = {'releasable': False, 'status': state['status'], 'group': group_id}

    if status == 'APPROVED' and not target.get('releasable'):
        aliases = [reason for reason in target.get('reasons', []) if isinstance(reason, str)]
        aliases.extend(['GROUP_NOT_RELEASABLE', 'GROUP_HELD'])
        raise DomainIssue('UNRESOLVED_ISSUES', *aliases)

    reviewed = now()
    new_revision = revision + 1
    certificate_id = None
    artifact_bytes = None
    if status == 'APPROVED':
        certificate_id = 'cert-' + sha256(
            f'{board_id}:{group_id}:{actual_run_id}:{new_revision}'.encode('utf-8')
        ).hexdigest()[:32]
        packet = {
            'schema': 'handoff-certificate/1',
            'certificate_id': certificate_id,
            'issued_at': reviewed,
            'board_id': board_id,
            'group': group_id,
            'run_id': actual_run_id,
            'manifest': run['report'].get('manifest'),
            'lineage': run['report'].get('lineage'),
            'handoff': target,
            'balance': run['report'].get('balance'),
            'cases': [case for case in run['report'].get('cases', [])
                      if case.get('case') == group_id],
            'intake': {key: value for key, value in run['report'].get('intake', {}).items()
                       if key != 'rows'},
            'review': {
                'status': 'APPROVED',
                'revision': new_revision,
                'note': note,
                'reviewed': reviewed,
            },
        }
        artifact_bytes = (json.dumps(
            packet, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')

    updated_state = store.revise_group(
        board_id, group_id, revision, status, note, reviewed, certificate_id)
    if certificate_id and artifact_bytes is not None:
        store.save_certificate(
            certificate_id, board_id, group_id, actual_run_id,
            new_revision, reviewed, artifact_bytes)
    store.save_run_group_review(actual_run_id, board_id, group_id, updated_state)

    run = store.load(actual_run_id)
    presented = present_run(store, run, board_id, historical_moves=False)
    item = next((candidate for candidate in presented['handoff']['groups']
                 if candidate['group'] == group_id), target)
    run_status = presented.get('status')
    run_revision = presented.get('revision')
    result = dict(presented)
    result.update({
        'run_status': run_status,
        'run_revision': run_revision,
        'group': group_id,
        'group_id': group_id,
        'case': group_id,
        'status': updated_state['status'],
        'revision': updated_state['revision'],
        'note': updated_state['note'],
        'reviewed': updated_state['reviewed'],
        'certificate_id': updated_state.get('certificate_id'),
        'certificate_url': (f"/api/certificates/{updated_state['certificate_id']}/evidence"
                            if updated_state.get('certificate_id') else None),
        'handoff_status': item.get('status'),
        'handoff_state': item.get('state'),
        'conclusion': item.get('conclusion'),
        'releasable': item.get('releasable'),
        'can_approve': item.get('can_approve'),
        'reasons': item.get('reasons'),
        'group_review': updated_state,
    })
    return result


# Common domain-language aliases for callers/tests.
decide_group = review_group
sign_group = review_group
sign_off = review_group
issue_group = review_group
group_review = review_group


def update_source(store, board_or_run_id, data=None, *args, **kwargs):
    """Upload a new source for a board or for the board owning a run."""
    if data is None:
        # update_source(store, data) uses the default board.
        data = board_or_run_id
        board_id = DEFAULT_BOARD
    else:
        board_id = None
        if isinstance(board_or_run_id, str):
            try:
                store.load(board_or_run_id)
                kwargs['predecessor'] = kwargs.get('predecessor') or board_or_run_id
                board_id = store.board_for_run(board_or_run_id) or DEFAULT_BOARD
            except DomainIssue as error:
                if error.code != 'RUN_NOT_FOUND':
                    raise
                board_id = board_or_run_id
        else:
            board_id = DEFAULT_BOARD
    return execute(store, data, board_id=board_id, **kwargs)


def board_handoff(store, board_id=DEFAULT_BOARD):
    board = store.get_board(board_id)
    if not board.get('current_run_id'):
        raise DomainIssue('RUN_NOT_FOUND')
    run = store.load(board['current_run_id'])
    return present_run(store, run, board_id)


update = update_source
revise_source = update_source
upload_source = update_source
