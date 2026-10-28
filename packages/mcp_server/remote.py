"""HTTP client for remote MCP servers (REST legacy + JSON-RPC)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .resilience import CircuitBreaker, CircuitOpenError
from .security import SecurityPolicy, UnsafeTargetError


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
        protocol: str = "rest",
        retries: int = 0,
        breaker: CircuitBreaker | None = None,
        policy: SecurityPolicy | None = None,
        sleeper: Callable[[float], None] | None = None,
        audit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        try:
            (policy or SecurityPolicy()).check(self.base_url)
        except UnsafeTargetError as exc:
            raise RemoteMCPError(f"unsafe MCP endpoint: {exc}") from exc

        if protocol not in {"rest", "jsonrpc"}:
            raise ValueError(f"unsupported MCP protocol: {protocol}")
        self.protocol = protocol
        self.timeout_seconds = float(timeout_seconds)
        self.request_json = request_json
        self.retries = max(0, retries)
        self.breaker = breaker
        self.audit = audit
        self._sleeper = sleeper or time.sleep
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    # ------------------------------------------------------------------ tools
    def list_tools(self) -> list[dict[str, Any]]:
        if self.protocol == "jsonrpc":
            result = self._rpc("tools/list")
            tools = result.get("tools")
            if not isinstance(tools, list):
                raise RemoteMCPError("remote MCP tools response must be a list")
            return tools

        result = self._request("GET", f"{self.base_url}/mcp/tools")
        if not isinstance(result, list):
            raise RemoteMCPError("remote MCP tools response must be a list")
        return result

    def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.protocol == "jsonrpc":
            result = self._rpc("tools/call", {"name": name, "arguments": payload})
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                return structured
            return result

        result = self._request("POST", f"{self.base_url}/mcp/tools/{name}", payload)
        if not isinstance(result, dict):
            raise RemoteMCPError("remote MCP tool response must be an object")
        return result

    def health(self) -> dict[str, Any]:
        result = self._request("GET", f"{self.base_url}/health")
        if not isinstance(result, dict):
            raise RemoteMCPError("remote MCP health response must be an object")
        return result

    # --------------------------------------------------------------- internals
    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params or {},
        }
        data = self._request("POST", f"{self.base_url}/mcp", body)
        if not isinstance(data, dict):
            raise RemoteMCPError("remote MCP JSON-RPC response must be an object")
        error = data.get("error")
        if isinstance(error, dict):
            raise RemoteMCPError(
                f"remote MCP error {error.get('code')}: {error.get('message')}"
            )
        result = data.get("result")
        if not isinstance(result, dict):
            raise RemoteMCPError("remote MCP JSON-RPC response has no result object")
        return result

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        last_error: RemoteMCPError | None = None

        for attempt in range(self.retries + 1):
            if self.breaker is not None and not self.breaker.allow():
                raise CircuitOpenError("MCP circuit breaker is open")

            try:
                result = self.request_json(
                    method, url, self.headers, payload, self.timeout_seconds
                )
            except RemoteMCPError as exc:
                last_error = exc
                if self.breaker is not None:
                    self.breaker.record_failure()
                if attempt < self.retries:
                    self._sleeper(min(0.05 * (2**attempt), 1.0))
                    continue
                self._audit(method, url, "error")
                raise
            except Exception as exc:  # noqa: BLE001 - normalised into RemoteMCPError
                last_error = RemoteMCPError(f"remote MCP request failed: {exc}")
                if self.breaker is not None:
                    self.breaker.record_failure()
                if attempt < self.retries:
                    self._sleeper(min(0.05 * (2**attempt), 1.0))
                    continue
                self._audit(method, url, "error")
                raise last_error from exc

            if self.breaker is not None:
                self.breaker.record_success()
            self._audit(method, url, "ok")
            return result

        raise last_error or RemoteMCPError("remote MCP request failed")

    def _audit(self, method: str, url: str, outcome: str) -> None:
        if self.audit is None:
            return
        self.audit(
            {
                "event": "mcp.remote_call",
                "method": method,
                "url": url,
                "outcome": outcome,
            }
        )