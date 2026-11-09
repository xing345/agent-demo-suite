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

def test_console_explains_what_the_project_is_for() -> None:
    """界面必须自己回答“这是什么、解决什么问题”。

    控制台的读者是第一次打开它的人。页面上如果只有几个输入框，他看不出
    这个项目想证明什么。这几段文案就是功能的一部分，删掉等于把说明书丢了。
    """

    body = client.get("/").text

    for needle in [
        "运行时实验台",
        "可观测、可审批、可回放",
        "它干了什么",
        "谁批准的",
        "挂了能续吗",
        "数据从哪来",
        "从这里开始",
    ]:
        assert needle in body


def test_console_ui_contracts_match_the_real_payloads() -> None:
    """界面读的字段必须和接口真实返回的一致。

    之前界面按 ``experiment.rank`` 取实验参数，而接口把参数放在
    ``experiment.config`` 里——页面上会整列空白，且不会报错。
    """

    import json
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "apps/console/static/index.html").read_text(
        encoding="utf-8"
    )

    # 实验参数嵌套在 config 下
    assert "e.config || {}" in page
    # 数据集必须带 source_types（接口要求的必填字段）
    assert "source_types" in page
    # 事件流、计划、trace、summary 四个端点都要被用到
    for suffix in ["/plan", "/events", "/trace", "/summary"]:
        assert suffix in page
    # 页面里的 JSON.parse 只应出现在“元数据”和“工具入参”两处输入框
    assert page.count("JSON.parse") <= 3

    # 交叉验证：真实响应里确实没有顶层 rank，只有 config.rank
    dataset = client.post("/multimodal/datasets", json={"name": "ui-contract", "source_types": ["image"]})
    assert dataset.status_code == 201
    experiment = client.post(
        "/multimodal/experiments",
        json={
            "name": "ui-contract-exp",
            "dataset_id": dataset.json()["dataset_id"],
            "rank": 8,
            "alpha": 16,
            "learning_rate": 0.0002,
            "epochs": 1,
        },
    )
    assert experiment.status_code == 201
    payload = experiment.json()
    assert "rank" not in payload
    assert payload["config"]["rank"] == 8
    json.dumps(payload)  # 必须可序列化
