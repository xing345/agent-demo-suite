"""Aggregate a run's events into a summary. Missing data stays null."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from packages.event_store import EventRecord, RunRecord

TERMINAL_RUN_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


@dataclass
class RunSummary:
    run_id: str
    status: str
    duration_ms: int | None
    task_count: int
    completed: int
    failed: int
    cancelled: int
    tool_calls: int
    event_count: int
    tokens: dict[str, int | float | None] = field(
        default_factory=lambda: {
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        }
    )

    @property
    def success_rate(self) -> float | None:
        finished = self.completed + self.failed
        return None if finished == 0 else round(self.completed / finished, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "task_count": self.task_count,
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "tool_calls": self.tool_calls,
            "event_count": self.event_count,
            "tokens": dict(self.tokens),
            "success_rate": self.success_rate,
        }


def summarize_run(run: RunRecord, events: list[EventRecord]) -> RunSummary:
    counts = Counter(event.event_type for event in events)
    task_ids = {
        str(event.payload.get("task_id"))
        for event in events
        if event.event_type == "task.started" and event.payload.get("task_id")
    }

    started_at = events[0].created_at if events else None
    terminal = [event for event in events if event.event_type in TERMINAL_RUN_EVENTS]
    ended_at = terminal[-1].created_at if terminal else None
    duration_ms = (
        max(0, int((ended_at - started_at).total_seconds() * 1000))
        if started_at is not None and ended_at is not None
        else None
    )

    return RunSummary(
        run_id=run.run_id,
        status=run.status,
        duration_ms=duration_ms,
        task_count=len(task_ids),
        completed=counts["task.completed"],
        failed=counts["task.failed"],
        cancelled=counts["task.cancelled"],
        tool_calls=counts["tool.completed"],
        event_count=len(events),
        tokens=_aggregate_usage(events),
    )


def _aggregate_usage(events: list[EventRecord]) -> dict[str, int | float | None]:
    totals: dict[str, int | float | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
    }
    for event in events:
        usage = event.payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in ("input_tokens", "output_tokens", "cost_usd"):
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            totals[key] = (totals[key] or 0) + value
    return totals