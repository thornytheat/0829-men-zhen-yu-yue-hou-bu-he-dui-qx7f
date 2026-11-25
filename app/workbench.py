"""Workbench-facing facade for shift hand-off conclusions."""
from app.handoff import build_handoff, revalidate_groups
from app.review.service import (
    DEFAULT_BOARD,
    board_handoff,
    execute,
    present_run,
    review_group,
    update_source,
)

current_handoff = board_handoff
get_board = board_handoff
submit_group = review_group

__all__ = [
    'DEFAULT_BOARD', 'build_handoff', 'revalidate_groups', 'board_handoff',
    'current_handoff', 'get_board', 'execute', 'present_run',
    'review_group', 'submit_group', 'update_source',
]
