"""Retry helper with exponential backoff and an injectable classifier."""

from __future__ import annotations

import time
from collections.abc import Callable

RetryPredicate = Callable[[BaseException], bool]


def default_is_retryable(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, ConnectionError, OSError))


def retry_call[T](
    func: Callable[[], T],
    *,
    attempts: int = 2,
    base_delay: float = 0.05,
    max_delay: float = 1.0,
    sleeper: Callable[[float], None] | None = None,
    is_retryable: RetryPredicate | None = None,
) -> T:
    total = max(1, attempts)
    sleep = sleeper or time.sleep
    predicate = is_retryable or default_is_retryable
    last_error: BaseException | None = None

    for attempt in range(total):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - re-raised below when not retryable
            last_error = exc
            if attempt >= total - 1 or not predicate(exc):
                break
            sleep(min(base_delay * (2**attempt), max_delay))

    assert last_error is not None
    raise last_error