"""Freezes the public HTTP surface so refactors cannot silently break it.

Only additive changes are allowed: new paths/fields may appear, but existing
paths and response keys must keep their shape.
"""

from fastapi.testclient import TestClient

from apps.runtime_harness.main import app

client = TestClient(app, raise_server_exceptions=False)

RUNTIME_PATHS = {
    "/health",
    "/planner",
    "/skills",
    "/tools",
    "/plans/validate",
    "/runs",
    "/runs/{run_id}/events",
    "/runs/{run_id}/execute",
    "/runs/{run_id}/plan",
    "/runs/{run_id}/checkpoints",
    "/runs/{run_id}/resume",
    "/runs/{run_id}/approvals/{approval_id}",
    "/runs/{run_id}/tools/{tool_name}",
    "/mcp/tools",
    "/mcp/tools/{tool_name}",
}


def test_runtime_route_set_is_frozen() -> None:
    paths = {path for path in app.openapi()["paths"] if not path.startswith(("/docs", "/redoc"))}
    paths.discard("/openapi.json")

    assert paths == RUNTIME_PATHS


def test_create_run_response_shape() -> None:
    response = client.post("/runs", json={"task": "inspect repository"})

    assert response.status_code == 201
    assert set(response.json()) == {"session_id", "run_id", "status"}


def test_events_response_shape() -> None:
    run_id = client.post("/runs", json={"task": "inspect repository"}).json()["run_id"]

    body = client.get(f"/runs/{run_id}/events").json()

    assert set(body) == {"run_id", "events"}
    assert body["events"][0]["event_type"] == "run.created"
    assert set(body["events"][0]) >= {"event_id", "run_id", "event_type", "status", "created_at"}


def test_planner_response_shape() -> None:
    body = client.get("/planner", params={"goal": "读取代码并分析问题"}).json()

    assert set(body) >= {"goal", "tasks"}
    assert set(body["tasks"][0]) >= {"task_id", "name", "description", "depends_on"}


def test_skills_response_shape() -> None:
    body = client.get("/skills").json()

    assert isinstance(body, list)
    assert set(body[0]) >= {"name", "description", "prompt_template", "tool_names"}


def test_tools_alias_matches_mcp_tools() -> None:
    assert client.get("/tools").json() == client.get("/mcp/tools").json()