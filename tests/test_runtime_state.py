"""Run/task status vocabulary and legal transitions."""

import pytest

from packages.runtime.state import (
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    InvalidTransition,
    RunStatus,
    TaskStatus,
    ensure_transition,
)


def test_status_enums_cover_the_requested_vocabulary() -> None:
    expected = {
        "created",
        "queued",
        "running",
        "waiting_approval",
        "paused",
        "completed",
        "failed",
        "cancelled",
    }

    assert {status.value for status in RunStatus} == expected
    assert {status.value for status in TaskStatus} == expected


def test_legal_transition_passes() -> None:
    ensure_transition("created", "running", transitions=RUN_TRANSITIONS, entity="run", entity_id="r1")
    ensure_transition(
        "running", "waiting_approval", transitions=RUN_TRANSITIONS, entity="run", entity_id="r1"
    )
    ensure_transition(
        "waiting_approval", "running", transitions=RUN_TRANSITIONS, entity="run", entity_id="r1"
    )


def test_illegal_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransition, match="completed -> running"):
        ensure_transition(
            "completed", "running", transitions=RUN_TRANSITIONS, entity="run", entity_id="r1"
        )


def test_run_terminal_states_have_no_exits() -> None:
    for status in ("completed", "failed", "cancelled"):
        assert RUN_TRANSITIONS[status] == set()


def test_failed_task_must_be_requeued_before_retry() -> None:
    # A failed task is retried by re-queueing it; it may not jump to running.
    assert TASK_TRANSITIONS["failed"] == {"queued"}
    assert TASK_TRANSITIONS["completed"] == set()
    assert TASK_TRANSITIONS["cancelled"] == set()
    with pytest.raises(InvalidTransition):
        ensure_transition(
            "failed", "running", transitions=TASK_TRANSITIONS, entity="task", entity_id="t1"
        )


def test_waiting_approval_can_be_cancelled() -> None:
    ensure_transition(
        "waiting_approval", "cancelled", transitions=RUN_TRANSITIONS, entity="run", entity_id="r1"
    )