from collections import defaultdict
import json
import sqlite3
from pathlib import Path

from .models import (
    CheckpointRecord,
    EventRecord,
    RunRecord,
    SessionRecord,
    TaskRecord,
)


class InMemoryEventStore:
    """Small deterministic store used by the skeleton and unit tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.runs: dict[str, RunRecord] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self.events: dict[str, list[EventRecord]] = defaultdict(list)
        self.checkpoints: dict[str, list[CheckpointRecord]] = defaultdict(list)

    def create_session(self, record: SessionRecord | None = None) -> SessionRecord:
        item = record or SessionRecord()
        self.sessions[item.session_id] = item
        return item

    def create_run(self, record: RunRecord) -> RunRecord:
        if record.session_id not in self.sessions:
            raise KeyError(f"unknown session: {record.session_id}")
        self.runs[record.run_id] = record
        return record

    def create_task(self, record: TaskRecord) -> TaskRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.tasks[record.task_id] = record
        return record

    def append_event(self, record: EventRecord) -> EventRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.events[record.run_id].append(record)
        return record

    def list_events(self, run_id: str) -> list[EventRecord]:
        return list(self.events.get(run_id, []))

    def save_checkpoint(self, record: CheckpointRecord) -> CheckpointRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.checkpoints[record.run_id].append(record)
        return record

    def latest_checkpoint(self, run_id: str) -> CheckpointRecord | None:
        items = self.checkpoints.get(run_id, [])
        return items[-1] if items else None


class SQLiteEventStore:
    """Durable event store with the same public shape as the memory store."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.sessions: dict[str, SessionRecord] = {}
        self.runs: dict[str, RunRecord] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self._create_tables()
        self._load_records()

    def _create_tables(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def _load_records(self) -> None:
        for row in self.connection.execute("SELECT payload FROM sessions"):
            record = SessionRecord.model_validate_json(row["payload"])
            self.sessions[record.session_id] = record
        for row in self.connection.execute("SELECT payload FROM runs"):
            record = RunRecord.model_validate_json(row["payload"])
            self.runs[record.run_id] = record
        for row in self.connection.execute("SELECT payload FROM tasks"):
            record = TaskRecord.model_validate_json(row["payload"])
            self.tasks[record.task_id] = record

    def create_session(self, record: SessionRecord | None = None) -> SessionRecord:
        item = record or SessionRecord()
        self.connection.execute(
            "INSERT INTO sessions(session_id, payload) VALUES (?, ?)",
            (item.session_id, item.model_dump_json()),
        )
        self.connection.commit()
        self.sessions[item.session_id] = item
        return item

    def create_run(self, record: RunRecord) -> RunRecord:
        if record.session_id not in self.sessions:
            raise KeyError(f"unknown session: {record.session_id}")
        self.connection.execute(
            "INSERT INTO runs(run_id, session_id, payload) VALUES (?, ?, ?)",
            (record.run_id, record.session_id, record.model_dump_json()),
        )
        self.connection.commit()
        self.runs[record.run_id] = record
        return record

    def create_task(self, record: TaskRecord) -> TaskRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.connection.execute(
            "INSERT INTO tasks(task_id, run_id, payload) VALUES (?, ?, ?)",
            (record.task_id, record.run_id, record.model_dump_json()),
        )
        self.connection.commit()
        self.tasks[record.task_id] = record
        return record

    def append_event(self, record: EventRecord) -> EventRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.connection.execute(
            "INSERT INTO events(run_id, payload) VALUES (?, ?)",
            (record.run_id, record.model_dump_json()),
        )
        self.connection.commit()
        return record

    def list_events(self, run_id: str) -> list[EventRecord]:
        rows = self.connection.execute(
            "SELECT payload FROM events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        )
        return [EventRecord.model_validate_json(row["payload"]) for row in rows]

    def save_checkpoint(self, record: CheckpointRecord) -> CheckpointRecord:
        if record.run_id not in self.runs:
            raise KeyError(f"unknown run: {record.run_id}")
        self.connection.execute(
            "INSERT INTO checkpoints(run_id, payload) VALUES (?, ?)",
            (record.run_id, json.dumps(record.model_dump(mode="json"))),
        )
        self.connection.commit()
        return record

    def latest_checkpoint(self, run_id: str) -> CheckpointRecord | None:
        row = self.connection.execute(
            "SELECT payload FROM checkpoints WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return CheckpointRecord.model_validate_json(row["payload"])

    def close(self) -> None:
        self.connection.close()
