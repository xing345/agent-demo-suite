from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field


class PlannedTask(BaseModel):
    """A single unit of work inside a plan.

    ``tool_name`` is optional: the deterministic planner leaves it empty and the
    runtime falls back to name matching, while a model planner may pin a tool.
    """

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1)
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    max_retries: int = Field(default=0, ge=0, le=5)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class TaskPlan(BaseModel):
    goal: str
    tasks: list[PlannedTask]
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    planner_version: str = "unknown"
    replan_count: int = Field(default=0, ge=0, le=10)