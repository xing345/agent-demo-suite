from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ModelGateway
from .calling import parse_tool_calls, tools_from_definitions
from .protocol import ChatResult
from .streaming import StreamAssembler, StreamDelta, iter_sse_events
from .usage import PriceTable, usage_from_response


class ModelGatewayError(RuntimeError):
    """Raised when a model provider cannot produce a valid response."""


PostJSON = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
PostStream = Callable[[str, dict[str, str], dict[str, Any], float], Iterable[str]]


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelGatewayError(f"model provider HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ModelGatewayError(f"model provider network error: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ModelGatewayError("model provider returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ModelGatewayError("model provider response must be an object")
    return data


def _post_stream(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> Iterator[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                yield raw_line.decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ModelGatewayError(f"model provider HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ModelGatewayError(f"model provider network error: {exc.reason}") from exc


class OpenAICompatibleGateway(ModelGateway):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60,
        post_json: PostJSON = _post_json,
        post_stream: PostStream | None = None,
        supports_streaming: bool = True,
        prices: PriceTable | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.post_json = post_json
        self.post_stream = post_stream or _post_stream
        self.supports_streaming = supports_streaming
        self.prices = prices or PriceTable()
        self.last_stream_result: ChatResult | None = None

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self.generate_sync(
            messages,
            response_model=response_model,
            tools=tools,
            metadata=metadata,
        )

    def generate_sync(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if metadata:
            payload.update(metadata)
        data = self.post_json(
            f"{self.base_url}/chat/completions",
            self.headers,
            payload,
            self.timeout_seconds,
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelGatewayError("model response missing choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ModelGatewayError("model response content must be a string")
        if response_model is None:
            return content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelGatewayError("structured model response is not valid JSON") from exc
        return response_model.model_validate(parsed)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[Any] | None = None,
        response_model: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatResult:
        """One chat call that also reports usage, tool calls and latency."""
        payload = self._chat_payload(messages, tools=tools, metadata=metadata)
        if response_model is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": getattr(response_model, "__name__", "response"),
                    "schema": response_model.model_json_schema(),
                    "strict": True,
                },
            }

        started = perf_counter()
        data = self.post_json(
            f"{self.base_url}/chat/completions",
            self.headers,
            payload,
            self.timeout_seconds,
        )
        latency_ms = int((perf_counter() - started) * 1000)

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelGatewayError("model response missing choices[0].message") from exc

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ModelGatewayError("model response content must be a string")

        structured: Any | None = None
        if response_model is not None:
            try:
                structured = response_model.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ModelGatewayError(
                    "structured model response is not valid JSON for the schema"
                ) from exc

        return ChatResult(
            content=content,
            model=str(data.get("model") or self.model),
            tool_calls=parse_tool_calls(message),
            usage=usage_from_response(
                data.get("usage"), model=self.model, prices=self.prices
            ),
            latency_ms=latency_ms,
            structured=structured,
        )

    def stream_sync(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[StreamDelta]:
        if not self.supports_streaming:
            result = self.complete(messages, tools=tools, metadata=metadata)
            self.last_stream_result = result
            yield StreamDelta(text=result.content)
            return

        payload = self._chat_payload(messages, tools=tools, metadata=metadata)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        assembler = StreamAssembler(prices=self.prices)
        for event in iter_sse_events(
            self.post_stream(
                f"{self.base_url}/chat/completions",
                self.headers,
                payload,
                self.timeout_seconds,
            )
        ):
            yield assembler.feed(event)
        self.last_stream_result = assembler.result()

    def _chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[Any] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            if hasattr(tools[0], "model_dump"):
                payload["tools"] = tools_from_definitions(tools)
            else:
                payload["tools"] = list(tools)
        if metadata:
            payload.update(metadata)
        return payload

    async def embed(
        self,
        texts: list[str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[list[float]]:
        return self.embed_sync(texts, metadata=metadata)

    def embed_sync(
        self,
        texts: list[str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if metadata:
            payload.update(metadata)
        data = self.post_json(
            f"{self.base_url}/embeddings",
            self.headers,
            payload,
            self.timeout_seconds,
        )
        try:
            embeddings = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise ModelGatewayError("embedding response missing data[].embedding") from exc
        if not all(isinstance(item, list) for item in embeddings):
            raise ModelGatewayError("embedding values must be lists")
        return embeddings
