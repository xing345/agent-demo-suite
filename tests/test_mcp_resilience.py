"""Retry, circuit breaking and health checks for the MCP client."""

import pytest

from packages.mcp_server import MCPRemoteClient, RemoteMCPError
from packages.mcp_server.resilience import CircuitBreaker, CircuitOpenError


def test_breaker_opens_then_half_opens_then_closes() -> None:
    now = {"value": 0.0}
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10, clock=lambda: now["value"])

    breaker.record_failure()
    assert breaker.allow() is True
    assert breaker.state == "closed"

    breaker.record_failure()
    assert breaker.allow() is False
    assert breaker.state == "open"

    now["value"] = 11
    assert breaker.allow() is True
    assert breaker.state == "half_open"

    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow() is True


def test_client_retries_transient_failures() -> None:
    calls = {"count": 0}

    def flaky(method, url, headers, payload, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RemoteMCPError("transient outage")
        return [{"name": "read_context"}]

    client = MCPRemoteClient(
        "https://mcp.example.com",
        request_json=flaky,
        retries=2,
        sleeper=lambda seconds: None,
    )

    tools = client.list_tools()

    assert tools[0]["name"] == "read_context"
    assert calls["count"] == 3


def test_client_gives_up_after_retry_budget() -> None:
    client = MCPRemoteClient(
        "https://mcp.example.com",
        request_json=lambda *args: (_ for _ in ()).throw(RemoteMCPError("down")),
        retries=1,
        sleeper=lambda seconds: None,
    )

    with pytest.raises(RemoteMCPError, match="down"):
        client.list_tools()


def test_client_stops_calling_when_circuit_is_open() -> None:
    now = {"value": 0.0}
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=60, clock=lambda: now["value"])
    calls = {"count": 0}

    def failing(method, url, headers, payload, timeout):
        calls["count"] += 1
        raise RemoteMCPError("down")

    client = MCPRemoteClient(
        "https://mcp.example.com",
        request_json=failing,
        breaker=breaker,
        sleeper=lambda seconds: None,
    )

    with pytest.raises(RemoteMCPError):
        client.list_tools()
    with pytest.raises(CircuitOpenError):
        client.list_tools()
    assert calls["count"] == 1


def test_health_check_returns_payload() -> None:
    client = MCPRemoteClient(
        "https://mcp.example.com",
        request_json=lambda method, url, headers, payload, timeout: {"status": "ok"},
    )

    assert client.health() == {"status": "ok"}


def test_jsonrpc_client_unwraps_structured_content() -> None:
    def rpc(method, url, headers, payload, timeout):
        assert method == "POST"
        assert payload["method"] == "tools/call"
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"structuredContent": {"answer": 42}, "content": []},
        }

    client = MCPRemoteClient("https://mcp.example.com", request_json=rpc, protocol="jsonrpc")

    assert client.call_tool("answer_tool", {"q": "life"}) == {"answer": 42}


def test_jsonrpc_client_surfaces_error_objects() -> None:
    def rpc(method, url, headers, payload, timeout):
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "error": {"code": -32602, "message": "unknown tool"},
        }

    client = MCPRemoteClient("https://mcp.example.com", request_json=rpc, protocol="jsonrpc")

    with pytest.raises(RemoteMCPError, match="unknown tool"):
        client.call_tool("ghost", {})