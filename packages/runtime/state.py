"""Run and task status vocabulary plus the legal transition tables."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class RunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTransition(RuntimeError):
    """A run or task was asked to move to an illegal status."""


RUN_TRANSITIONS: dict[str, set[str]] = {
    "created": {"queued", "running", "paused", "failed", "cancelled", "waiting_approval"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "paused", "cancelled", "waiting_approval"},
    "waiting_approval": {"running", "paused", "cancelled", "failed"},
    "paused": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

TASK_TRANSITIONS: dict[str, set[str]] = {
    "created": {"queued", "running", "cancelled", "failed", "waiting_approval"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled", "paused", "waiting_approval"},
    "waiting_approval": {"running", "cancelled", "failed"},
    "paused": {"running", "failed", "cancelled"},
    # A failed task may only be retried by explicitly re-queueing it.
    "failed": {"queued"},
    "completed": set(),
    "cancelled": set(),
}


def ensure_transition(
    current: str,
    target: str,
    *,
    transitions: Mapping[str, set[str]],
    entity: str,
    entity_id: str,
) -> None:
    if str(current) == str(target):
        return
    allowed = transitions.get(str(current), set())
    if str(target) not in allowed:
        raise InvalidTransition(
            f"{entity} {entity_id}: illegal transition {current} -> {target}"
        )