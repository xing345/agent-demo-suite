from apps.runtime_harness.engine import RuntimeEngine
from apps.runtime_harness.planner import PlannedTask, TaskPlan
from packages.event_store import InMemoryEventStore
from packages.tool_registry import ToolDefinition


def test_runtime_executes_plan_in_dependency_order() -> None:
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(
        ToolDefinition(name="read"),
        lambda payload: {"text": payload["goal"]},
    )
    engine.register_tool(
        ToolDefinition(name="analyze"),
        lambda payload: {"analysis": payload["goal"]},
    )
    plan = TaskPlan(
        goal="read and analyze",
        tasks=[
            PlannedTask(task_id="t1", name="read", description="read"),
            PlannedTask(
                task_id="t2",
                name="analyze",
                description="analyze",
                depends_on=["t1"],
            ),
        ],
    )
    run = engine.start_run(plan.goal)

    result = engine.execute_plan(run.run_id, plan)

    assert [item.name for item in result.tasks] == ["read", "analyze"]
    assert [item.status for item in result.tasks] == ["completed", "completed"]
    assert [event.event_type for event in engine.trace(run.run_id)] == [
        "run.created",
        "task.started",
        "task.completed",
        "task.started",
        "task.completed",
        "run.completed",
    ]


def test_runtime_saves_checkpoint_when_plan_task_fails() -> None:
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(
        ToolDefinition(name="read"),
        lambda payload: (_ for _ in ()).throw(RuntimeError("tool failed")),
    )
    plan = TaskPlan(
        goal="read",
        tasks=[PlannedTask(task_id="t1", name="read", description="read")],
    )
    run = engine.start_run(plan.goal)

    result = engine.execute_plan(run.run_id, plan)

    assert result.tasks[0].status == "failed"
    assert engine.get_run(run.run_id).status == "paused"
    assert engine.store.latest_checkpoint(run.run_id).state["next_task_id"] == "t1"
