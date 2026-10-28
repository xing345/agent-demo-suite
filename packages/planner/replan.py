"""Bounded re-planning after a task failure.

The failed task and everything downstream of it is replaced; upstream work is
kept so the runtime can skip it. ``TaskPlan.replan_count`` is persisted in the
checkpoint, which makes the budget survive restarts and resume.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from .models import PlannedTask, TaskPlan
from .protocol import Planner
from .validation import validate_plan


class Replanner:
    def __init__(self, planner: Planner, *, max_replans: int = 2) -> None:
        self.planner = planner
        self.max_replans = max(0, max_replans)

    def next_plan(
        self,
        plan: TaskPlan,
        *,
        failed_task_id: str,
        error: str,
        completed_ids: Iterable[str] = (),
        known_tools: Iterable[str] | None = None,
    ) -> TaskPlan | None:
        if plan.replan_count >= self.max_replans:
            return None

        by_id = {task.task_id: task for task in plan.tasks}
        if failed_task_id not in by_id:
            raise KeyError(f"unknown task in plan: {failed_task_id}")

        completed = set(completed_ids)
        ancestors = self._ancestors(by_id, failed_task_id)
        downstream = self._descendants(by_id, failed_task_id)
        keep = [
            task
            for task in plan.tasks
            if task.task_id in ancestors or task.task_id in completed
        ]
        keep_ids = [task.task_id for task in keep]

        sub_plan = self.planner.plan(
            self._subgoal(plan, by_id, downstream, error),
        )

        attempt = plan.replan_count + 1
        entry_deps = [
            dependency
            for dependency in by_id[failed_task_id].depends_on
            if dependency in keep_ids
        ] or keep_ids[-1:]

        id_map = {
            task.task_id: f"{failed_task_id}-r{attempt}-{index}"
            for index, task in enumerate(sub_plan.tasks)
        }
        remapped: list[PlannedTask] = []
        for index, task in enumerate(sub_plan.tasks):
            dependencies = [id_map[dep] for dep in task.depends_on if dep in id_map]
            if index == 0 and not dependencies:
                dependencies = list(entry_deps)
            remapped.append(
                task.model_copy(
                    update={"task_id": id_map[task.task_id], "depends_on": dependencies}
                )
            )

        new_plan = TaskPlan(
            goal=plan.goal,
            tasks=[*keep, *remapped],
            planner_version=f"replan:{plan.planner_version}",
            replan_count=attempt,
        )
        validate_plan(new_plan, known_tools=known_tools)
        return new_plan

    def _ancestors(self, by_id: dict[str, PlannedTask], task_id: str) -> set[str]:
        found: set[str] = set()
        queue = deque(by_id[task_id].depends_on)
        while queue:
            current = queue.popleft()
            if current in found or current not in by_id:
                continue
            found.add(current)
            queue.extend(by_id[current].depends_on)
        return found

    def _descendants(self, by_id: dict[str, PlannedTask], task_id: str) -> set[str]:
        children: dict[str, list[str]] = {key: [] for key in by_id}
        for task in by_id.values():
            for dependency in task.depends_on:
                children.setdefault(dependency, []).append(task.task_id)

        found: set[str] = {task_id}
        queue = deque([task_id])
        while queue:
            current = queue.popleft()
            for child in children.get(current, []):
                if child not in found:
                    found.add(child)
                    queue.append(child)
        return found

    def _subgoal(
        self,
        plan: TaskPlan,
        by_id: dict[str, PlannedTask],
        downstream: set[str],
        error: str,
    ) -> str:
        remaining = [by_id[task_id].name for task_id in downstream if task_id in by_id]
        return (
            f"目标: {plan.goal}\n"
            f"仍需完成: {', '.join(remaining)}\n"
            f"上次失败原因: {error}\n"
            "请只规划仍需完成的部分。"
        )