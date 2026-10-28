"""Derive a span tree from the event log (no clock injection needed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.event_store import EventRecord, RunRecord

TERMINAL_RUN_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
TASK_END_EVENTS = {
    "task.completed": "completed",
    "task.failed": "failed",
    "task.cancelled": "cancelled",
}


@dataclass
class Span:
    span_id: str
    name: str
    kind: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[Span] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
            "children": [child.to_dict() for child in self.children],
        }


def _duration_ms(started: datetime | None, ended: datetime | None) -> int | None:
    if started is None or ended is None:
        return None
    return max(0, int((ended - started).total_seconds() * 1000))


def build_span_tree(run: RunRecord, events: list[EventRecord]) -> Span:
    if not events:
        return Span(span_id=run.run_id, name=run.run_id, kind="run", status=run.status)

    started_at = events[0].created_at
    terminal = [event for event in events if event.event_type in TERMINAL_RUN_EVENTS]
    ended_at = terminal[-1].created_at if terminal else None

    root = Span(
        span_id=run.run_id,
        name=run.run_id,
        kind="run",
        status=run.status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=_duration_ms(started_at, ended_at),
        attributes={"goal": run.metadata.get("task")},
    )

    open_tasks: dict[str, list[EventRecord]] = {}
    for event in events:
        task_id = str(event.payload.get("task_id", ""))
        if event.event_type == "task.started":
            open_tasks.setdefault(task_id, []).append(event)
            continue

        if event.event_type in TASK_END_EVENTS:
            pending = open_tasks.get(task_id) or []
            start = pending.pop(0) if pending else None
            root.children.append(
                Span(
                    span_id=task_id,
                    name=str(event.payload.get("name") or task_id),
                    kind="task",
                    status=TASK_END_EVENTS[event.event_type],
                    started_at=start.created_at if start else None,
                    ended_at=event.created_at,
                    duration_ms=(
                        event.latency_ms
                        if event.latency_ms is not None
                        else _duration_ms(start.created_at if start else None, event.created_at)
                    ),
                    attributes={
                        "attempts": event.payload.get("attempts"),
                        "error": event.payload.get("error"),
                    },
                )
            )
            continue

        if event.event_type == "tool.completed":
            root.children.append(
                Span(
                    span_id=event.event_id,
                    name=str(event.payload.get("tool_name") or "tool"),
                    kind="tool",
                    status="completed",
                    started_at=event.created_at,
                    ended_at=event.created_at,
                    duration_ms=event.latency_ms,
                )
            )
        elif event.event_type == "mcp.fallback":
            root.children.append(
                Span(
                    span_id=event.event_id,
                    name=str(event.payload.get("tool_name") or "mcp"),
                    kind="mcp",
                    status="degraded",
                    started_at=event.created_at,
                    ended_at=event.created_at,
                    duration_ms=0,
                    attributes={"reason": event.payload.get("reason")},
                )
            )

    return root