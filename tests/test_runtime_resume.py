"""Resume semantics: a checkpointed run continues instead of restarting."""

from apps.runtime_harness.engine import RuntimeEngine
from apps.runtime_harness.planner import PlannedTask, TaskPlan
from packages.event_store import InMemoryEventStore
from packages.tool_registry import ToolDefinition


def test_resume_after_failure_runs_only_remaining_tasks() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    calls: list[str] = []
    should_fail = {"value": True}

    def analyze(payload: dict[str, object]) -> dict[str, object]:
        calls.append("analyze")
        if should_fail["value"]:
            raise RuntimeError("model unavailable")
        return {"analysis": "ok"}

    engine.register_tool(ToolDefinition(name="read"), lambda payload: {"text": "ok"})
    engine.register_tool(ToolDefinition(name="analyze"), analyze)
    engine.register_tool(ToolDefinition(name="generate"), lambda payload: {"draft": "ok"})

    plan = TaskPlan(
        goal="read then analyze then write",
        tasks=[
            PlannedTask(task_id="t1", name="read", description="read"),
            PlannedTask(
                task_id="t2", name="analyze", description="analyze", depends_on=["t1"]
            ),
            PlannedTask(
                task_id="t3", name="generate", description="generate", depends_on=["t2"]
            ),
        ],
    )
    run = engine.start_run(plan.goal)

    failed = engine.execute_plan(run.run_id, plan)

    assert failed.status == "paused"
    assert engine.get_run(run.run_id).status == "paused"
    assert store.latest_checkpoint(run.run_id) is not None

    should_fail["value"] = False
    engine.resume_run(run.run_id)
    resumed = engine.execute_plan(run.run_id, plan)

    assert resumed.status == "completed"
    assert [item.task_id for item in resumed.tasks] == ["t2", "t3"]
    assert calls == ["analyze", "analyze"]

    started = [
        event.payload["task_id"]
        for event in engine.trace(run.run_id)
        if event.event_type == "task.started"
    ]
    assert started == ["t1", "t2", "t2", "t3"]