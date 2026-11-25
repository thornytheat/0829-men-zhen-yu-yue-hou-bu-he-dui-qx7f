from collections import Counter, defaultdict

from csv import Error

from app.business import DomainIssue
from app.handoff import clean_group_id
from app.intake.reader import records
from app.intake.resolve import partition
from app.intake.schema import HEADER, record


def inspect(data):
    counted = repeated = blanks = 0
    candidates, rejected = [], []
    try:
        for line, values in records(data):
            counted += 1
            if not any(v.strip() for v in values):
                blanks += 1
                continue
            if tuple(values) == HEADER:
                repeated += 1
                continue
            try:
                candidates.append((line, record(values)))
            except DomainIssue as error:
                key = values[0][:36] if values else ''
                case = values[1][:36] if len(values) > 1 else ''
                rejected.append(dict(line=line, record=key, case=case, reason=error.code))
    except Error as error:
        raise DomainIssue('CSV_MALFORMED') from error
    accepted, conflicts = partition(candidates)
    rejects = sorted(rejected + conflicts, key=lambda row: row['line'])
    conflict_cases = defaultdict(set)
    for row in rejects:
        if row.get('reason') == 'DUPLICATE_CONFLICT':
            group = clean_group_id(row.get('case'))
            if group:
                conflict_cases[row.get('record')].add(group)
    cross_group_records = {record for record, groups in conflict_cases.items() if len(groups) > 1}
    for row in rejects:
        row['group_recognizable'] = clean_group_id(row.get('case')) is not None
        if row.get('reason') == 'DUPLICATE_CONFLICT' and row.get('record') in cross_group_records:
            row['cross_group'] = True
            row['conflict_code'] = 'CROSS_GROUP_CONFLICT'
    return dict(input=counted, accepted=len(accepted), repeated=repeated, blank=blanks,
                rejected=len(rejects), reasons=dict(Counter(r['reason'] for r in rejects)),
                isolation=rejects, rows=accepted,
                cross_group_conflicts=sorted(cross_group_records))
