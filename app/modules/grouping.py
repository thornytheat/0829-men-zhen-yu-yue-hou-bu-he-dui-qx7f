from collections import defaultdict

from app.handoff import (
    build_handoff,
    changed_groups,
    cross_group_conflicts,
    moved_records,
)


def case_groups(rows):
    groups = defaultdict(list)
    for row in sorted(rows,key=lambda r:(r['case'],r['record'])):
        groups[row['case']].append(row)
    return groups.items()


# Group hand-off policy lives in app.handoff; these aliases keep the grouping
# module as a convenient import location for callers.
group_handoff = build_handoff
handoff_conclusions = build_handoff
group_conclusions = build_handoff

__all__ = [
    'case_groups', 'build_handoff', 'changed_groups',
    'cross_group_conflicts', 'moved_records', 'group_handoff',
    'handoff_conclusions', 'group_conclusions',
]
