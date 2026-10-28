from apps.runtime_harness.engine import RuntimeEngine
from packages.event_store import InMemoryEventStore
from packages.tool_registry import ToolDefinition


def test_dangerous_tool_waits_for_human_approval() -> None:
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(
        ToolDefinition(
            name="write_file",
            permission="dangerous",
            requires_human_confirmation=True,
        ),
        lambda payload: {"written": payload["path"]},
    )
    run = engine.start_run("update the README")

    result = engine.call_tool(run.run_id, "write_file", {"path": "README.md"})

    assert result.status == "awaiting_approval"
    assert result.approval_id is not None
    # Stage 3 refined the status: a pending approval is `waiting_approval`,
    # while `paused` is reserved for checkpoint pauses.
    assert engine.get_run(run.run_id).status == "waiting_approval"
    assert [event.event_type for event in engine.trace(run.run_id)] == [
        "run.created",
        "approval.requested",
    ]


def test_approved_tool_executes_and_records_trace() -> None:
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(
        ToolDefinition(
            name="write_file",
            permission="dangerous",
            requires_human_confirmation=True,
        ),
        lambda payload: {"written": payload["path"]},
    )
    run = engine.start_run("update the README")
    pending = engine.call_tool(run.run_id, "write_file", {"path": "README.md"})

    result = engine.approve(run.run_id, pending.approval_id)

    assert result.status == "completed"
    assert result.output == {"written": "README.md"}
    assert engine.get_run(run.run_id).status == "completed"
    assert [event.event_type for event in engine.trace(run.run_id)] == [
        "run.created",
        "approval.requested",
        "approval.granted",
        "tool.completed",
        "run.completed",
    ]
