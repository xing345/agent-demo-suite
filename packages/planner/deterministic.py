from __future__ import annotations

from ..tool_registry import ToolDefinition
from .models import PlannedTask, TaskPlan


class DeterministicPlanner:
    """Rule-based planner used as the offline default and as the final fallback."""

    planner_version = "deterministic/1"

    _INTENTS = (
        ("read", ("读取", "查看", "获取"), "读取并收集任务所需的信息"),
        ("analyze", ("分析", "检查", "定位"), "分析信息并定位问题或关键结论"),
        ("generate", ("生成", "输出", "建议"), "生成结构化结果或修改建议"),
        ("confirm", ("确认", "审批", "人工"), "等待人工确认后再继续执行"),
    )

    def plan(
        self,
        goal: str,
        *,
        tools: list[ToolDefinition] | None = None,
    ) -> TaskPlan:
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
        return TaskPlan(goal=goal, tasks=tasks, planner_version=self.planner_version)