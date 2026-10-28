"""Execute tool handlers with timeouts, retries and bounded concurrency."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

Handler = Callable[[dict[str, Any]], dict[str, Any]]

RETRYABLE_ERROR_NAMES = frozenset(
    {
        "TaskTimeout",
        "TimeoutError",
        "ConnectionError",
        "OSError",
        "RemoteMCPError",
        "ModelGatewayError",
    }
)


class TaskTimeout(TimeoutError):
    """Raised internally when a handler exceeds its deadline."""


@dataclass(frozen=True)
class HandlerCall:
    task_id: str
    handler: Handler
    payload: dict[str, Any]
    timeout_seconds: float | None = None
    max_retries: int = 0


@dataclass
class AttemptResult:
    task_id: str
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    timed_out: bool = False


def default_is_retryable(error: BaseException) -> bool:
    return any(base.__name__ in RETRYABLE_ERROR_NAMES for base in type(error).__mro__)


class TaskExecutor:
    """Submits handler calls to a thread pool; timeouts and retries are per task.

    A timed-out handler cannot be interrupted in Python; the deadline only stops
    the runtime from *waiting* for it. That is recorded as ``timed_out`` so the
    caller can surface it instead of hiding it.
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 1,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        backoff_base: float = 0.05,
        backoff_max: float = 1.0,
        is_retryable: Callable[[BaseException], bool] | None = None,
    ) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self._pool = ThreadPoolExecutor(
            max_workers=self.max_concurrency, thread_name_prefix="runtime-task"
        )
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self._backoff_base = max(0.0, backoff_base)
        self._backoff_max = max(self._backoff_base, backoff_max)
        self._is_retryable = is_retryable or default_is_retryable

    def run_batch(self, calls: list[HandlerCall]) -> list[AttemptResult]:
        futures = [
            (call, self._pool.submit(self._invoke, call.handler, call.payload))
            for call in calls
        ]
        return [self._collect(call, future) for call, future in futures]

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _invoke(handler: Handler, payload: dict[str, Any]) -> dict[str, Any]:
        return handler(payload)

    def _collect(self, call: HandlerCall, future: Any) -> AttemptResult:
        started = self._clock()
        attempts = 0
        timed_out = False

        while True:
            attempts += 1
            try:
                output = future.result(timeout=call.timeout_seconds)
                return AttemptResult(
                    task_id=call.task_id,
                    ok=True,
                    output=output,
                    attempts=attempts,
                    latency_ms=int((self._clock() - started) * 1000),
                )
            except FutureTimeout:
                timed_out = True
                error: BaseException = TaskTimeout(
                    f"task {call.task_id} exceeded {call.timeout_seconds}s"
                )
            except Exception as exc:  # noqa: BLE001 - every failure is classified below
                error = exc

            retryable = self._is_retryable(error)
            if attempts > call.max_retries or not retryable:
                return AttemptResult(
                    task_id=call.task_id,
                    ok=False,
                    error=str(error) or type(error).__name__,
                    error_type=type(error).__name__,
                    attempts=attempts,
                    latency_ms=int((self._clock() - started) * 1000),
                    timed_out=timed_out,
                )

            delay = min(
                self._backoff_base * (2 ** (attempts - 1)),
                self._backoff_max,
            )
            self._sleeper(delay)
            future = self._pool.submit(self._invoke, call.handler, call.payload)