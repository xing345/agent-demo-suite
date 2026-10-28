from collections.abc import Callable
from typing import Any

from packages.tool_registry import ToolDefinition, ToolRegistry


class MCPServer:
    """Small MCP-shaped adapter; transport can be added without changing tools."""

    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        if definition.source != "mcp":
            raise ValueError("MCP Server only accepts tools with source=mcp")
        self.registry.register(definition)
        self.handlers[definition.name] = handler

    def list_tools(self) -> list[ToolDefinition]:
        return self.registry.list()

    def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            definition = self.registry.get(name)
            handler = self.handlers[name]
        except KeyError as exc:
            raise KeyError(f"unknown MCP tool: {name}") from exc

        required = definition.input_schema.get("required", [])
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValueError(f"missing required input: {', '.join(missing)}")
        return handler(payload)
