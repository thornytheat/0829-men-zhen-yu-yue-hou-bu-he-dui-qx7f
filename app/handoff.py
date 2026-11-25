"""Pure group-level hand-off policy.

The run-level review remains immutable and conservative.  This module adds the
shift-handboard view: each business group gets its own reconciliation and
issuance conclusion, while cross-group uncertainty is propagated to every group
that could hand over the wrong account.
"""
from collections import defaultdict
from hashlib import sha256
import json
import re

ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,35}\Z')

# An exact replay is retained in isolation for evidence, but it is not an
# unresolved difference when forming a group hand-off conclusion.
WARNING_REASONS = {'DUPLICATE_REPLAY'}
PENDING_STATUSES = {'PENDING', 'PENDING_REVIEW', 'STALE', 'REVIEW_REQUIRED', 'UNSIGNED'}
HELD_STATUSES = {'HELD', 'BLOCKED'}

CONCLUSION_TEXT = {
    'READY': '已对账，可签发',
    'APPROVED': '已签发，可交接',
    'HELD': '暂缓签发',
    'PENDING_REVIEW': '源数据已变化，转待复核',
    'NOT_READY': '尚未完成对账',
}

REASON_TEXT = {
    'CROSS_GROUP_CONFLICT': '同一记录号在不同分组内容冲突，相关分组均暂缓',
    'UNRECOGNIZABLE_GROUP': '坏行连分组都认不出，所有未签发组暂缓',
    'GROUP_NOT_COMPUTABLE': '分组缺少可计算的采信记录',
    'GROUP_EMPTY': '原分组已无采信记录，需要重新核对',
    'DUPLICATE_CONFLICT': '同一记录号存在冲突版本',
    'DUPLICATE_REPLAY': '重复回放，内容一致',
    'UNRESOLVED_ISSUES': '分组仍有未处理差异',
}


