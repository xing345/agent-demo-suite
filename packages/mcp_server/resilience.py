"""Failure handling primitives for outbound MCP calls."""

from __future__ import annotations

import time
from collections.abc import Callable


class CircuitOpenError(RuntimeError):
    """The circuit is open; calls are rejected without touching the network."""


class CircuitBreaker:
    """Closed -> open after ``failure_threshold`` failures, half-open after cooldown."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_timeout: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.reset_timeout = max(0.0, reset_timeout)
        self._clock = clock or time.monotonic
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._half_open else "open"

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at >= self.reset_timeout:
            self._half_open = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open = False

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures < self.failure_threshold and self._opened_at is None:
            return
        # Trip on the threshold, and re-arm the cooldown if a probe fails.
        self._half_open = False
        self._opened_at = self._clock()