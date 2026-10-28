"""In-process MCP-style tool server with a JSON-RPC 2.0 entry point.

The class keeps the original ``list_tools``/``call_tool`` surface; JSON-RPC is a
second face over the same registry so the REST transport stays compatible.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError

from packages.tool_registry import ToolDefinition, ToolRegistry

AuditSink = Callable[[dict[str, Any]], None]

SERVER_NAME = "agent-demo-suite-mcp"
SERVER_VERSION = "0.2.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class MCPServer:
    def __init__(self, *, audit: AuditSink | None = None) -> None:
        self.registry = ToolRegistry()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.audit = audit

    # ---------------------------------------------------------------- registry
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

    def tool_payloads(self) -> list[dict[str, Any]]:
        """MCP-shaped tool descriptors (camelCase, JSON Schema, version)."""
        payloads: list[dict[str, Any]] = []
        for tool in self.registry.list():
            schema = dict(tool.input_schema or {})
            schema.setdefault("type", "object")
            payloads.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": schema,
                    "version": tool.version,
                }
            )
        return payloads

    def manifest(self) -> dict[str, dict[str, str]]:
        return {
            tool.name: {
                "version": tool.version,
                "schema_sha256": _digest(tool.input_schema),
            }
            for tool in self.registry.list()
        }

    # ------------------------------------------------------------------- calls
    def call_tool(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        principal: str = "anonymous",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            definition = self.registry.get(name)
            handler = self.handlers[name]
        except KeyError as exc:
            self._audit(name, payload, principal, "error", started, "UNKNOWN_TOOL")
            raise KeyError(f"unknown MCP tool: {name}") from exc

        try:
            self._validate(definition, payload)
            output = handler(payload)
        except (ValueError, JsonSchemaError) as exc:
            self._audit(name, payload, principal, "error", started, "INVALID_INPUT")
            raise ValueError(str(exc)) from exc

        self._audit(name, payload, principal, "ok", started, None)
        return output

    def _validate(self, definition: ToolDefinition, payload: dict[str, Any]) -> None:
        schema = definition.input_schema or {"type": "object"}
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        if not errors:
            return
        first = errors[0]
        if first.validator == "required":
            missing = _extract_property(first.message)
            raise ValueError(f"missing required input: {missing}")
        raise ValueError(f"invalid input for {definition.name}: {first.message}")

    def _audit(
        self,
        name: str,
        payload: dict[str, Any],
        principal: str,
        outcome: str,
        started: float,
        error_code: str | None,
    ) -> None:
        if self.audit is None:
            return
        self.audit(
            {
                "event": "mcp.tool_call",
                "tool": name,
                "principal": principal,
                "args_sha256": _digest(payload),
                "outcome": outcome,
                "error_code": error_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )

    # ---------------------------------------------------------------- JSON-RPC
    def handle_jsonrpc(
        self,
        message: Any,
        *,
        principal: str = "anonymous",
    ) -> dict[str, Any]:
        request_id = message.get("id") if isinstance(message, dict) else None
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return _error(request_id, -32600, "invalid request")

        method = str(message["method"])
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, -32602, "params must be an object")

        try:
            if method == "initialize":
                return _result(
                    request_id,
                    {
                        "protocolVersion": str(
                            params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
                        ),
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                        "capabilities": {"tools": {"listChanged": False}},
                    },
                )
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": self.tool_payloads()})
            if method == "tools/call":
                name = params.get("name")
                if not isinstance(name, str) or not name:
                    return _error(
                        request_id, -32602, "tool name is required", {"code": "INVALID_PARAMS"}
                    )
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    return _error(
                        request_id,
                        -32602,
                        "arguments must be an object",
                        {"code": "INVALID_PARAMS"},
                    )
                output = self.call_tool(name, arguments, principal=principal)
                return _result(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(output, ensure_ascii=False),
                            }
                        ],
                        "structuredContent": output,
                        "isError": False,
                    },
                )
        except KeyError as exc:
            return _error(request_id, -32602, str(exc), {"code": "UNKNOWN_TOOL"})
        except ValueError as exc:
            return _error(request_id, -32602, str(exc), {"code": "INVALID_INPUT"})

        return _error(request_id, -32601, f"method not found: {method}")


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _extract_property(message: str) -> str:
    if "'" in message:
        return message.split("'")[1]
    return message


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}