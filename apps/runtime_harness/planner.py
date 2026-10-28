from uuid import uuid4

from pydantic import BaseModel, Field


class PlannedTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    goal: str
    tasks: list[PlannedTask]


class DeterministicPlanner:
    """Rule-based planner used until a real model provider is configured."""

    _INTENTS = (
        ("read", ("读取", "查看", "获取"), "读取并收集任务所需的信息"),
        ("analyze", ("分析", "检查", "定位"), "分析信息并定位问题或关键结论"),
        ("generate", ("生成", "输出", "建议"), "生成结构化结果或修改建议"),
        ("confirm", ("确认", "审批", "人工"), "等待人工确认后再继续执行"),
    )

    def plan(self, goal: str) -> TaskPlan:
        if not goal.strip():
            raise ValueError("goal must not be empty")

        tasks: list[PlannedTask] = []
        for name, keywords, description in self._INTENTS:
            if any(keyword in goal for keyword in keywords):
                depends_on = [tasks[-1].task_id] if tasks else []
                tasks.append(
                    PlannedTask(
                        name=name,
                        description=description,
                        depends_on=depends_on,
                    )
                )

        if not tasks:
            tasks.append(
                PlannedTask(
                    name="execute",
                    description="执行用户提出的单一任务",
                )
            )
        return TaskPlan(goal=goal, tasks=tasks)
