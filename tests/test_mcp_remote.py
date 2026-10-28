import pytest

from packages.mcp_server import MCPRemoteClient, RemoteMCPError


def test_remote_mcp_client_lists_and_calls_tools() -> None:
    calls = []

    def fake_request(method, url, headers, payload, timeout):
        calls.append((method, url, headers, payload, timeout))
        if method == "GET":
            return [{"name": "read_context", "source": "mcp"}]
        return {"result": payload["query"]}

    client = MCPRemoteClient("http://mcp.test", request_json=fake_request)

    assert client.list_tools()[0]["name"] == "read_context"
    assert client.call_tool("read_context", {"query": "README"}) == {
        "result": "README"
    }
    assert calls[0][0] == "GET"
    assert calls[1][0] == "POST"


def test_remote_mcp_client_surfaces_remote_errors() -> None:
    client = MCPRemoteClient(
        "http://mcp.test",
        request_json=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("connection refused")
        ),
    )

    with pytest.raises(RemoteMCPError, match="connection refused"):
        client.list_tools()
