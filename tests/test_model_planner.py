"""ModelPlanner: structured JSON, one repair retry, deterministic fallback."""

from typing import Any

from packages.model_gateway import ModelGatewayError
from packages.planner import DeterministicPlanner, ModelPlanner, TaskPlan


class FakeGateway:
    """Smallest possible stand-in for the OpenAI-compatible gateway."""

    model = "fake-model"

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def generate_sync(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[TaskPlan] | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(messages)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if response_model is not None:
            return response_model.model_validate(item)
        return item


VALID_PLAN = {
    "goal": "demo",
    "tasks": [
        {"task_id": "t1", "name": "read", "description": "read"},
        {"task_id": "t2", "name": "analyze", "description": "analyze", "depends_on": ["t1"]},
    ],
}


def test_model_planner_returns_validated_plan() -> None:
    gateway = FakeGateway([VALID_PLAN])
    planner = ModelPlanner(gateway, fallback=DeterministicPlanner())

    plan = planner.plan("read then analyze")

    assert [task.task_id for task in plan.tasks] == ["t1", "t2"]
    assert plan.planner_version == "model/fake-model"
    assert plan.goal == "read then analyze"
    assert len(gateway.calls) == 1


def test_model_planner_repairs_once_before_succeeding() -> None:
    gateway = FakeGateway([ModelGatewayError("invalid json"), VALID_PLAN])
    planner = ModelPlanner(gateway, fallback=DeterministicPlanner(), max_attempts=2)

    plan = planner.plan("read then analyze")

    assert len(gateway.calls) == 2
    assert plan.planner_version == "model/fake-model"
    repair_hint = gateway.calls[1][-1]["content"].lower()
    assert "rejected" in repair_hint or "invalid" in repair_hint


def test_model_planner_falls_back_after_exhausting_attempts() -> None:
    gateway = FakeGateway([ModelGatewayError("boom"), ModelGatewayError("boom again")])
    planner = ModelPlanner(gateway, fallback=DeterministicPlanner(), max_attempts=2)

    plan = planner.plan("读取代码并分析问题")

    assert len(gateway.calls) == 2
    assert plan.planner_version.startswith("fallback:deterministic")
    assert [task.name for task in plan.tasks] == ["read", "analyze"]


def test_model_planner_falls_back_when_plan_is_illegal() -> None:
    illegal = {
        "goal": "cycle",
        "tasks": [
            {"task_id": "a", "name": "a", "depends_on": ["b"]},
            {"task_id": "b", "name": "b", "depends_on": ["a"]},
        ],
    }
    gateway = FakeGateway([illegal, illegal])
    planner = ModelPlanner(gateway, fallback=DeterministicPlanner(), max_attempts=2)

    plan = planner.plan("loop forever")

    assert plan.planner_version.startswith("fallback:deterministic")
    assert plan.tasks[0].name == "execute"


def test_model_planner_rejects_empty_goal() -> None:
    import pytest

    planner = ModelPlanner(FakeGateway([VALID_PLAN]), fallback=DeterministicPlanner())

    with pytest.raises(ValueError, match="goal"):
        planner.plan("   ")


def test_model_planner_passes_known_tools_to_the_prompt() -> None:
    from packages.tool_registry import ToolDefinition

    gateway = FakeGateway([VALID_PLAN])
    planner = ModelPlanner(gateway, fallback=DeterministicPlanner())

    planner.plan("read then analyze", tools=[ToolDefinition(name="read_context")])

    prompt = gateway.calls[0][-1]["content"]
    assert "read_context" in prompt