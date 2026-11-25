"""Compatibility location for group hand-off policy."""
from app.handoff import *  # noqa: F401,F403
from app.handoff import (  # noqa: F401
    build_handoff,
    changed_groups,
    conclusions,
    cross_group_conflicts,
    group_conclusions,
    group_fingerprint,
    handoff,
    lineage,
    moved_records,
    plan_handoff,
    revalidate_groups,
    transition,
)
