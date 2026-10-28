"""The executor must honour the dependency graph, not the array order."""

from apps.runtime_harness.engine import RuntimeEngine
from packages.event_store import InMemoryEventStore
from packages.planner import PlannedTask, TaskPlan
from packages.tool_registry import ToolDefinition


def test_unsorted_plan_executes_in_dependency_order() -> None:
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(ToolDefinition(name="parent"), lambda payload: {"ok": "parent"})
    engine.register_tool(ToolDefinition(name="child"), lambda payload: {"ok": "child"})

    # Deliberately reversed: the child is declared before its dependency.
    plan = TaskPlan(
        goal="child needs parent",
        tasks=[
            PlannedTask(task_id="child", name="child", depends_on=["parent"]),
            PlannedTask(task_id="parent", name="parent"),
        ],
    )
    run = engine.start_run(plan.goal)

    result = engine.execute_plan(run.run_id, plan)

    assert result.status == "completed"
    assert [item.task_id for item in result.tasks] == ["parent", "child"]