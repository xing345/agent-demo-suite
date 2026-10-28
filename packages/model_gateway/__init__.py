"""Model provider abstraction: providers, streaming, usage, routing."""

from .base import ModelGateway
from .calling import parse_tool_calls, tools_from_definitions
from .openai_compatible import ModelGatewayError, OpenAICompatibleGateway
from .protocol import (
    ChatResult,
    ModelProvider,
    SafetyVerdict,
    SyncModelGateway,
    ToolCall,
)
from .retry import retry_call
from .router import Attempt, ModelRouter, ModelRouterError, SafetyViolation
from .streaming import StreamAssembler, StreamDelta, iter_sse_events
from .usage import PriceTable, Usage, usage_from_response

__all__ = [
    "Attempt",
    "ChatResult",
    "ModelGateway",
    "ModelGatewayError",
    "ModelProvider",
    "ModelRouter",
    "ModelRouterError",
    "OpenAICompatibleGateway",
    "PriceTable",
    "SafetyVerdict",
    "SafetyViolation",
    "StreamAssembler",
    "StreamDelta",
    "SyncModelGateway",
    "ToolCall",
    "Usage",
    "iter_sse_events",
    "parse_tool_calls",
    "retry_call",
    "tools_from_definitions",
    "usage_from_response",
]