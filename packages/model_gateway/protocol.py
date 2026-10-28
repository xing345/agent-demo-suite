"""Provider-neutral chat results and the provider protocol."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .usage import Usage


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""
    parse_error: str | None = None


@dataclass
class ChatResult:
    content: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    structured: Any | None = None


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool = True
    reason: str | None = None


class ModelProvider(Protocol):
    """The runtime only needs this much from a provider."""

    model: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_model: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatResult: ...


class SyncModelGateway(Protocol):
    """Minimal synchronous surface the runtime and planner depend on."""

    model: str

    def generate_sync(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...


def stream_of(result: ChatResult) -> Iterable[str]:
    """Convenience for callers that only want the text."""
    yield result.content