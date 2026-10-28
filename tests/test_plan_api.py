"""Plan validation and plan inspection over HTTP."""

from fastapi.testclient import TestClient

from apps.runtime_harness.main import app

client = TestClient(app, raise_server_exceptions=False)

VALID_PLAN = {
    "goal": "demo",
    "tasks": [
        {"task_id": "a", "name": "a", "description": "a"},
        {"task_id": "b", "name": "b", "description": "b", "depends_on": ["a"]},
    ],
}


def test_validate_returns_order_and_depth() -> None:
    response = client.post("/plans/validate", json=VALID_PLAN)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["task_order"] == ["a", "b"]
    assert body["depth"] == 2


def test_validate_reports_cycle_with_machine_readable_code() -> None:
    cyclic = {
        "goal": "loop",
        "tasks": [
            {"task_id": "a", "name": "a", "depends_on": ["b"]},
            {"task_id": "b", "name": "b", "depends_on": ["a"]},
        ],
    }

    response = client.post("/plans/validate", json=cyclic)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "CYCLE_DETECTED"


def test_run_plan_endpoint_returns_the_frozen_plan() -> None:
    run_id = client.post("/runs", json={"task": "读取代码"}).json()["run_id"]

    response = client.get(f"/runs/{run_id}/plan")

    assert response.status_code == 200
    assert response.json()["goal"] == "读取代码"
    assert [task["name"] for task in response.json()["tasks"]] == ["read"]
    assert client.get("/runs/missing/plan").status_code == 404