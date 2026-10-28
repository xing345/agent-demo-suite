"""JSONL export: one event object per line, ready for offline analysis."""

from __future__ import annotations

import json

from packages.event_store import EventRecord


def export_jsonl(events: list[EventRecord]) -> str:
    if not events:
        return ""
    lines = [
        json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for event in events
    ]
    return "\n".join(lines) + "\n"