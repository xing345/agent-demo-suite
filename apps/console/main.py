"""Agent Demo Suite 的统一控制台。

设计要点：

* **只做聚合，不复制业务逻辑**：两个既有 app（runtime harness、multimodal）
  以 ASGI 子应用的形式挂载在固定前缀下，控制台本身只提供界面与一个
  ``/console/api/*`` 的元信息聚合端点。
* 子应用仍以 ``import`` 方式构建，因此它们原有的 ``settings`` 与测试契约
  （``apps.runtime_harness.main:app`` / ``apps.multimodal_lora.main:app``）不变。
* 默认只监听回环地址，与两个既有 app 的默认 host 一致。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from apps.multimodal_lora.main import app as multimodal_app
from apps.runtime_harness.main import app as runtime_app
from packages.shared_config import get_settings

_STATIC_DIR = Path(__file__).with_name("static")

console = FastAPI(title="Agent Demo Suite Console", version="0.1.0")


@console.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@console.get("/console/api/config")
async def config() -> dict[str, Any]:
    """Non-secret view of the active configuration.

    Only booleans and non-sensitive strings are exposed: the console is a
    local tool, but it must still never echo API tokens to a browser.
    """

    settings = get_settings()
    return {
        "event_store_backend": settings.event_store_backend,
        "model_provider": settings.model_provider,
        "model_name": settings.model_name,
        "model_configured": bool(settings.model_name and settings.model_base_url),
        "mcp_remote_configured": bool(settings.mcp_remote_url),
        "mcp_protocol": settings.mcp_protocol,
        "mcp_server_auth": bool(settings.mcp_server_token),
        "executor_concurrency": settings.executor_concurrency,
        "max_replans": settings.max_replans,
        "approval_ttl_seconds": settings.approval_ttl_seconds,
        "max_upload_bytes": settings.max_upload_bytes,
        "routes": {
            "runtime": "/runtime",
            "multimodal": "/multimodal",
        },
    }


console.mount("/runtime", runtime_app)
console.mount("/multimodal", multimodal_app)

app = console

__all__ = ["app", "console"]


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(console, host=settings.console_host, port=settings.console_port)