"""Minimal in-process MCP-style tool server."""

from .remote import MCPRemoteClient, RemoteMCPError
from .server import MCPServer
from .transport import create_mcp_router

__all__ = ["MCPServer", "MCPRemoteClient", "RemoteMCPError", "create_mcp_router"]
