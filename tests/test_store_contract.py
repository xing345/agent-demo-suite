"""Contract tests every EventStore implementation must satisfy.

The memory store and the SQLite store are expected to behave identically.
The SQLite variant used to keep run/task state only in memory, so a reopened
store silently lost status changes; these tests pin that behaviour down.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from packages.event_store import (
    EventRecord,
    InMemoryEventStore,
    RunRecord,
    SessionRecord,
    SQLiteEventStore,
    TaskRecord,
)

StoreFactory = tuple[object, Callable[[], object]]


@pytest.fixture(params=["memory", "sqlite"])
def store_factory(request: pytest.FixtureRequest, tmp_path: Path) -> StoreFactory:
    if request.param == "memory":
        store = InMemoryEventStore()
        return store, lambda: store

    database = tmp_path / "contract.sqlite3"
    store = SQLiteEventStore(database)

    def reopen() -> SQLiteEventStore:
        return SQLiteEventStore(database)

    return store, reopen


def test_session_run_and_task_round_trip(store_factory: StoreFactory) -> None:
    store, reopen = store_factory
    session = store.create_session()
    run = store.create_run(RunRecord(session_id=session.session_id))
    task = store.create_task(TaskRecord(run_id=run.run_id, name="read"))

    reopened = reopen()

    assert reopened.get_run(run.run_id).session_id == session.session_id
    assert reopened.get_task(task.task_id).name == "read"
    assert [item.task_id for item in reopened.list_tasks(run.run_id)] == [task.task_id]


def test_status_and_metadata_changes_survive_reload(store_factory: StoreFactory) -> None:
    store, reopen = store_factory
    session = store.create_session()
    run = store.create_run(RunRecord(session_id=session.session_id))
    task = store.create_task(TaskRecord(run_id=run.run_id, name="read"))

    run.status = "completed"
    run.metadata["plan"] = {"goal": "demo"}
    store.update_run(run)
    task.status = "completed"
    task.metadata["output"] = {"ok": True}
    store.update_task(task)

    reopened = reopen()

    assert reopened.get_run(run.run_id).status == "completed"
    assert reopened.get_run(run.run_id).metadata["plan"] == {"goal": "demo"}
    assert reopened.get_task(task.task_id).status == "completed"
    assert reopened.get_task(task.task_id).metadata["output"] == {"ok": True}


def test_unknown_records_raise_key_error(store_factory: StoreFactory) -> None:
    store, _ = store_factory

    with pytest.raises(KeyError):
        store.get_run("missing-run")
    with pytest.raises(KeyError):
        store.get_task("missing-task")
    with pytest.raises(KeyError):
        store.update_run(RunRecord(session_id="missing-session"))


def test_list_tasks_is_scoped_to_run(store_factory: StoreFactory) -> None:
    store, _ = store_factory
    first = store.create_session()
    second = store.create_session()
    run_a = store.create_run(RunRecord(session_id=first.session_id))
    run_b = store.create_run(RunRecord(session_id=second.session_id))
    store.create_task(TaskRecord(run_id=run_a.run_id, name="a1"))
    store.create_task(TaskRecord(run_id=run_a.run_id, name="a2"))
    store.create_task(TaskRecord(run_id=run_b.run_id, name="b1"))

    assert len(store.list_tasks(run_a.run_id)) == 2
    assert len(store.list_tasks(run_b.run_id)) == 1
    assert store.list_tasks("missing-run") == []


def test_checkpoint_append_order_is_preserved(store_factory: StoreFactory) -> None:
    store, reopen = store_factory
    session = store.create_session()
    run = store.create_run(RunRecord(session_id=session.session_id))
    store.append_event(EventRecord(run_id=run.run_id, event_type="run.created"))
    store.append_event(EventRecord(run_id=run.run_id, event_type="task.started"))

    assert [event.event_type for event in reopen().list_events(run.run_id)] == [
        "run.created",
        "task.started",
    ]


def test_session_record_is_accepted_by_create_session(store_factory: StoreFactory) -> None:
    store, reopen = store_factory
    session = store.create_session(SessionRecord(metadata={"tenant": "acme"}))

    assert reopen().sessions[session.session_id].metadata["tenant"] == "acme"