from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteMCPError(RuntimeError):
    """Raised when a remote MCP endpoint cannot be reached or understood."""


RequestJSON = Callable[
    [str, str, dict[str, str], dict[str, Any] | None, float],
    Any,
]


def _request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: float,
) -> Any:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={**headers, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RemoteMCPError(f"remote MCP HTTP {exc.code}: {detail}") from exc
    except (URLError, json.JSONDecodeError) as exc:
        raise RemoteMCPError(f"remote MCP request failed: {exc}") from exc


class MCPRemoteClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_seconds: float = 30,
        request_json: RequestJSON = _request_json,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.request_json = request_json
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def list_tools(self) -> list[dict[str, Any]]:
        try:
            result = self.request_json(
                "GET", f"{self.base_url}/mcp/tools", self.headers, None, self.timeout_seconds
            )
        except Exception as exc:
            if isinstance(exc, RemoteMCPError):
                raise
            raise RemoteMCPError(str(exc)) from exc
        if not isinstance(result, list):
            raise RemoteMCPError("remote MCP tools response must be a list")
        return result

    def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.request_json(
                "POST",
                f"{self.base_url}/mcp/tools/{name}",
                self.headers,
                payload,
                self.timeout_seconds,
            )
        except Exception as exc:
            if isinstance(exc, RemoteMCPError):
                raise
            raise RemoteMCPError(str(exc)) from exc
        if not isinstance(result, dict):
            raise RemoteMCPError("remote MCP tool response must be an object")
        return result
