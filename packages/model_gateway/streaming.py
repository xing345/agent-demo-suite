"""SSE parsing and incremental assembly of a streamed chat completion."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .calling import parse_arguments
from .protocol import ChatResult, ToolCall
from .usage import PriceTable, Usage, usage_from_response

DONE_SENTINEL = "[DONE]"


def iter_sse_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Yield JSON payloads from an SSE byte stream; stop at ``[DONE]``."""
    buffer: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if buffer:
                payload = "\n".join(buffer)
                buffer = []
                if payload.strip() == DONE_SENTINEL:
                    return
                yield json.loads(payload)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())

    if buffer:
        payload = "\n".join(buffer)
        if payload.strip() != DONE_SENTINEL:
            yield json.loads(payload)


@dataclass
class StreamDelta:
    text: str = ""
    finish_reason: str | None = None


@dataclass
class _CallSlot:
    id: str = ""
    name: str = ""
    arguments: str = ""
    chunks: list[str] = field(default_factory=list)


class StreamAssembler:
    """Fold SSE chunks into a final ``ChatResult``."""

    def __init__(self, *, prices: PriceTable | None = None) -> None:
        self._prices = prices
        self._content: list[str] = []
        self._model = ""
        self._usage = Usage()
        self._calls: dict[int, _CallSlot] = {}

    def feed(self, event: dict[str, Any]) -> StreamDelta:
        if not isinstance(event, dict):
            return StreamDelta()

        if event.get("model") and not self._model:
            self._model = str(event["model"])

        if isinstance(event.get("usage"), dict):
            self._usage = usage_from_response(
                event["usage"], model=self._model or "unknown", prices=self._prices
            )

        choices = event.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}
        text = delta.get("content") or ""
        if text:
            self._content.append(str(text))

        for item in delta.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            index = int(item.get("index", 0))
            slot = self._calls.setdefault(index, _CallSlot())
            if item.get("id"):
                slot.id = str(item["id"])
            function = item.get("function") or {}
            if function.get("name"):
                slot.name += str(function["name"])
            if function.get("arguments"):
                slot.arguments += str(function["arguments"])

        return StreamDelta(text=str(text), finish_reason=choice.get("finish_reason"))

    def result(self) -> ChatResult:
        calls: list[ToolCall] = []
        for index in sorted(self._calls):
            slot = self._calls[index]
            arguments, error = parse_arguments(slot.arguments)
            calls.append(
                ToolCall(
                    id=slot.id or f"call_{index}",
                    name=slot.name,
                    arguments=arguments,
                    raw_arguments=slot.arguments,
                    parse_error=error,
                )
            )
        return ChatResult(
            content="".join(self._content),
            model=self._model or "unknown",
            tool_calls=calls,
            usage=self._usage,
        )