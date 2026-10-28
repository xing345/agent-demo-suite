from apps.runtime_harness.main import mcp_router


def test_runtime_exposes_remote_mcp_transport_routes() -> None:
    paths = {route.path for route in mcp_router.routes}

    assert "/mcp/tools" in paths
    assert "/mcp/tools/{tool_name}" in paths
