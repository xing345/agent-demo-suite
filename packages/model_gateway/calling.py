"""Translate tool definitions to provider schemas and back."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..tool_registry import ToolDefinition
from .protocol import ToolCall


def tools_from_definitions(tools: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for tool in tools:
        parameters = dict(tool.input_schema or {})
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        payload.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": parameters,
                },
            }
        )
    return payload


def parse_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index, item in enumerate(message.get("tool_calls") or []):
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        raw = function.get("arguments")
        raw_text = "" if raw is None else str(raw)
        arguments, error = parse_arguments(raw_text)
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call_{index}"),
                name=str(function.get("name") or ""),
                arguments=arguments,
                raw_arguments=raw_text,
                parse_error=error,
            )
        )
    return calls


def parse_arguments(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw.strip():
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid tool arguments JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return {}, "tool arguments must be a JSON object"
    return parsed, None