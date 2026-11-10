"""Model-executed tasks must not report success when the model said it is blocked.

回归背景：演示时一个「读取仓库 -> 分析冲突 -> 生成问题清单」的计划，
4 个由模型执行的任务全部返回 ``{"status": "blocked", "reason": "未提供仓库路径"}``，
控制台却显示 5/5 completed、success_rate 1.0。原因是引擎只把「抛异常」当成失败，
而模型已经明确说「我做不了」时，那个 JSON 只能算是失败的输出，不是成功的结果。
"""

from __future__ import annotations

import pytest

from apps.runtime_harness.engine import RuntimeEngine
from packages.event_store import InMemoryEventStore
from packages.planner import PlannedTask, TaskPlan


class _StubGateway:
    """Gateway that returns whatever the test wants, no network involved."""

    model = "stub-model"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def generate_sync(self, messages: list[dict[str, str]]) -> str:
        return self.payload


def _plan() -> TaskPlan:
    return TaskPlan(goal="读取仓库结构", tasks=[PlannedTask(task_id="t1", name="read")])


def _engine(payload: str) -> RuntimeEngine:
    return RuntimeEngine(InMemoryEventStore(), model_gateway=_StubGateway(payload))


def _run(payload: str):  # noqa: ANN202 - helper kept tiny on purpose
    engine = _engine(payload)
    plan = _plan()
    run = engine.start_run(plan.goal)
    engine.execute_plan(run.run_id, plan)
    return engine.store.list_tasks(run.run_id)[0]


@pytest.mark.parametrize(
    "payload",
    [
        # 现场真实出现过的那种输出
        '{"status": "blocked", "reason": "未提供仓库路径"}',
        # 英文 blocked，同样要识别
        '{"status": "blocked", "reason": "no repository path provided"}',
        # 大小写不同也要识别
        '{"status": "BLOCKED", "reason": "missing input"}',
    ],
)
def test_blocked_output_is_recorded_as_task_failure(payload: str) -> None:
    task = _run(payload)
    assert task.status == "failed", "模型说 blocked 时任务不能记成 completed"


def test_blocked_task_carries_the_model_reason() -> None:
    task = _run('{"status": "blocked", "reason": "未提供仓库路径"}')
    assert "未提供仓库路径" in str(task.metadata)


def test_normal_output_still_counts_as_success() -> None:
    task = _run('{"status": "ok", "content": "顶层目录共 12 个文件"}')
    assert task.status == "completed"


def test_blocked_is_not_confused_with_a_merely_short_回答() -> None:
    task = _run('{"content": "顶层目录共 12 个文件，没有依赖冲突。"}')
    assert task.status == "completed", "没有 status 字段的正常回答不能被误判成失败"