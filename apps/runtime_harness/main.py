from pathlib import Path

from fastapi import FastAPI, HTTPException

from packages.event_store import (
    EventRecord,
    EventStore,
    InMemoryEventStore,
    RunRecord,
    SQLiteEventStore,
)
from packages.mcp_server import (
    MCPRemoteClient,
    MCPServer,
    SecurityPolicy,
    TokenAuthenticator,
    create_mcp_router,
)
from packages.model_gateway import OpenAICompatibleGateway
from packages.planner import (
    DeterministicPlanner,
    ModelPlanner,
    PlanValidationError,
    Replanner,
    TaskPlan,
    plan_depth,
    topological_order,
    validate_plan,
)
from packages.runtime import ApprovalExpired
from packages.shared_config import get_settings
from packages.skill_registry import SkillDefinition, SkillRegistry
from packages.tool_registry import ToolDefinition

from .engine import (
    InvalidStateTransition,
    PlanExecutionResult,
    RuntimeEngine,
    ToolCallResult,
)
from .schemas import (
    CheckpointRequest,
    CreateRunRequest,
    CreateRunResponse,
    ToolCallRequest,
)

app = FastAPI(title="Agent Runtime & Harness Demo", version="0.1.0")
settings = get_settings()


def build_store() -> EventStore:
    settings = get_settings()
    if settings.event_store_backend.lower() == "sqlite":
        database = Path(settings.event_store_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        return SQLiteEventStore(database)
    return InMemoryEventStore()


def build_model_gateway() -> OpenAICompatibleGateway | None:
    if settings.model_provider.lower() not in {"openai", "openai_compatible"}:
        return None
    if not settings.model_base_url or not settings.model_name:
        raise ValueError(
            "MODEL_BASE_URL and MODEL_NAME are required for an OpenAI-compatible provider"
        )
    return OpenAICompatibleGateway(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
    )


def build_mcp_client() -> MCPRemoteClient | None:
    if not settings.mcp_remote_url:
        return None
    return MCPRemoteClient(
        settings.mcp_remote_url,
        token=settings.mcp_remote_token,
        timeout_seconds=settings.model_timeout_seconds,
        protocol=settings.mcp_protocol,
        retries=settings.mcp_retries,
        policy=SecurityPolicy(
            allow_private=settings.mcp_allow_insecure,
            require_https=settings.mcp_require_https,
        ),
    )


store = build_store()
model_gateway = build_model_gateway()
_offline_planner = DeterministicPlanner()
planner = (
    ModelPlanner(model_gateway, fallback=_offline_planner)
    if model_gateway is not None
    else _offline_planner
)
engine = RuntimeEngine(
    store,
    model_gateway=model_gateway,
    mcp_client=build_mcp_client(),
    mcp_fallback_to_local=settings.mcp_fallback_to_local,
    replanner=Replanner(planner, max_replans=settings.max_replans),
    max_concurrency=settings.executor_concurrency,
    approval_ttl_seconds=settings.approval_ttl_seconds,
)
skills = SkillRegistry()
skills.register(
    SkillDefinition(
        name="repo_diagnosis",
        description="Diagnose a repository issue",
        prompt_template="Read {path} and summarize the issue.",
        tool_names=["read_context"],
    )
)
mcp_server = MCPServer()
mcp_server.register_tool(
    ToolDefinition(
        name="read_context",
        description="Read context through the MCP adapter",
        source="mcp",
        input_schema={"required": ["query"]},
    ),
    lambda payload: {"result": payload["query"]},
)
engine.register_tool(
    ToolDefinition(name="read_context", permission="read"),
    lambda payload: {"context": payload},
)
engine.register_tool(
    ToolDefinition(
        name="write_demo_file",
        permission="dangerous",
        requires_human_confirmation=True,
    ),
    lambda payload: {"accepted": True, "target": payload.get("path", "")},
)
mcp_router = create_mcp_router(
    mcp_server,
    authenticator=(
        TokenAuthenticator(settings.mcp_server_token)
        if settings.mcp_server_token
        else None
    ),
)
app.include_router(mcp_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs", response_model=CreateRunResponse, status_code=201)
def create_run(request: CreateRunRequest) -> CreateRunResponse:
    run = engine.start_run(request.task)
    plan = planner.plan(request.task)

    run.metadata.update(request.metadata)
    run.metadata["task"] = request.task
    run.metadata["plan"] = plan.model_dump(mode="json")
    store.update_run(run)

    store.append_event(
        EventRecord(
            run_id=run.run_id,
            event_type="plan.created",
            payload={"tasks": [task.model_dump(mode="json") for task in plan.tasks]},
        )
    )
    return CreateRunResponse(
        session_id=run.session_id,
        run_id=run.run_id,
        status=run.status,
    )


@app.get("/runs/{run_id}/events")
def list_run_events(run_id: str) -> dict[str, object]:
    try:
        engine.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"run_id": run_id, "events": engine.trace(run_id)}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    try:
        return engine.describe_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, object]:
    try:
        run = engine.cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": run.run_id,
        "status": run.status,
        "cancel_requested": bool(run.metadata.get("cancel_requested")),
    }


