"""The old import path must keep working after the planner package move."""

from apps.runtime_harness.planner import DeterministicPlanner, PlannedTask, TaskPlan


def test_legacy_import_path_still_exports_planner_types() -> None:
    plan = DeterministicPlanner().plan("读取代码")

    assert isinstance(plan, TaskPlan)
    assert plan.tasks[0].name == "read"


def test_planned_task_defaults_stay_backwards_compatible() -> None:
    task = PlannedTask(name="read", description="read")

    assert task.depends_on == []
    assert task.max_retries == 0
    assert task.timeout_seconds is None
    assert task.tool_name is None


def test_plan_carries_version_and_replan_counter() -> None:
    plan = DeterministicPlanner().plan("读取代码")

    assert plan.planner_version == "deterministic/1"
    assert plan.replan_count == 0
    assert plan.plan_id