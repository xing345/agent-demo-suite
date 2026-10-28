"""Checkpoint payload: what a resumed run needs to continue safely."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..planner import TaskPlan
from ..tool_registry import ToolRegistry


def tool_fingerprint(registry: ToolRegistry) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for tool in registry.list():
        encoded = json.dumps(tool.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        fingerprints[tool.name] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
    return fingerprints


def context_digest(plan: TaskPlan) -> str:
    encoded = json.dumps(
        {"goal": plan.goal, "plan_id": plan.plan_id, "tasks": [task.task_id for task in plan.tasks]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def build_checkpoint_state(
    *,
    plan: TaskPlan,
    completed_ids: set[str],
    outputs: dict[str, dict[str, Any]],
    attempts: dict[str, int],
    next_task_id: str | None,
    error: str | None,
    model_version: str | None,
    registry: ToolRegistry,
) -> dict[str, Any]:
    return {
        "next_task_id": next_task_id,
        "completed_task_ids": sorted(completed_ids),
        "outputs": outputs,
        "attempts": attempts,
        "replan_count": plan.replan_count,
        "planner_version": plan.planner_version,
        "plan_id": plan.plan_id,
        "model_version": model_version,
        "tool_versions": tool_fingerprint(registry),
        "context_digest": context_digest(plan),
        "error": error,
    }