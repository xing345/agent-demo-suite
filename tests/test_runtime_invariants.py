"""Invariants that used to be violated by the audited implementation.

Each test here maps to a concrete audit finding (B1 - B5, B8, B12).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime_harness.engine import RuntimeEngine
from apps.runtime_harness.main import app, store
from apps.runtime_harness.planner import DeterministicPlanner
from packages.event_store import SQLiteEventStore
from packages.tool_registry import ToolDefinition

client = TestClient(app, raise_server_exceptions=False)


def _create_run(task: str = "读取代码并分析问题", **extra: object) -> str:
    payload: dict[str, object] = {"task": task, **extra}
    response = client.post("/runs", json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


def test_event_task_ids_exist_in_store() -> None:
    """B2: trace payloads must reference real TaskRecords."""
    run_id = _create_run()

    assert client.post(f"/runs/{run_id}/execute").status_code == 200

    event_task_ids = {
        event.payload["task_id"]
        for event in store.list_events(run_id)
        if "task_id" in event.payload
    }
    stored_task_ids = {task.task_id for task in store.list_tasks(run_id)}

    assert event_task_ids
    assert event_task_ids == stored_task_ids


def test_approval_survives_a_wrong_run_id() -> None:
    """B3: a mismatched run id must not consume a pending approval."""
    run_a = _create_run("update a file")
    pending = client.post(
        f"/runs/{run_a}/tools/write_demo_file",
        json={"payload": {"path": "README.md"}},
    ).json()
    run_b = _create_run("another run")

    mismatch = client.post(f"/runs/{run_b}/approvals/{pending['approval_id']}")
    assert mismatch.status_code == 404

    approved = client.post(f"/runs/{run_a}/approvals/{pending['approval_id']}")
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"


def test_second_execute_is_rejected() -> None:
    """B4: completed runs must not be executed again."""
    run_id = _create_run()

    assert client.post(f"/runs/{run_id}/execute").status_code == 200
    assert client.post(f"/runs/{run_id}/execute").status_code == 409


def test_request_metadata_is_persisted() -> None:
    """B8: CreateRunRequest.metadata used to be dropped."""
    run_id = _create_run(metadata={"tenant": "acme"})

    run = store.get_run(run_id)
    assert run.metadata["tenant"] == "acme"
    assert run.metadata["task"] == "读取代码并分析问题"
    assert run.metadata["plan"]["tasks"]


def test_empty_goal_is_a_client_error() -> None:
    """B5: empty goal used to surface as a 500."""
    response = client.get("/planner", params={"goal": ""})

    assert response.status_code == 400


def test_sqlite_run_survives_reopen(tmp_path: Path) -> None:
    """B1: status, metadata and task output must be durable."""
    database = tmp_path / "runtime.sqlite3"
    first = SQLiteEventStore(database)
    engine = RuntimeEngine(first)
    engine.register_tool(ToolDefinition(name="read"), lambda payload: {"ok": True})
    run = engine.start_run("读取代码")
    plan = DeterministicPlanner().plan("读取代码")

    engine.execute_plan(run.run_id, plan)
    first.close()

    reopened = SQLiteEventStore(database)
    try:
        assert reopened.get_run(run.run_id).status == "completed"
        task = reopened.get_task(plan.tasks[0].task_id)
        assert task.status == "completed"
        assert task.metadata["output"] == {"ok": True}
    finally:
        reopened.close()


def test_execute_reuses_the_plan_saved_at_create_time() -> None:
    """B12: re-planning on execute made task ids drift."""
    run_id = _create_run()
    planned_ids = [task["task_id"] for task in store.get_run(run_id).metadata["plan"]["tasks"]]

    client.post(f"/runs/{run_id}/execute")

    assert [task.task_id for task in store.list_tasks(run_id)] == planned_ids