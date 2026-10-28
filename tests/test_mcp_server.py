import pytest

from packages.mcp_server import MCPServer
from packages.tool_registry import ToolDefinition


def test_mcp_server_lists_and_calls_registered_tool() -> None:
    server = MCPServer()
    server.register_tool(
        ToolDefinition(
            name="read_context",
            source="mcp",
            input_schema={"required": ["query"]},
        ),
        lambda payload: {"result": payload["query"]},
    )

    assert server.list_tools()[0].name == "read_context"
    assert server.call_tool("read_context", {"query": "README"}) == {
        "result": "README"
    }


def test_mcp_server_rejects_unknown_tool_and_missing_input() -> None:
    server = MCPServer()
    server.register_tool(
        ToolDefinition(
            name="read_context",
            source="mcp",
            input_schema={"required": ["query"]},
        ),
        lambda payload: payload,
    )

    with pytest.raises(KeyError, match="unknown MCP tool"):
        server.call_tool("missing", {})
    with pytest.raises(ValueError, match="missing required input"):
        server.call_tool("read_context", {})
