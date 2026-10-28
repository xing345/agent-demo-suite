"""Task executor: timeout, retry with backoff, retryable classification."""

import time

from packages.runtime.executor import HandlerCall, TaskExecutor


def _call(
    handler,
    *,
    timeout: float | None = None,
    retries: int = 0,
    task_id: str = "t1",
) -> HandlerCall:
    return HandlerCall(
        task_id=task_id,
        handler=handler,
        payload={},
        timeout_seconds=timeout,
        max_retries=retries,
    )


def test_timeout_is_recorded_as_timed_out_failure() -> None:
    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch(
            [_call(lambda payload: time.sleep(0.5) or {"ok": True}, timeout=0.05)]
        )
    finally:
        executor.close()

    assert results[0].ok is False
    assert results[0].timed_out is True
    assert results[0].error_type == "TaskTimeout"


def test_retryable_failure_is_retried_then_succeeds() -> None:
    attempts = {"count": 0}

    def flaky(payload: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise OSError("connection reset")
        return {"ok": True}

    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch([_call(flaky, retries=2)])
    finally:
        executor.close()

    assert results[0].ok is True
    assert attempts["count"] == 2
    assert results[0].attempts == 2


def test_non_retryable_failure_stops_immediately() -> None:
    attempts = {"count": 0}

    def bad(payload: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        raise ValueError("bad input")

    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch([_call(bad, retries=3)])
    finally:
        executor.close()

    assert results[0].ok is False
    assert results[0].error_type == "ValueError"
    assert attempts["count"] == 1


def test_retry_budget_is_exhausted() -> None:
    attempts = {"count": 0}

    def always_down(payload: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        raise OSError("down")

    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch([_call(always_down, retries=2)])
    finally:
        executor.close()

    assert results[0].ok is False
    assert results[0].attempts == 3
    assert attempts["count"] == 3


def test_batch_runs_in_parallel_when_concurrency_allows() -> None:
    def slow(payload: dict[str, object]) -> dict[str, object]:
        time.sleep(0.2)
        return {"ok": True}

    executor = TaskExecutor(max_concurrency=3)
    started = time.perf_counter()
    try:
        results = executor.run_batch([_call(slow), _call(slow), _call(slow)])
    finally:
        executor.close()
    elapsed = time.perf_counter() - started

    assert all(result.ok for result in results)
    assert elapsed < 0.55