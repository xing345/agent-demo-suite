from apps.runtime_harness.main import (
    approve_tool,
    call_tool,
    create_run,
    execute_run,
    health,
    list_mcp_tools,
    list_run_events,
    list_skills,
    plan_task,
    restore_checkpoint,
    save_checkpoint,
)
from apps.runtime_harness.schemas import (
    CheckpointRequest,
    CreateRunRequest,
    ToolCallRequest,
)


def test_health() -> None:
    assert health() == {"status": "ok"}


def test_create_run_and_list_events() -> None:
    response = create_run(CreateRunRequest(task="inspect repository"))
    events = list_run_events(response.run_id)

    assert response.status == "created"
    assert events["events"][0].event_type == "run.created"


def test_api_returns_approval_for_write_tool() -> None:
    response = create_run(CreateRunRequest(task="update a file"))

    pending = call_tool(
        response.run_id,
        "write_demo_file",
        ToolCallRequest(payload={"path": "README.md"}),
    )

    assert pending.status == "awaiting_approval"
    completed = approve_tool(response.run_id, pending.approval_id)
    assert completed.status == "completed"


def test_api_exposes_plan_skills_and_mcp_tools() -> None:
    plan = plan_task("读取代码并分析问题")
    skills = list_skills()
    tools = list_mcp_tools()

    assert [task.name for task in plan.tasks] == ["read", "analyze"]
    assert skills[0].name == "repo_diagnosis"
    assert tools[0].name == "read_context"


def test_api_saves_and_restores_checkpoint() -> None:
    response = create_run(CreateRunRequest(task="continue task"))
    saved = save_checkpoint(
        response.run_id,
        CheckpointRequest(state={"next_task": "confirm"}),
    )
    restored = restore_checkpoint(response.run_id)

    assert saved.checkpoint_id == restored.checkpoint_id
    assert restored.state == {"next_task": "confirm"}


def test_api_executes_planner_tasks_through_runtime() -> None:
    response = create_run(CreateRunRequest(task="读取代码并分析问题"))

    result = execute_run(response.run_id)

    assert result.status == "completed"
    assert [task.name for task in result.tasks] == ["read", "analyze"]