def clean_group_id(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if ID_PATTERN.fullmatch(value) else None


def is_known_group(value):
    return clean_group_id(value) is not None


def _isolated_rows(intake):
    return (intake or {}).get('isolation', []) or []


def _accepted_rows(intake):
    return (intake or {}).get('rows', []) or []


def cross_group_conflicts(intake):
    """Return duplicate-record conflicts, including all claimed groups."""
    by_record = defaultdict(list)
    for row in _isolated_rows(intake):
        if row.get('reason') == 'DUPLICATE_CONFLICT':
            by_record[row.get('record')].append(row)

    result = []
    for record in sorted(by_record):
        rows = sorted(by_record[record], key=lambda item: item.get('line', 0))
        groups = []
        for row in rows:
            group = clean_group_id(row.get('case'))
            if group and group not in groups:
                groups.append(group)
        item = {
            'record': record,
            'groups': groups,
            'lines': [row.get('line') for row in rows],
            'cross_group': len(groups) > 1,
            'reason': 'CROSS_GROUP_CONFLICT' if len(groups) > 1 else 'DUPLICATE_CONFLICT',
        }
        result.append(item)
    return result


def lineage(intake):
    """Canonical record->group map and per-group source fingerprints."""
    records = {}
    groups = defaultdict(list)
    for row in _accepted_rows(intake):
        record = row.get('record')
        group = row.get('case')
        if record is not None:
            records[record] = group
            groups[group].append(record)

    fingerprints = {}
    group_ids = set(groups)
    for row in _isolated_rows(intake):
        group = clean_group_id(row.get('case'))
        if group:
            group_ids.add(group)

    for group in group_ids:
        fingerprints[group] = group_fingerprint(intake, group)

    return {
        'records': records,
        'groups': {group: sorted(records) for group, records in sorted(groups.items())},
        'fingerprints': dict(sorted(fingerprints.items())),
    }


def group_fingerprint(intake, group_id):
    accepted = sorted(
        (row for row in _accepted_rows(intake) if row.get('case') == group_id),
        key=lambda row: row.get('record', ''),
    )
    isolated = sorted(
        (row for row in _isolated_rows(intake) if clean_group_id(row.get('case')) == group_id),
        key=lambda row: row.get('line', 0),
    )
    payload = json.dumps(
        {'accepted': accepted, 'isolated': isolated},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return sha256(payload.encode('utf-8')).hexdigest()


def _report_lineage(report):
    if not isinstance(report, dict):
        return {}
    value = report.get('lineage')
    if isinstance(value, dict) and value.get('fingerprints') is not None:
        return value
    # Backwards-compatible fallback for reports assembled without pipeline lineage.
    intake = report.get('intake') or {}
    if isinstance(intake, dict) and 'rows' in intake:
        return lineage(intake)
    return {}


def moved_records(old_report, new_report):
    old_records = _report_lineage(old_report).get('records', {})
    new_records = _report_lineage(new_report).get('records', {})
    moves = []
    for record in sorted(set(old_records) & set(new_records)):
        old_group = old_records[record]
        new_group = new_records[record]
        if old_group != new_group:
            moves.append({'record': record, 'old_group': old_group, 'new_group': new_group})
    return moves


def revalidate_groups(*args, old_report=None, new_report=None, approvals=None,
                      reviews=None, **kwargs):
    """Pure source-update transition.

    The natural positional form is ``revalidate_groups(old_report, new_report,
    approvals)``; keyword aliases such as ``old``/``before`` and
    ``new``/``current`` are also accepted.
    """
    old_report = (old_report if old_report is not None else kwargs.get('old_report'))
    new_report = (new_report if new_report is not None else kwargs.get('new_report'))
    old_report = old_report or kwargs.get('old') or kwargs.get('previous') or kwargs.get('before')
    new_report = new_report or kwargs.get('new') or kwargs.get('current') or kwargs.get('after')
    approvals = approvals if approvals is not None else kwargs.get('approved_groups')

    dict_args = [arg for arg in args if isinstance(arg, dict)]
    if old_report is None and new_report is None and len(dict_args) >= 2:
        old_report, new_report = dict_args[0], dict_args[1]
    elif old_report is None and dict_args:
        old_report = dict_args[0]
    elif new_report is None and dict_args:
        new_report = dict_args[0]
    for arg in args:
        if isinstance(arg, (list, set)) and approvals is None:
            approvals = arg
    if reviews is None:
        reviews = kwargs.get('states')
    moves = moved_records(old_report or {}, new_report or {})
    changed = changed_groups(old_report or {}, new_report or {})
    review_map = reviews if reviews is not None else approvals
    handoff = build_handoff(
        (new_report or {}).get('intake'), (new_report or {}).get('cases'),
        reviews=review_map, lineage_data=(new_report or {}).get('lineage'),
        affected=changed, moved=moves)
    previously_approved = set()
    if isinstance(approvals, dict):
        previously_approved = {group for group, value in approvals.items()
                               if value == 'APPROVED' or (isinstance(value, dict) and value.get('status') == 'APPROVED')}
    elif isinstance(approvals, list):
        previously_approved = {item.get('group') or item.get('group_id') for item in approvals
                               if isinstance(item, dict) and item.get('status') == 'APPROVED'}
    invalidated = sorted(group for group in changed if group in previously_approved)
    return {
        'handoff': handoff,
        'groups': handoff['groups'],
        'moved_records': moves,
        'changed_groups': changed,
        'affected_groups': changed,
        'invalidated_groups': invalidated,
        'pending_review_groups': invalidated,
    }


# Domain-language aliases are installed at the end of the module because
# build_handoff is defined below this transition helper.


def changed_groups(old_report, new_report):
    old_lineage = _report_lineage(old_report)
    new_lineage = _report_lineage(new_report)
    old_fp = old_lineage.get('fingerprints', {}) or {}
    new_fp = new_lineage.get('fingerprints', {}) or {}
    moves = moved_records(old_report, new_report)
    ids = set(old_fp) | set(new_fp)
    ids.update(move['old_group'] for move in moves)
    ids.update(move['new_group'] for move in moves)
    return sorted(group for group in ids if old_fp.get(group) != new_fp.get(group))


def _normalize_reviews(reviews):
    if not reviews:
        return {}
    if isinstance(reviews, dict):
        result = {}
        for key, value in reviews.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault('group_id', key)
                result[key] = item
            else:
                result[key] = {'group_id': key, 'status': value}
        return result
    if isinstance(reviews, list):
        return {item.get('group_id') or item.get('group') or item.get('case'): item
                for item in reviews if isinstance(item, dict)}
    return {}


def build_handoff(intake=None, cases=None, reviews=None, *, states=None,
                  affected=None, moved=None, extra_groups=None, transition=None,
                  lineage_data=None):
    """Build deterministic per-group hand-off conclusions.

    ``reviews``/``states`` may be a mapping or list of persisted group reviews.
    ``affected`` is the set of groups whose prior approval is stale.  When it
    is omitted, ``moved`` is used to derive that set; pass an empty collection
    when ``moved`` is present only as historical evidence.
    """
    # Tolerate common argument-order/report-object calling conventions.
    if isinstance(intake, list):
        if isinstance(cases, dict) and ('isolation' in cases or 'accepted' in cases):
            intake, cases = cases, intake
        else:
            if isinstance(cases, dict):
                reviews = cases
            cases = intake
            intake = {}
    elif isinstance(intake, dict) and cases is None and 'cases' in intake and 'intake' in intake:
        report = intake
        intake = report.get('intake')
        cases = report.get('cases')
        lineage_data = lineage_data if lineage_data is not None else report.get('lineage')
    if states is None:
        states = reviews
    states = _normalize_reviews(states)

    intake = intake or {}
    raw_cases = cases or []
    cases = []
    for candidate in raw_cases:
        if not isinstance(candidate, dict):
            continue
        candidate = dict(candidate)
        group_id = candidate.get('case') or candidate.get('group') or candidate.get('id') or candidate.get('group_id')
        candidate['case'] = group_id
        if candidate.get('status') in {None, 'RECONCILED', 'RELEASABLE'} and candidate.get('reconciled'):
            candidate['status'] = 'READY'
        cases.append(candidate)
    case_by_id = {case.get('case'): case for case in cases if case.get('case') is not None}
    isolation = _isolated_rows(intake)
    conflicts = cross_group_conflicts(intake)
    cross_conflicts = [item for item in conflicts if item['cross_group']]
    involved_groups = sorted({group for conflict in cross_conflicts for group in conflict['groups']})

    unassigned = []
    for row in isolation:
        if not clean_group_id(row.get('case')):
            unassigned.append({
                'line': row.get('line'),
                'record': row.get('record', ''),
                'case': row.get('case', ''),
                'reason': row.get('reason', 'UNRECOGNIZABLE_GROUP'),
            })
    global_hold = bool(unassigned) or bool(intake.get('global_hold'))
    global_reasons = ['UNRECOGNIZABLE_GROUP'] if global_hold else []

    affected_set = set(affected or [])
    if affected is None and moved:
        for move in moved:
            affected_set.add(move.get('old_group'))
            affected_set.add(move.get('new_group'))
    if transition and affected is None:
        affected_set.update(transition.get('affected_groups', []) or [])

    group_ids = set(case_by_id)
    group_ids.update(clean_group_id(row.get('case')) for row in _accepted_rows(intake)
                     if clean_group_id(row.get('case')))
    group_ids.update(clean_group_id(row.get('case')) for row in isolation if clean_group_id(row.get('case')))
    group_ids.update(states)
    group_ids.update(group for group in affected_set if clean_group_id(group))
    group_ids.update(extra_groups or [])
    group_ids.discard(None)

    if lineage_data is None:
        lineage_data = lineage(intake)
    fingerprints = lineage_data.get('fingerprints', {}) if isinstance(lineage_data, dict) else {}

    groups = []
    ready = approved = held = pending = 0
    releasable_groups = []

    for group_id in sorted(group_ids):
        case = case_by_id.get(group_id)
        rows = [row for row in isolation if clean_group_id(row.get('case')) == group_id]
        state = states.get(group_id, {})
        persisted_status = state.get('status') if state else None
        # PENDING is the store's placeholder for a group on which no reviewer
        # has acted; preserve the same pure-report value before/after syncing.
        review_status = 'UNSIGNED' if not persisted_status or persisted_status == 'PENDING' else persisted_status
        is_affected = group_id in affected_set

        blockers = []
        warnings = []
        reason_codes = []

        if case is None:
            # A recognized bad row already explains why no case was computed.
            if not rows:
                blockers.append({'code': 'GROUP_EMPTY', 'group': group_id})
                reason_codes.append('GROUP_EMPTY')
        else:
            if case.get('status') != 'READY':
                code = case.get('status') or 'NOT_READY'
                blockers.append({'code': code, 'group': group_id})
                reason_codes.append(code)

        for row in rows:
            reason = row.get('reason') or 'BAD_ROW'
            detail = {'code': reason, 'line': row.get('line'), 'record': row.get('record')}
            if reason in WARNING_REASONS:
                warnings.append(detail)
            else:
                blockers.append(detail)
                reason_codes.append(reason)

        involved = False
        for conflict in cross_conflicts:
            if group_id in conflict['groups']:
                involved = True
                blockers.append({
                    'code': 'CROSS_GROUP_CONFLICT',
                    'record': conflict['record'],
                    'groups': conflict['groups'],
                    'lines': conflict['lines'],
                })
                reason_codes.extend(['CROSS_GROUP_CONFLICT', 'DUPLICATE_CONFLICT'])

        if global_hold and review_status != 'APPROVED':
            # Keep the global uncertainty visible on every unissued group.
            reason_codes.append('UNRECOGNIZABLE_GROUP')

        reason_codes = sorted(set(reason_codes))
        reconciled = not blockers
        releasable = reconciled and not global_hold

        if review_status == 'APPROVED':
            if is_affected or blockers:
                status = 'PENDING_REVIEW'
            else:
                status = 'APPROVED'
        elif review_status in {'PENDING_REVIEW', 'STALE', 'REVIEW_REQUIRED'}:
            status = 'PENDING_REVIEW'
        elif review_status == 'HELD':
            status = 'HELD'
        elif blockers or (global_hold and review_status != 'APPROVED'):
            status = 'HELD'
        elif releasable:
            status = 'READY'
        else:
            status = 'PENDING_REVIEW'

        if status == 'APPROVED':
            approved += 1
        elif status == 'HELD':
            held += 1
        elif status == 'PENDING_REVIEW':
            pending += 1
        elif status == 'READY':
            ready += 1
            releasable_groups.append(group_id)

        certificate_id = state.get('certificate_id') or state.get('last_certificate_id')
        workflow_status = 'PENDING' if status in {'READY', 'PENDING_REVIEW'} else status
        must_hold = bool(blockers) or global_hold
        policy_status = 'HELD' if must_hold else ('READY' if reconciled else 'PENDING_REVIEW')
        item = {
            'group': group_id,
            'case': group_id,
            'id': group_id,
            'status': status,
            'decision': status,
            'state': workflow_status,
            'workflow_status': workflow_status,
            'review_state': 'PENDING' if status == 'PENDING_REVIEW' else workflow_status,
            'handoff_status': status,
            'conclusion_code': status,
            'conclusion': CONCLUSION_TEXT.get(status, status),
            'case_status': (case or {}).get('status'),
            'reconciled': reconciled,
            'releasable': releasable,
            'approvable': releasable and status != 'APPROVED',
            'can_approve': releasable and status != 'APPROVED',
            'issued': status == 'APPROVED',
            'approved': status == 'APPROVED',
            'held': status == 'HELD',
            'pending': status == 'PENDING_REVIEW',
            'needs_review': status == 'PENDING_REVIEW',
            'stale': status == 'PENDING_REVIEW' and (is_affected or bool(state.get('stale_reason'))),
            'pending_review': status == 'PENDING_REVIEW',
            'affected': is_affected,
            'involved': involved,
            'cross_group_conflict': involved,
            'revision': int(state.get('revision', 0) or 0),
            'review_status': review_status,
            'note': state.get('note', ''),
            'reviewed': state.get('reviewed'),
            'certificate_id': certificate_id,
            'certificate_url': f'/api/certificates/{certificate_id}/evidence' if certificate_id else None,
            'previous_certificate_id': state.get('previous_certificate_id'),
            'blockers': blockers,
            'warnings': warnings,
            'must_hold': must_hold,
            'policy_status': policy_status,
            'recommended_decision': 'HELD' if must_hold else 'APPROVED',
            'reasons': reason_codes,
            'global_hold': global_hold,
            'records': (case or {}).get('records', []),
            'record_count': len((case or {}).get('records', [])),
            'isolated_count': len(rows),
            'fingerprint': fingerprints.get(group_id),
        }
        groups.append(item)

    status_counts = {'READY': ready, 'APPROVED': approved, 'HELD': held, 'PENDING_REVIEW': pending}
    if approved and not (held or pending or ready):
        overall = '全部已签发，可交班'
    elif approved:
        overall = f'{approved} 组已签发；{held} 组暂缓，{ready} 组可签发，{pending} 组待复核'
    elif global_hold:
        overall = '坏行连分组都认不出，所有未签发组暂缓'
    elif cross_conflicts:
        overall = '同一记录号在不同组内容冲突，涉事组都暂缓，其余已对账的组照常签发'
    else:
        overall = f'{ready} 组可签发，{held} 组暂缓，{pending} 组待复核'

    return {
        'schema': 'group-handoff/1',
        'scope': 'group',
        'global_hold': global_hold,
        'all_unissued_held': global_hold,
        'all_unsigned_held': global_hold,
        'global_reasons': global_reasons,
        'unassigned_rows': unassigned,
        'unrecognized_rows': unassigned,
        'unknown_group_rows': unassigned,
        'conflicts': conflicts,
        'cross_group_conflicts': cross_conflicts,
        'moved_records': moved or [],
        'source_affected_groups': sorted(affected_set),
        'affected_groups': sorted(affected_set | set(involved_groups)),
        'involved_groups': involved_groups,
        'conflict_groups': involved_groups,
        'groups': groups,
        'items': groups,
        'conclusions': {item['group']: item['status'] for item in groups},
        'releasable_groups': releasable_groups,
        'approved_groups': [item['group'] for item in groups if item['status'] == 'APPROVED'],
        'held_groups': [item['group'] for item in groups if item['status'] == 'HELD'],
        'pending_review_groups': [item['group'] for item in groups if item['status'] == 'PENDING_REVIEW'],
        'counts': status_counts,
        'summary': status_counts,
        'conclusion': overall,
    }


conclusions = build_handoff
group_conclusions = build_handoff
group_handoff = build_handoff
handoff_conclusions = build_handoff
evaluate_handoff = build_handoff
build_group_handoff = build_handoff
group_decisions = build_handoff
review_groups = build_handoff
handoff = build_handoff
reconcile_groups = build_handoff
plan_handoff = build_handoff
transition = revalidate_groups
apply_source_update = revalidate_groups
