from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .server import MCPServer


def create_mcp_router(server: MCPServer) -> APIRouter:
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.get("/tools")
    def list_tools() -> list[dict[str, Any]]:
        return [tool.model_dump(mode="json") for tool in server.list_tools()]

    @router.post("/tools/{tool_name}")
    def call_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return server.call_tool(tool_name, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
