"""Event-sourced human approvals: durable, ownership-checked, expiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from ..event_store import EventRecord, EventStore

ApprovalStatus = Literal["pending", "granted", "rejected", "expired"]

_DECISION_EVENTS = ("approval.granted", "approval.rejected", "approval.expired")


class ApprovalExpired(ValueError):
    """The approval existed but its time-to-live elapsed."""


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    run_id: str
    tool_name: str
    payload: dict[str, Any]
    requested_at: datetime
    status: ApprovalStatus = "pending"
    reason: str | None = None
    decided_at: datetime | None = None


class ApprovalStore:
    """Approvals live in the event log, so they survive a process restart."""

    def __init__(
        self,
        store: EventStore,
        *,
        clock_now: Callable[[], datetime] | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        self.store = store
        self.clock_now = clock_now or (lambda: datetime.now(UTC))
        self.ttl_seconds = ttl_seconds

    def request(
        self,
        run_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=str(uuid4()),
            run_id=run_id,
            tool_name=tool_name,
            payload=payload,
            requested_at=self.clock_now(),
        )
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="approval.requested",
                status="waiting_approval",
                payload={
                    "approval_id": record.approval_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "requested_at": record.requested_at.isoformat(),
                },
            )
        )
        return record

    def get(self, run_id: str, approval_id: str) -> ApprovalRecord:
        record = self._rebuild(run_id, approval_id)
        if record.status == "pending" and self._is_expired(record):
            return replace(record, status="expired")
        return record

    def grant(self, run_id: str, approval_id: str) -> ApprovalRecord:
        return self._decide(run_id, approval_id, "approval.granted", "granted")

    def reject(
        self, run_id: str, approval_id: str, reason: str | None = None
    ) -> ApprovalRecord:
        return self._decide(run_id, approval_id, "approval.rejected", "rejected", reason)

    def _decide(
        self,
        run_id: str,
        approval_id: str,
        event_type: str,
        status: ApprovalStatus,
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = self._locate(approval_id)
        if record.run_id != run_id:
            raise ValueError("approval does not belong to run")
        if record.status != "pending":
            raise KeyError(f"approval already decided: {approval_id}")
        if self._is_expired(record):
            self._append_decision(record, "approval.expired", "expired", "ttl elapsed")
            raise ApprovalExpired(f"approval expired: {approval_id}")

        self._append_decision(record, event_type, status, reason)
        return replace(record, status=status, reason=reason, decided_at=self.clock_now())

    def _append_decision(
        self,
        record: ApprovalRecord,
        event_type: str,
        status: ApprovalStatus,
        reason: str | None,
    ) -> None:
        self.store.append_event(
            EventRecord(
                run_id=record.run_id,
                event_type=event_type,
                status="waiting_approval" if status == "expired" else "running",
                payload={
                    "approval_id": record.approval_id,
                    "reason": reason,
                    "decided_at": self.clock_now().isoformat(),
                },
            )
        )

    def _is_expired(self, record: ApprovalRecord) -> bool:
        return (self.clock_now() - record.requested_at) > timedelta(seconds=self.ttl_seconds)

    def _locate(self, approval_id: str) -> ApprovalRecord:
        for run_id in self.store.list_run_ids():
            try:
                return self._rebuild(run_id, approval_id)
            except KeyError:
                continue
        raise KeyError(f"approval not found: {approval_id}")

    def _rebuild(self, run_id: str, approval_id: str) -> ApprovalRecord:
        requested: EventRecord | None = None
        decision: EventRecord | None = None
        for event in self.store.list_events(run_id):
            if event.payload.get("approval_id") != approval_id:
                continue
            if event.event_type == "approval.requested":
                requested = event
            elif event.event_type in _DECISION_EVENTS:
                decision = event

        if requested is None:
            raise KeyError(f"approval not found: {approval_id}")

        return ApprovalRecord(
            approval_id=approval_id,
            run_id=run_id,
            tool_name=str(requested.payload.get("tool_name", "")),
            payload=dict(requested.payload.get("payload") or {}),
            requested_at=datetime.fromisoformat(
                str(requested.payload.get("requested_at", requested.created_at.isoformat()))
            ),
            status=_status_from_event(decision),
            reason=None if decision is None else decision.payload.get("reason"),
            decided_at=(
                None
                if decision is None
                else datetime.fromisoformat(str(decision.payload.get("decided_at")))
            ),
        )


def _status_from_event(decision: EventRecord | None) -> ApprovalStatus:
    if decision is None:
        return "pending"
    return {
        "approval.granted": "granted",
        "approval.rejected": "rejected",
        "approval.expired": "expired",
    }.get(decision.event_type, "pending")  # type: ignore[return-value]