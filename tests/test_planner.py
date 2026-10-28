from apps.runtime_harness.planner import DeterministicPlanner


def test_planner_creates_ordered_tasks_from_known_intents() -> None:
    planner = DeterministicPlanner()

    plan = planner.plan("读取代码，分析问题，生成修改建议，等待确认")

    assert [task.name for task in plan.tasks] == [
        "read",
        "analyze",
        "generate",
        "confirm",
    ]
    assert plan.tasks[1].depends_on == [plan.tasks[0].task_id]
    assert plan.tasks[3].depends_on == [plan.tasks[2].task_id]


def test_planner_keeps_short_task_as_single_task() -> None:
    plan = DeterministicPlanner().plan("查看 README")

    assert len(plan.tasks) == 1
    assert plan.tasks[0].name == "read"
