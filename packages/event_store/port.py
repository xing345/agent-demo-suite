"""Storage ports.

Adapters (memory, SQLite, and later Postgres/Redis) implement this protocol;
the runtime depends on the protocol only, never on a concrete adapter.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    CheckpointRecord,
    EventRecord,
    RunRecord,
    SessionRecord,
    TaskRecord,
)


@runtime_checkable
class EventStore(Protocol):
    """Persistence boundary for sessions, runs, tasks, events and checkpoints."""

    def create_session(self, record: SessionRecord | None = None) -> SessionRecord: ...

    def create_run(self, record: RunRecord) -> RunRecord: ...

    def create_task(self, record: TaskRecord) -> TaskRecord: ...

    def get_run(self, run_id: str) -> RunRecord: ...

    def get_task(self, task_id: str) -> TaskRecord: ...

    def update_run(self, record: RunRecord) -> RunRecord: ...

    def update_task(self, record: TaskRecord) -> TaskRecord: ...

    def list_tasks(self, run_id: str) -> list[TaskRecord]: ...

    def append_event(self, record: EventRecord) -> EventRecord: ...

    def list_events(self, run_id: str) -> list[EventRecord]: ...

    def save_checkpoint(self, record: CheckpointRecord) -> CheckpointRecord: ...

    def latest_checkpoint(self, run_id: str) -> CheckpointRecord | None: ...