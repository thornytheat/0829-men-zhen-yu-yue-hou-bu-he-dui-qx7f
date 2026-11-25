"""Group-level review service aliases."""
from app.handoff import build_handoff, revalidate_groups
from app.review.service import (
    board_handoff,
    decide_group,
    review_group,
    sign_group,
    update_source,
)


def approve_group(store, run_id=None, group_id=None, values=None, **kwargs):
    if values is None and isinstance(group_id, dict):
        values = group_id
        group_id = None
    values = dict(values or {})
    values['status'] = 'APPROVED'
    return review_group(store, run_id, group_id, values, **kwargs)


def hold_group(store, run_id=None, group_id=None, values=None, **kwargs):
    if values is None and isinstance(group_id, dict):
        values = group_id
        group_id = None
    values = dict(values or {})
    values['status'] = 'HELD'
    return review_group(store, run_id, group_id, values, **kwargs)


issue_group = approve_group
sign_off_group = approve_group

__all__ = [
    'approve_group', 'hold_group', 'issue_group', 'sign_off_group',
    'review_group', 'decide_group', 'sign_group', 'update_source',
    'board_handoff', 'build_handoff', 'revalidate_groups',
]