@app.post("/runs/{run_id}/approvals/{approval_id}/reject")
def reject_approval(
    run_id: str,
    approval_id: str,
    reason: str | None = None,
) -> dict[str, object]:
    try:
        record = engine.reject_approval(run_id, approval_id, reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "approval_id": record.approval_id,
        "status": record.status,
        "run_status": engine.get_run(run_id).status,
    }


@app.post("/runs/{run_id}/tools/{tool_name}", response_model=ToolCallResult)
def call_tool(
    run_id: str,
    tool_name: str,
    request: ToolCallRequest,
) -> ToolCallResult:
    try:
        return engine.call_tool(run_id, tool_name, request.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/approvals/{approval_id}", response_model=ToolCallResult)
def approve_tool(run_id: str, approval_id: str | None) -> ToolCallResult:
    try:
        return engine.approve(run_id, approval_id)
    except ApprovalExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/execute", response_model=PlanExecutionResult)
def execute_run(run_id: str) -> PlanExecutionResult:
    try:
        run = engine.get_run(run_id)
        plan = load_plan(run)
        return engine.execute_plan(run_id, plan)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def load_plan(run: RunRecord) -> TaskPlan:
    """Reuse the plan frozen at creation time so task ids stay stable."""
    stored = run.metadata.get("plan")
    if isinstance(stored, dict):
        return TaskPlan.model_validate(stored)
    return planner.plan(str(run.metadata.get("task", "")))


@app.get("/planner")
def plan_task(goal: str):
    try:
        return planner.plan(goal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/skills")
def list_skills():
    return skills.list()


@app.post("/plans/validate")
def validate_plan_endpoint(plan: TaskPlan) -> dict[str, object]:
    try:
        order = topological_order(plan)
        validate_plan(plan)
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    return {"valid": True, "task_order": order, "depth": plan_depth(plan)}


@app.get("/runs/{run_id}/plan")
def get_run_plan(run_id: str) -> dict[str, object]:
    try:
        run = engine.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    stored = run.metadata.get("plan")
    if not isinstance(stored, dict):
        raise HTTPException(status_code=404, detail="plan not found for run")
    return stored


@app.get("/tools", response_model=list[ToolDefinition])
def list_mcp_tools() -> list[ToolDefinition]:
    """Alias of ``/mcp/tools`` kept for local inspection."""
    return mcp_server.list_tools()


@app.post("/runs/{run_id}/checkpoints")
def save_checkpoint(run_id: str, request: CheckpointRequest):
    try:
        return engine.save_checkpoint(run_id, request.state)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/runs/{run_id}/resume")
def restore_checkpoint(run_id: str):
    try:
        return engine.resume_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.runtime_host, port=settings.runtime_port)