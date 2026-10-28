from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from .auth import AuthError, Principal, TokenAuthenticator
from .server import MCPServer


def create_mcp_router(
    server: MCPServer,
    *,
    authenticator: TokenAuthenticator | None = None,
    required_scope: str = "mcp:tools",
) -> APIRouter:
    """Expose the server over REST (legacy) and JSON-RPC on the same prefix."""
    router = APIRouter(tags=["mcp"])

    def principal_from(authorization: str | None) -> Principal:
        if authenticator is None:
            return Principal()
        try:
            principal = authenticator.authenticate(authorization)
            authenticator.require(principal, required_scope)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return principal

    @router.get("/mcp/tools")
    def list_tools(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        principal_from(authorization)
        return [tool.model_dump(mode="json") for tool in server.list_tools()]

    @router.post("/mcp/tools/{tool_name}")
    def call_tool(
        tool_name: str,
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal = principal_from(authorization)
        try:
            return server.call_tool(tool_name, payload, principal=principal.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/mcp")
    def jsonrpc(
        message: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        principal = principal_from(authorization)
        return server.handle_jsonrpc(message, principal=principal.name)

    return router