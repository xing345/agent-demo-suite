"""Event-sourced approvals: ownership, expiry, rejection, durability."""

from datetime import UTC, datetime, timedelta

import pytest

from packages.event_store import InMemoryEventStore, RunRecord
from packages.runtime.approvals import ApprovalExpired, ApprovalStore


def _store_with_runs(count: int = 1) -> tuple[InMemoryEventStore, list[str]]:
    store = InMemoryEventStore()
    session = store.create_session()
    run_ids = []
    for _ in range(count):
        run = store.create_run(RunRecord(session_id=session.session_id))
        run_ids.append(run.run_id)
    return store, run_ids


def test_request_and_grant_roundtrip() -> None:
    store, (run_id,) = _store_with_runs()
    approvals = ApprovalStore(store)

    record = approvals.request(run_id, "write_file", {"path": "README.md"})
    granted = approvals.grant(run_id, record.approval_id)

    assert granted.status == "granted"
    assert [event.event_type for event in store.list_events(run_id)] == [
        "approval.requested",
        "approval.granted",
    ]


def test_grant_twice_is_rejected() -> None:
    store, (run_id,) = _store_with_runs()
    approvals = ApprovalStore(store)
    record = approvals.request(run_id, "write_file", {})
    approvals.grant(run_id, record.approval_id)

    with pytest.raises(KeyError):
        approvals.grant(run_id, record.approval_id)


def test_wrong_run_does_not_consume_the_approval() -> None:
    store, run_ids = _store_with_runs(2)
    approvals = ApprovalStore(store)
    record = approvals.request(run_ids[0], "write_file", {})

    with pytest.raises(ValueError, match="does not belong"):
        approvals.grant(run_ids[1], record.approval_id)

    assert approvals.grant(run_ids[0], record.approval_id).status == "granted"


def test_reject_marks_the_approval_rejected() -> None:
    store, (run_id,) = _store_with_runs()
    approvals = ApprovalStore(store)
    record = approvals.request(run_id, "write_file", {})

    rejected = approvals.reject(run_id, record.approval_id, reason="too risky")

    assert rejected.status == "rejected"
    assert rejected.reason == "too risky"
    with pytest.raises(KeyError):
        approvals.grant(run_id, record.approval_id)


def test_expired_approval_cannot_be_granted() -> None:
    store, (run_id,) = _store_with_runs()
    now = {"value": datetime(2026, 1, 1, tzinfo=UTC)}
    approvals = ApprovalStore(
        store,
        clock_now=lambda: now["value"],
        ttl_seconds=10,
    )
    record = approvals.request(run_id, "write_file", {})

    now["value"] = now["value"] + timedelta(seconds=11)

    with pytest.raises(ApprovalExpired):
        approvals.grant(run_id, record.approval_id)
    assert any(
        event.event_type == "approval.expired" for event in store.list_events(run_id)
    )


def test_pending_approvals_are_rebuilt_from_events() -> None:
    store, (run_id,) = _store_with_runs()
    record = ApprovalStore(store).request(run_id, "write_file", {"path": "x"})

    # A brand new store instance must still see the pending approval.
    reopened = ApprovalStore(store)

    assert reopened.get(run_id, record.approval_id).status == "pending"
    assert reopened.grant(run_id, record.approval_id).status == "granted"