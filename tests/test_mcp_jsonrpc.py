"""JSON-RPC 2.0 surface of the MCP server (`POST /mcp`)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.runtime_harness.main import app
from packages.mcp_server import MCPServer, create_mcp_router
from packages.mcp_server.auth import TokenAuthenticator
from packages.tool_registry import ToolDefinition

client = TestClient(app, raise_server_exceptions=False)


def _rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_initialize_returns_server_capabilities() -> None:
    body = _rpc("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test"}})

    result = body["result"]
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"]
    assert "tools" in result["capabilities"]
    assert body["id"] == 1


def test_tools_list_exposes_schema_and_version() -> None:
    tools = _rpc("tools/list")["result"]["tools"]

    assert tools
    first = tools[0]
    assert {"name", "description", "inputSchema", "version"} <= set(first)
    assert first["inputSchema"]["type"] == "object"


def test_tools_call_returns_structured_content() -> None:
    body = _rpc("tools/call", {"name": "read_context", "arguments": {"query": "README"}})

    result = body["result"]
    assert result["structuredContent"] == {"result": "README"}
    assert result["content"][0]["type"] == "text"


def test_unknown_method_returns_method_not_found() -> None:
    body = _rpc("does/not/exist")

    assert body["error"]["code"] == -32601
    assert "method" in body["error"]["message"].lower()


def test_unknown_tool_returns_invalid_params() -> None:
    body = _rpc("tools/call", {"name": "ghost", "arguments": {}})

    assert body["error"]["code"] == -32602
    assert body["error"]["data"]["code"] == "UNKNOWN_TOOL"


def test_invalid_envelope_returns_invalid_request() -> None:
    body = client.post("/mcp", json={"foo": "bar"}).json()

    assert body["error"]["code"] == -32600


def test_jsonrpc_endpoint_enforces_bearer_token() -> None:
    server = MCPServer()
    server.register_tool(
        ToolDefinition(name="ping_tool", source="mcp"),
        lambda payload: {"ok": True},
    )
    guarded = FastAPI()
    guarded.include_router(
        create_mcp_router(
            server,
            authenticator=TokenAuthenticator("secret", scopes={"mcp:tools"}),
        )
    )
    guarded_client = TestClient(guarded, raise_server_exceptions=False)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    assert guarded_client.post("/mcp", json=request).status_code == 401
    assert (
        guarded_client.post(
            "/mcp", json=request, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    allowed = guarded_client.post(
        "/mcp", json=request, headers={"Authorization": "Bearer secret"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["result"]["tools"][0]["name"] == "ping_tool"