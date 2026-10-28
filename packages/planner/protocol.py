from __future__ import annotations

from typing import Protocol

from ..tool_registry import ToolDefinition
from .models import TaskPlan


class Planner(Protocol):
    """Planning boundary; the runtime never imports a concrete planner."""

    def plan(
        self,
        goal: str,
        *,
        tools: list[ToolDefinition] | None = None,
    ) -> TaskPlan: ...