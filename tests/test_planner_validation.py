"""Plan legality rules: duplicate ids, dangling deps, cycles, limits, tools."""

import pytest

from packages.planner import (
    DeterministicPlanner,
    PlannedTask,
    PlanValidationError,
    TaskPlan,
    topological_order,
    validate_plan,
)


def _chain(length: int) -> TaskPlan:
    tasks = [PlannedTask(task_id="t0", name="t0", description="t0")]
    for index in range(1, length):
        tasks.append(
            PlannedTask(
                task_id=f"t{index}",
                name=f"t{index}",
                description=f"t{index}",
                depends_on=[f"t{index - 1}"],
            )
        )
    return TaskPlan(goal="chain", tasks=tasks)


def _code(plan: TaskPlan, **kwargs: object) -> str:
    with pytest.raises(PlanValidationError) as info:
        validate_plan(plan, **kwargs)  # type: ignore[arg-type]
    return str(info.value.code)


def test_diamond_plan_is_valid_and_ordered() -> None:
    plan = TaskPlan(
        goal="diamond",
        tasks=[
            PlannedTask(task_id="a", name="a", description="a"),
            PlannedTask(task_id="b", name="b", description="b", depends_on=["a"]),
            PlannedTask(task_id="c", name="c", description="c", depends_on=["a"]),
            PlannedTask(task_id="d", name="d", description="d", depends_on=["b", "c"]),
        ],
    )

    order = topological_order(plan)

    assert order[0] == "a"
    assert order[-1] == "d"
    assert set(order) == {"a", "b", "c", "d"}
    validate_plan(plan)


def test_empty_plan_is_rejected() -> None:
    assert _code(TaskPlan(goal="empty", tasks=[])) == "EMPTY_PLAN"


def test_duplicate_task_id_is_rejected() -> None:
    plan = TaskPlan(
        goal="dup",
        tasks=[
            PlannedTask(task_id="a", name="a"),
            PlannedTask(task_id="a", name="b"),
        ],
    )

    assert _code(plan) == "DUPLICATE_TASK_ID"


def test_unknown_dependency_is_rejected() -> None:
    plan = TaskPlan(
        goal="dangling",
        tasks=[PlannedTask(task_id="a", name="a", depends_on=["ghost"])],
    )

    assert _code(plan) == "UNKNOWN_DEPENDENCY"


def test_cycle_is_rejected() -> None:
    plan = TaskPlan(
        goal="cycle",
        tasks=[
            PlannedTask(task_id="a", name="a", depends_on=["b"]),
            PlannedTask(task_id="b", name="b", depends_on=["a"]),
        ],
    )

    assert _code(plan) == "CYCLE_DETECTED"


def test_unknown_tool_is_rejected_when_tools_are_known() -> None:
    plan = TaskPlan(
        goal="tool",
        tasks=[PlannedTask(task_id="a", name="a", tool_name="ghost_tool")],
    )

    assert _code(plan, known_tools={"read_context"}) == "UNKNOWN_TOOL"


def test_task_limit_is_enforced() -> None:
    plan = TaskPlan(
        goal="wide",
        tasks=[PlannedTask(task_id=f"t{index}", name=f"t{index}") for index in range(21)],
    )

    assert _code(plan) == "TASK_LIMIT_EXCEEDED"


def test_depth_limit_is_enforced() -> None:
    assert _code(_chain(9), max_depth=8) == "DEPTH_EXCEEDED"
    validate_plan(_chain(8), max_depth=8)


def test_deterministic_planner_output_is_always_valid() -> None:
    planner = DeterministicPlanner()

    for goal in ("读取代码并分析问题", "inspect repository", "生成报告"):
        plan = planner.plan(goal)
        validate_plan(plan)
        assert plan.planner_version.startswith("deterministic")


def test_validation_error_serializes_code_and_task() -> None:
    plan = TaskPlan(goal="dup", tasks=[PlannedTask(task_id="a", name="a", depends_on=["x"])])

    with pytest.raises(PlanValidationError) as info:
        validate_plan(plan)

    payload = info.value.to_dict()
    assert payload["code"] == "UNKNOWN_DEPENDENCY"
    assert payload["task_id"] == "a"
    assert payload["detail"]