"""Prometheus text exposition derived from the event store."""

from __future__ import annotations

from collections import Counter

from packages.event_store import EventStore

from .summary import summarize_run

RUN_STATUSES = (
    "created",
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
)


def render_prometheus(store: EventStore) -> str:
    run_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    tool_calls = 0
    event_total = 0
    duration_sum = 0
    duration_count = 0

    for run_id in store.list_run_ids():
        run = store.get_run(run_id)
        events = store.list_events(run_id)
        summary = summarize_run(run, events)

        run_counts[summary.status] += 1
        task_counts["completed"] += summary.completed
        task_counts["failed"] += summary.failed
        task_counts["cancelled"] += summary.cancelled
        tool_calls += summary.tool_calls
        event_total += summary.event_count
        if summary.duration_ms is not None:
            duration_sum += summary.duration_ms
            duration_count += 1

    lines = [
        "# HELP agent_runs_total Runs grouped by terminal or current status.",
        "# TYPE agent_runs_total counter",
    ]
    lines.extend(
        f'agent_runs_total{{status="{status}"}} {run_counts.get(status, 0)}'
        for status in RUN_STATUSES
    )

    lines.extend(
        [
            "# HELP agent_tasks_total Tasks grouped by outcome.",
            "# TYPE agent_tasks_total counter",
        ]
    )
    for status in ("completed", "failed", "cancelled"):
        lines.append(f'agent_tasks_total{{status="{status}"}} {task_counts[status]}')

    lines.extend(
        [
            "# HELP agent_tool_calls_total Direct tool calls recorded on runs.",
            "# TYPE agent_tool_calls_total counter",
            f"agent_tool_calls_total {tool_calls}",
            "# HELP agent_events_total Events persisted in the store.",
            "# TYPE agent_events_total counter",
            f"agent_events_total {event_total}",
            "# HELP agent_run_duration_ms Run wall-clock duration in milliseconds.",
            "# TYPE agent_run_duration_ms summary",
            f"agent_run_duration_ms_sum {duration_sum}",
            f"agent_run_duration_ms_count {duration_count}",
        ]
    )
    return "\n".join(lines) + "\n"