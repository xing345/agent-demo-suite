"""回归测试：executor 超时后不得重试同一 handler。

背景：``future.result(timeout=...)`` 超时只停止「等待」，被放弃的 handler 仍在
线程里运行。若此时重新 submit，同一个副作用会被并发执行两份（重复提交、重复
写库等），因此超时必须直接判失败，由上层用带幂等键的新调用重放。
"""

import time

from packages.runtime.executor import HandlerCall, TaskExecutor


def _call(handler, *, timeout: float | None = None, retries: int = 0) -> HandlerCall:
    return HandlerCall(
        task_id="t-timeout",
        handler=handler,
        payload={},
        timeout_seconds=timeout,
        max_retries=retries,
    )


def test_timeout_is_never_retried_so_side_effects_stay_single() -> None:
    calls = {"count": 0}

    def slow(payload: dict[str, object]) -> dict[str, object]:
        calls["count"] += 1
        time.sleep(0.3)
        return {"ok": True}

    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch([_call(slow, timeout=0.05, retries=5)])
        time.sleep(0.45)  # 让被放弃的 handler 跑完，观察是否被重复调用
    finally:
        executor.close()

    assert results[0].ok is False
    assert results[0].timed_out is True
    assert results[0].attempts == 1
    assert calls["count"] == 1


def test_retryable_error_is_still_retried() -> None:
    """超时不重试，但普通可重试错误（handler 已退出）仍然重试。"""
    calls = {"count": 0}

    def flaky(payload: dict[str, object]) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] < 2:
            raise OSError("connection reset")
        return {"ok": True}

    executor = TaskExecutor(max_concurrency=1, sleeper=lambda seconds: None)
    try:
        results = executor.run_batch([_call(flaky, retries=2)])
    finally:
        executor.close()

    assert results[0].ok is True
    assert results[0].timed_out is False
    assert calls["count"] == 2