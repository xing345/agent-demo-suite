"""Regression tests for the unified console (``apps.console``).

The console must stay a thin aggregator: it mounts the two existing apps and
never re-implements their behaviour, and it must not leak secrets through the
``/console/api/config`` endpoint.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.console.main import app
from packages.shared_config import get_settings

client = TestClient(app)


def test_console_serves_the_single_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Agent Demo Suite" in response.text


def test_console_mounts_both_sub_applications() -> None:
    paths = {route.path for route in app.routes}

    assert "/runtime" in paths
    assert "/multimodal" in paths


def test_runtime_sub_application_is_reachable_through_the_mount() -> None:
    response = client.get("/runtime/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_multimodal_sub_application_is_reachable_through_the_mount() -> None:
    response = client.get("/multimodal/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_runs_can_be_created_through_the_console() -> None:
    response = client.post("/runtime/runs", json={"task": "diagnose login failure"})

    assert response.status_code == 201
    assert response.json()["run_id"]


def test_config_endpoint_never_exposes_secrets() -> None:
    settings = get_settings()
    response = client.get("/console/api/config")
    body = response.json()

    assert response.status_code == 200
    for value in body.values():
        if isinstance(value, str) and value:
            assert value != settings.model_api_key
            assert value != settings.mcp_server_token
            assert value != settings.mcp_remote_token
    assert body["routes"] == {"runtime": "/runtime", "multimodal": "/multimodal"}


def test_config_endpoint_reports_model_availability() -> None:
    settings = get_settings()
    body = client.get("/console/api/config").json()

    assert body["model_configured"] is bool(settings.model_name and settings.model_base_url)
    assert body["mcp_server_auth"] is bool(settings.mcp_server_token)