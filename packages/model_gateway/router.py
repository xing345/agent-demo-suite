"""Multi-provider routing with retries, attempt history and output safety."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .openai_compatible import ModelGatewayError
from .protocol import ChatResult, ModelProvider, SafetyVerdict

SafetyCheck = Callable[[str], SafetyVerdict]


class SafetyViolation(RuntimeError):
    """Provider output was blocked by the configured safety policy."""


@dataclass(frozen=True)
class Attempt:
    provider: str
    attempt: int
    outcome: str
    error: str | None = None


class ModelRouterError(RuntimeError):
    def __init__(self, attempts: Sequence[Attempt]) -> None:
        detail = "; ".join(
            f"{item.provider}#{item.attempt}={item.outcome}"
            + (f"({item.error})" if item.error else "")
            for item in attempts
        )
        super().__init__(f"all model providers failed: {detail}")
        self.attempts = list(attempts)


class ModelRouter:
    """Try providers in order; retry transient errors; enforce safety once."""

    def __init__(
        self,
        providers: Sequence[ModelProvider],
        *,
        retries: int = 0,
        base_delay: float = 0.05,
        max_delay: float = 1.0,
        sleeper: Callable[[float], None] | None = None,
        security_check: SafetyCheck | None = None,
        is_retryable: Callable[[BaseException], bool] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = list(providers)
        self.retries = max(0, retries)
        self.base_delay = max(0.0, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self._sleeper = sleeper or time.sleep
        self.security_check = security_check
        self._is_retryable = is_retryable or _default_retryable
        self.attempts: list[Attempt] = []
        self.model = self.providers[0].model

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_model: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatResult:
        self.attempts = []

        for provider in self.providers:
            for attempt in range(self.retries + 1):
                try:
                    result = provider.complete(
                        messages,
                        tools=tools,
                        response_model=response_model,
                        metadata=metadata,
                    )
                except ModelGatewayError as exc:
                    self.attempts.append(
                        Attempt(
                            provider=provider.model,
                            attempt=attempt + 1,
                            outcome="error",
                            error=str(exc),
                        )
                    )
                    if attempt < self.retries and self._is_retryable(exc):
                        self._sleeper(
                            min(self.base_delay * (2**attempt), self.max_delay)
                        )
                        continue
                    break

                self.attempts.append(
                    Attempt(provider=provider.model, attempt=attempt + 1, outcome="ok")
                )
                self._enforce_safety(result)
                return result

        raise ModelRouterError(self.attempts)

    def _enforce_safety(self, result: ChatResult) -> None:
        if self.security_check is None:
            return
        verdict = self.security_check(result.content)
        if not verdict.allowed:
            raise SafetyViolation(verdict.reason or "blocked by security policy")

    def generate_sync(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Drop-in replacement for the single-provider synchronous API."""
        result = self.complete(
            messages,
            tools=tools,
            response_model=response_model,
            metadata=metadata,
        )
        return result.structured if result.structured is not None else result.content


def _default_retryable(error: BaseException) -> bool:
    # Provider-level failures (HTTP, network, malformed payloads) are worth one
    # more attempt; programming errors such as ValueError are not.
    return isinstance(error, (TimeoutError, ConnectionError, OSError, ModelGatewayError))