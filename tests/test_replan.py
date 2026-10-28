"""Bounded re-planning: keep finished work, replace the failed subgraph."""

from packages.planner import (
    DeterministicPlanner,
    PlannedTask,
    Replanner,
    TaskPlan,
    validate_plan,
)


def _plan() -> TaskPlan:
    return TaskPlan(
        goal="read then analyze then write then report",
        tasks=[
            PlannedTask(task_id="t1", name="read", description="read"),
            PlannedTask(task_id="t2", name="analyze", description="analyze", depends_on=["t1"]),
            PlannedTask(task_id="t3", name="generate", description="generate", depends_on=["t2"]),
            PlannedTask(task_id="t4", name="report", description="report", depends_on=["t3"]),
        ],
    )


def test_replan_keeps_upstream_and_replaces_downstream() -> None:
    replanner = Replanner(DeterministicPlanner(), max_replans=2)

    new_plan = replanner.next_plan(
        _plan(),
        failed_task_id="t2",
        error="model unavailable",
        completed_ids={"t1"},
    )

    assert new_plan is not None
    validate_plan(new_plan)
    ids = [task.task_id for task in new_plan.tasks]
    assert ids[0] == "t1"
    assert not {"t2", "t3", "t4"} & set(ids)
    assert new_plan.replan_count == 1
    assert new_plan.tasks[1].depends_on == ["t1"]
    assert new_plan.planner_version.startswith("replan:")


def test_replan_replaces_only_the_failed_tail() -> None:
    replanner = Replanner(DeterministicPlanner(), max_replans=2)

    new_plan = replanner.next_plan(
        _plan(),
        failed_task_id="t4",
        error="tool timeout",
        completed_ids={"t1", "t2", "t3"},
    )

    assert new_plan is not None
    validate_plan(new_plan)
    assert [task.task_id for task in new_plan.tasks][:3] == ["t1", "t2", "t3"]
    assert "t4" not in [task.task_id for task in new_plan.tasks]


def test_replan_budget_is_enforced() -> None:
    replanner = Replanner(DeterministicPlanner(), max_replans=1)
    exhausted = _plan().model_copy(update={"replan_count": 1})

    assert replanner.next_plan(exhausted, failed_task_id="t2", error="x") is None


def test_replan_ids_stay_unique() -> None:
    replanner = Replanner(DeterministicPlanner(), max_replans=3)
    plan = _plan()

    first = replanner.next_plan(plan, failed_task_id="t3", error="boom")
    assert first is not None
    second = replanner.next_plan(first, failed_task_id=first.tasks[1].task_id, error="boom")

    assert second is not None
    assert second.replan_count == 2
    ids = [task.task_id for task in second.tasks]
    assert len(ids) == len(set(ids))
    validate_plan(second)


def test_replan_emits_nothing_when_budget_is_zero() -> None:
    replanner = Replanner(DeterministicPlanner(), max_replans=0)

    assert replanner.next_plan(_plan(), failed_task_id="t1", error="x") is None