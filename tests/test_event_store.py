from pathlib import Path

from packages.event_store import (
    EventRecord,
    InMemoryEventStore,
    RunRecord,
    SQLiteEventStore,
)


def test_event_store_keeps_events_in_append_order() -> None:
    store = InMemoryEventStore()
    session = store.create_session()
    run = store.create_run(RunRecord(session_id=session.session_id))

    store.append_event(EventRecord(run_id=run.run_id, event_type="run.created"))
    store.append_event(EventRecord(run_id=run.run_id, event_type="task.created"))

    assert [event.event_type for event in store.list_events(run.run_id)] == [
        "run.created",
        "task.created",
    ]


def test_sqlite_event_store_round_trips_trace() -> None:
    database = Path(".test-events.sqlite3")
    try:
        store = SQLiteEventStore(database)
        session = store.create_session()
        run = store.create_run(RunRecord(session_id=session.session_id))
        store.append_event(
            EventRecord(
                run_id=run.run_id,
                event_type="run.created",
                payload={"task": "inspect repository"},
            )
        )
        store.close()

        reopened = SQLiteEventStore(database)

        assert reopened.list_events(run.run_id)[0].payload == {
            "task": "inspect repository"
        }
        assert reopened.runs[run.run_id].session_id == session.session_id
        reopened.close()
    finally:
        if database.exists():
            database.unlink()
