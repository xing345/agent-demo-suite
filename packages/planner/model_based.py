"""Model-backed planner with one repair retry and a deterministic fallback."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from ..model_gateway import ModelGatewayError
from ..tool_registry import ToolDefinition
from .deterministic import DeterministicPlanner
from .models import TaskPlan
from .protocol import Planner
from .validation import PlanValidationError, validate_plan


class StructuredGateway(Protocol):
    """The slice of the model gateway the planner actually needs."""

    model: str

    def generate_sync(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[TaskPlan] | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...


class ModelPlanner:
    """Ask a model for a JSON plan, validate it, fall back when it misbehaves."""

    def __init__(
        self,
        gateway: StructuredGateway,
        *,
        fallback: Planner | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.gateway = gateway
        self.fallback = fallback or DeterministicPlanner()
        self.max_attempts = max(1, max_attempts)

    @property
    def planner_version(self) -> str:
        return f"model/{getattr(self.gateway, 'model', 'unknown')}"

    def plan(
        self,
        goal: str,
        *,
        tools: list[ToolDefinition] | None = None,
    ) -> TaskPlan:
        if not goal.strip():
            raise ValueError("goal must not be empty")

        known_tools = {tool.name for tool in tools} if tools else None
        messages = self._messages(goal, tools)

        for _attempt in range(self.max_attempts):
            try:
                raw = self.gateway.generate_sync(messages, response_model=TaskPlan)
                plan = self._coerce(raw, goal)
                validate_plan(plan, known_tools=known_tools)
                return plan
            except (ModelGatewayError, ValidationError, PlanValidationError) as exc:
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            f"Your previous plan was rejected: {exc}. "
                            "Return a corrected JSON plan that satisfies the schema, "
                            "uses unique task ids and contains no dependency cycles."
                        ),
                    },
                ]

        fallback_plan = self.fallback.plan(goal, tools=tools)
        fallback_plan.planner_version = f"fallback:{fallback_plan.planner_version}"
        return fallback_plan

    def _coerce(self, raw: Any, goal: str) -> TaskPlan:
        if isinstance(raw, TaskPlan):
            plan = raw
        elif isinstance(raw, dict):
            plan = TaskPlan.model_validate(raw)
        else:
            raise ModelGatewayError("model planner returned an unsupported payload")

        plan.goal = goal
        plan.planner_version = self.planner_version
        return plan

    def _messages(
        self,
        goal: str,
        tools: list[ToolDefinition] | None,
    ) -> list[dict[str, str]]:
        tool_lines = (
            "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
            if tools
            else "(no tools available)"
        )
        system = (
            "You are an agent planner. Reply with JSON only, matching this schema: "
            '{"goal": string, "tasks": [{"task_id": string, "name": string, '
            '"description": string, "depends_on": [string], "tool_name": string|null}]}. '
            "task_id values must be unique, depends_on may only reference existing "
            "task ids, and the dependency graph must be acyclic."
        )
        user = (
            f"Goal: {goal}\n"
            f"Available tools:\n{tool_lines}\n"
            "Return at most 20 tasks."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]