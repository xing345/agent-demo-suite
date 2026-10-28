from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ModelGateway


class ModelGatewayError(RuntimeError):
    """Raised when a model provider cannot produce a valid response."""


PostJSON = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


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


class OpenAICompatibleGateway(ModelGateway):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60,
        post_json: PostJSON = _post_json,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.post_json = post_json

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
