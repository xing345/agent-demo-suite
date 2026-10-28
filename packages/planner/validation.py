"""Structural rules a plan must satisfy before the runtime may execute it."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from .models import TaskPlan

MAX_TASKS = 20
MAX_DEPTH = 8


class PlanValidationError(ValueError):
    """A plan is structurally unsound; ``code`` is stable and machine readable."""

    def __init__(self, code: str, detail: str, task_id: str | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.task_id = task_id

    def to_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "detail": self.detail, "task_id": self.task_id}


def _children(plan: TaskPlan) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {task.task_id: [] for task in plan.tasks}
    for task in plan.tasks:
        for dependency in task.depends_on:
            children[dependency].append(task.task_id)
    return children


def _check_identity(plan: TaskPlan) -> list[str]:
    if not plan.tasks:
        raise PlanValidationError("EMPTY_PLAN", "plan must contain at least one task")

    ids = [task.task_id for task in plan.tasks]
    seen: set[str] = set()
    for task_id in ids:
        if task_id in seen:
            raise PlanValidationError(
                "DUPLICATE_TASK_ID", f"duplicate task_id: {task_id}", task_id
            )
        seen.add(task_id)

    known = set(ids)
    for task in plan.tasks:
        for dependency in task.depends_on:
            if dependency == task.task_id:
                raise PlanValidationError(
                    "CYCLE_DETECTED",
                    f"task {task.task_id} depends on itself",
                    task.task_id,
                )
            if dependency not in known:
                raise PlanValidationError(
                    "UNKNOWN_DEPENDENCY",
                    f"task {task.task_id} depends on unknown task {dependency}",
                    task.task_id,
                )
    return ids


def topological_order(plan: TaskPlan, *, max_depth: int = MAX_DEPTH) -> list[str]:
    """Return a deterministic execution order or raise ``PlanValidationError``."""
    ids = _check_identity(plan)
    children = _children(plan)
    indegree = {task.task_id: len(task.depends_on) for task in plan.tasks}

    ready = deque(task_id for task_id in ids if indegree[task_id] == 0)
    order: list[str] = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(order) != len(ids):
        placed = set(order)
        remaining = [task_id for task_id in ids if task_id not in placed]
        raise PlanValidationError(
            "CYCLE_DETECTED",
            f"dependency cycle among: {', '.join(remaining)}",
            remaining[0],
        )

    depth: dict[str, int] = {task_id: 1 for task_id in ids}
    for node in order:
        for child in children[node]:
            depth[child] = max(depth[child], depth[node] + 1)
    deepest = max(depth.values(), default=0)
    if deepest > max_depth:
        raise PlanValidationError(
            "DEPTH_EXCEEDED", f"plan depth {deepest} exceeds limit {max_depth}"
        )
    return order


def plan_depth(plan: TaskPlan) -> int:
    order = topological_order(plan)
    by_id = {task.task_id: task for task in plan.tasks}
    depth: dict[str, int] = {}
    for node in order:
        task = by_id[node]
        depth[node] = 1 + max((depth[dependency] for dependency in task.depends_on), default=0)
    return max(depth.values(), default=0)


def validate_plan(
    plan: TaskPlan,
    *,
    known_tools: Iterable[str] | None = None,
    max_tasks: int = MAX_TASKS,
    max_depth: int = MAX_DEPTH,
) -> None:
    """Validate structure, size, depth and (optionally) tool references."""
    if len(plan.tasks) > max_tasks:
        raise PlanValidationError(
            "TASK_LIMIT_EXCEEDED",
            f"plan has {len(plan.tasks)} tasks, limit is {max_tasks}",
        )

    topological_order(plan, max_depth=max_depth)

    if known_tools is not None:
        allowed = set(known_tools)
        for task in plan.tasks:
            if task.tool_name and task.tool_name not in allowed:
                raise PlanValidationError(
                    "UNKNOWN_TOOL",
                    f"task {task.task_id} references unknown tool {task.tool_name}",
                    task.task_id,
                )