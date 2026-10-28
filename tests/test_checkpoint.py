from apps.runtime_harness.engine import RuntimeEngine
from packages.event_store import InMemoryEventStore


def test_engine_saves_and_restores_latest_checkpoint() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    run = engine.start_run("analyze repository")

    saved = engine.save_checkpoint(run.run_id, {"next_task": "analyze", "step": 2})
    restored = RuntimeEngine(store).resume_run(run.run_id)

    assert saved.checkpoint_id == restored.checkpoint_id
    assert restored.state == {"next_task": "analyze", "step": 2}
    assert engine.get_run(run.run_id).status == "running"
    assert [event.event_type for event in engine.trace(run.run_id)] == [
        "run.created",
        "checkpoint.saved",
        "checkpoint.restored",
    ]
