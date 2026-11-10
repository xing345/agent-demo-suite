"""Fallback handler must work for every task, not only ones that carry a "query".

回归背景：现场跑「读取仓库结构并分析依赖冲突」时，五个任务全部失败，
错误信息是 ``KeyError: 'query'``。原因是引擎找不到同名工具时的兜底实现写死
``payload["query"]``，而调用约定给的是 ``goal/task_id/description/inputs``。
兜底的意思是「没有专用工具也能跑完」，不是「只对某一种任务有效」。
"""

from __future__ import annotations

from apps.runtime_harness.engine import RuntimeEngine
from packages.event_store import InMemoryEventStore
from packages.planner import PlannedTask, TaskPlan


def _plan(names: list[str]) -> TaskPlan:
    return TaskPlan(
        goal="读取仓库结构并分析依赖冲突",
        tasks=[
            PlannedTask(task_id=f"t{index}", name=name, description=f"做 {name}")
            for index, name in enumerate(names, start=1)
        ],
    )


def _execute(names: list[str]) -> list:
    engine = RuntimeEngine(InMemoryEventStore())
    plan = _plan(names)
    run = engine.start_run(plan.goal)
    engine.execute_plan(run.run_id, plan)
    return engine.store.list_tasks(run.run_id)


def test_tasks_without_registered_tool_still_complete() -> None:
    tasks = _execute(["读取仓库结构", "解析依赖清单", "生成问题清单"])

    assert [task.status for task in tasks] == ["completed", "completed", "completed"]


def test_fallback_output_does_not_raise_keyerror_on_missing_query() -> None:
    tasks = _execute(["读取仓库结构"])

    output = tasks[0].metadata.get("output")
    assert output["mode"] == "deterministic_fallback"
    assert "query" not in str(output.get("error", ""))


def test_fallback_is_marked_as_demo_not_dressed_up_as_real_work() -> None:
    tasks = _execute(["读取仓库结构"])

    # 兜底输出必须自报家门，否则演示时会把「什么都没做」误当成「做完了」
    assert tasks[0].metadata["output"]["mode"] == "deterministic_fallback"