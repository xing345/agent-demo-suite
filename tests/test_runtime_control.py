"""Cancel, concurrency, run inspection and bounded re-planning over HTTP/engine."""

import time

from fastapi.testclient import TestClient

from apps.runtime_harness.engine import RuntimeEngine
from apps.runtime_harness.main import app
from packages.event_store import InMemoryEventStore
from packages.planner import DeterministicPlanner, PlannedTask, Replanner, TaskPlan
from packages.tool_registry import ToolDefinition

client = TestClient(app, raise_server_exceptions=False)


def _two_step_plan() -> TaskPlan:
    return TaskPlan(
        goal="two steps",
        tasks=[
            PlannedTask(task_id="t1", name="first"),
            PlannedTask(task_id="t2", name="second", depends_on=["t1"]),
        ],
    )


def test_cancel_before_execution_returns_cancelled_and_blocks_execute() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]

    response = client.post(f"/runs/{run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert client.post(f"/runs/{run_id}/execute").status_code == 409


def test_cancel_during_execution_stops_remaining_tasks() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    engine.register_tool(ToolDefinition(name="first"), lambda payload: {"ok": 1})
    engine.register_tool(ToolDefinition(name="second"), lambda payload: {"ok": 2})
    plan = _two_step_plan()
    run = engine.start_run(plan.goal)

    original = engine.handlers["first"]

    def cancelling(payload: dict[str, object]) -> dict[str, object]:
        engine.cancel_run(run.run_id)
        return original(payload)

    engine.handlers["first"] = cancelling

    result = engine.execute_plan(run.run_id, plan)

    assert result.status == "cancelled"
    assert engine.get_run(run.run_id).status == "cancelled"
    assert [item.task_id for item in result.tasks] == ["t1"]
    started = [
        event.payload["task_id"]
        for event in engine.trace(run.run_id)
        if event.event_type == "task.started"
    ]
    assert started == ["t1"]


def test_run_endpoint_reports_tasks() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]
    client.post(f"/runs/{run_id}/execute")

    body = client.get(f"/runs/{run_id}").json()

    assert body["run_id"] == run_id
    assert body["status"] == "completed"
    assert [task["status"] for task in body["tasks"]] == ["completed"]


def test_concurrent_plan_runs_independent_tasks_in_parallel() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store, max_concurrency=2)

    def slow(payload: dict[str, object]) -> dict[str, object]:
        time.sleep(0.2)
        return {"ok": True}

    engine.register_tool(ToolDefinition(name="a"), slow)
    engine.register_tool(ToolDefinition(name="b"), slow)
    plan = TaskPlan(
        goal="independent",
        tasks=[
            PlannedTask(task_id="a", name="a"),
            PlannedTask(task_id="b", name="b"),
        ],
    )
    run = engine.start_run(plan.goal)

    started = time.perf_counter()
    result = engine.execute_plan(run.run_id, plan)
    elapsed = time.perf_counter() - started

    assert [item.task_id for item in result.tasks] == ["a", "b"]
    assert elapsed < 0.38


def test_reject_endpoint_closes_the_approval_and_fails_the_run() -> None:
    run_id = client.post("/runs", json={"task": "update a file"}).json()["run_id"]
    pending = client.post(
        f"/runs/{run_id}/tools/write_demo_file",
        json={"payload": {"path": "README.md"}},
    ).json()

    response = client.post(
        f"/runs/{run_id}/approvals/{pending['approval_id']}/reject",
        params={"reason": "too risky"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["run_status"] == "failed"
    # A rejected approval cannot be granted afterwards.
    assert client.post(
        f"/runs/{run_id}/approvals/{pending['approval_id']}"
    ).status_code == 404


def test_failure_triggers_one_bounded_replan() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store, replanner=Replanner(DeterministicPlanner(), max_replans=1))
    attempts = {"count": 0}

    def flaky(payload: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("unrecoverable this time")
        return {"ok": True}

    engine.register_tool(ToolDefinition(name="read"), lambda payload: {"ok": True})
    engine.register_tool(ToolDefinition(name="analyze"), flaky)
    plan = TaskPlan(
        goal="read then analyze",
        tasks=[
            PlannedTask(task_id="t1", name="read"),
            PlannedTask(task_id="t2", name="analyze", depends_on=["t1"]),
        ],
    )
    run = engine.start_run(plan.goal)

    result = engine.execute_plan(run.run_id, plan)

    assert result.status == "completed"
    stored = engine.get_run(run.run_id)
    assert stored.metadata["plan"]["replan_count"] == 1
    event_types = [event.event_type for event in engine.trace(run.run_id)]
    assert "plan.replanned" in event_types
    assert event_types.count("plan.replanned") == 1