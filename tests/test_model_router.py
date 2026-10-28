"""Multi-provider routing, retries and output safety."""

import pytest

from packages.model_gateway.protocol import ChatResult, SafetyVerdict
from packages.model_gateway.retry import retry_call
from packages.model_gateway.router import ModelRouter, ModelRouterError, SafetyViolation
from packages.model_gateway.usage import Usage


class FakeProvider:
    def __init__(self, model: str, outcomes: list[object]) -> None:
        self.model = model
        self.outcomes = outcomes
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, *, tools=None, response_model=None, metadata=None):
        self.calls.append(messages)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok(model: str, content: str = "ok") -> ChatResult:
    return ChatResult(content=content, model=model, usage=Usage())


def test_router_falls_back_to_the_next_provider() -> None:
    from packages.model_gateway.openai_compatible import ModelGatewayError

    primary = FakeProvider("primary", [ModelGatewayError("upstream 503")])
    secondary = FakeProvider("secondary", [_ok("secondary")])
    router = ModelRouter([primary, secondary], sleeper=lambda seconds: None)

    result = router.complete([{"role": "user", "content": "hi"}])

    assert result.model == "secondary"
    # The attempt history records both the failure and the successful fallback.
    assert [attempt.provider for attempt in router.attempts] == ["primary", "secondary"]
    assert router.attempts[0].outcome == "error"
    assert router.attempts[1].outcome == "ok"


def test_router_raises_with_attempt_history_when_all_fail() -> None:
    from packages.model_gateway.openai_compatible import ModelGatewayError

    router = ModelRouter(
        [
            FakeProvider("a", [ModelGatewayError("boom")]),
            FakeProvider("b", [ModelGatewayError("boom")]),
        ],
        sleeper=lambda seconds: None,
    )

    with pytest.raises(ModelRouterError) as info:
        router.complete([{"role": "user", "content": "hi"}])

    assert [attempt.provider for attempt in info.value.attempts] == ["a", "b"]


def test_router_retries_transient_failure_on_same_provider() -> None:
    from packages.model_gateway.openai_compatible import ModelGatewayError

    provider = FakeProvider("a", [ModelGatewayError("timeout"), _ok("a")])
    router = ModelRouter([provider], retries=1, sleeper=lambda seconds: None)

    result = router.complete([{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert len(provider.calls) == 2


def test_router_raises_on_blocked_output() -> None:
    def block(content: str) -> SafetyVerdict:
        return SafetyVerdict(allowed=False, reason="pii detected")

    provider = FakeProvider("a", [_ok("a", "secret data")])
    router = ModelRouter([provider], security_check=block)

    with pytest.raises(SafetyViolation, match="pii detected"):
        router.complete([{"role": "user", "content": "hi"}])


def test_router_passes_when_safety_allows() -> None:
    provider = FakeProvider("a", [_ok("a")])
    router = ModelRouter([provider], security_check=lambda content: SafetyVerdict(allowed=True))

    assert router.complete([{"role": "user", "content": "hi"}]).content == "ok"


def test_retry_call_uses_exponential_backoff() -> None:
    delays: list[float] = []
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("slow")
        return "done"

    result = retry_call(
        flaky,
        attempts=3,
        base_delay=0.1,
        sleeper=delays.append,
        is_retryable=lambda error: isinstance(error, TimeoutError),
    )

    assert result == "done"
    assert delays == [0.1, 0.2]


def test_retry_call_stops_on_non_retryable_error() -> None:
    attempts = {"count": 0}

    def bad() -> str:
        attempts["count"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        retry_call(
            bad,
            attempts=3,
            sleeper=lambda seconds: None,
            is_retryable=lambda error: isinstance(error, TimeoutError),
        )

    assert attempts["count"] == 1