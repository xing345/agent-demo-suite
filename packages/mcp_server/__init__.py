"""MCP-shaped tool server: REST legacy, JSON-RPC, auth and outbound policy."""

from .auth import AuthError, Principal, TokenAuthenticator
from .remote import MCPRemoteClient, RemoteMCPError
from .resilience import CircuitBreaker, CircuitOpenError
from .security import SecurityPolicy, UnsafeTargetError
from .server import MCPServer
from .transport import create_mcp_router

__all__ = [
    "AuthError",
    "CircuitBreaker",
    "CircuitOpenError",
    "MCPServer",
    "MCPRemoteClient",
    "Principal",
    "RemoteMCPError",
    "SecurityPolicy",
    "TokenAuthenticator",
    "UnsafeTargetError",
    "create_mcp_router",
]