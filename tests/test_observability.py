"""Trace tree, run summary, JSONL export and Prometheus metrics."""

import json

from fastapi.testclient import TestClient

from apps.runtime_harness.engine import RuntimeEngine
from apps.runtime_harness.main import app
from packages.event_store import InMemoryEventStore
from packages.observability.jsonl import export_jsonl
from packages.observability.metrics import render_prometheus
from packages.observability.summary import summarize_run
from packages.observability.trace import build_span_tree
from packages.planner import PlannedTask, TaskPlan
from packages.tool_registry import ToolDefinition

client = TestClient(app, raise_server_exceptions=False)


def _completed_run() -> tuple[RuntimeEngine, str]:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    engine.register_tool(ToolDefinition(name="read"), lambda payload: {"ok": True})
    engine.register_tool(ToolDefinition(name="analyze"), lambda payload: {"ok": True})
    plan = TaskPlan(
        goal="read then analyze",
        tasks=[
            PlannedTask(task_id="t1", name="read"),
            PlannedTask(task_id="t2", name="analyze", depends_on=["t1"]),
        ],
    )
    run = engine.start_run(plan.goal)
    engine.execute_plan(run.run_id, plan)
    return engine, run.run_id


def test_span_tree_has_run_root_and_task_children() -> None:
    engine, run_id = _completed_run()

    tree = build_span_tree(engine.get_run(run_id), engine.trace(run_id))

    assert tree.kind == "run"
    assert tree.status == "completed"
    assert tree.duration_ms is not None
    assert [child.name for child in tree.children] == ["read", "analyze"]
    assert all(child.kind == "task" for child in tree.children)
    assert all(child.duration_ms is not None for child in tree.children)
    assert tree.duration_ms >= max(child.duration_ms or 0 for child in tree.children)


def test_failed_task_span_is_marked_failed() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    engine.register_tool(
        ToolDefinition(name="boom"),
        lambda payload: (_ for _ in ()).throw(RuntimeError("tool exploded")),
    )
    plan = TaskPlan(goal="fail", tasks=[PlannedTask(task_id="t1", name="boom")])
    run = engine.start_run(plan.goal)
    engine.execute_plan(run.run_id, plan)

    tree = build_span_tree(engine.get_run(run.run_id), engine.trace(run.run_id))

    assert tree.children[0].status == "failed"
    assert "tool exploded" in str(tree.children[0].attributes.get("error"))


def test_summary_counts_and_nullable_usage() -> None:
    engine, run_id = _completed_run()
    run = engine.get_run(run_id)
    events = engine.trace(run_id)

    summary = summarize_run(run, events)

    assert summary.task_count == 2
    assert summary.completed == 2
    assert summary.failed == 0
    assert summary.event_count == len(events)
    assert summary.tokens["input_tokens"] is None
    assert summary.tokens["cost_usd"] is None
    assert summary.success_rate == 1.0
    assert summary.duration_ms is not None


def test_success_rate_is_none_when_no_task_finished() -> None:
    store = InMemoryEventStore()
    engine = RuntimeEngine(store)
    run = engine.start_run("nothing yet")

    summary = summarize_run(engine.get_run(run.run_id), engine.trace(run.run_id))

    assert summary.success_rate is None


def test_export_jsonl_emits_one_object_per_event() -> None:
    engine, run_id = _completed_run()

    payload = export_jsonl(engine.trace(run_id))
    lines = payload.strip().splitlines()

    assert len(lines) == len(engine.trace(run_id))
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event_type"] == "run.created"
    assert {"event_id", "run_id", "event_type", "created_at"} <= set(parsed[0])


def test_metrics_render_run_and_task_counters() -> None:
    engine, _ = _completed_run()

    text = render_prometheus(engine.store)

    assert 'agent_runs_total{status="completed"} 1' in text
    assert 'agent_tasks_total{status="completed"} 2' in text
    assert "agent_events_total " in text
    assert text.endswith("\n")


def test_trace_endpoint_returns_tree() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]
    client.post(f"/runs/{run_id}/execute")

    body = client.get(f"/runs/{run_id}/trace").json()

    assert body["run_id"] == run_id
    assert body["spans"][0]["kind"] == "run"
    assert body["spans"][0]["children"][0]["kind"] == "task"


def test_summary_endpoint_returns_counts() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]
    client.post(f"/runs/{run_id}/execute")

    body = client.get(f"/runs/{run_id}/summary").json()

    assert body["task_count"] == 1
    assert body["completed"] == 1
    assert body["status"] == "completed"


def test_export_endpoint_serves_ndjson() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]

    response = client.get(f"/runs/{run_id}/events/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(response.text.splitlines()[0])["event_type"] == "run.created"


def test_metrics_endpoint_is_prometheus_text() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "agent_runs_total" in response.text
    assert response.headers["content-type"].startswith("text/plain")