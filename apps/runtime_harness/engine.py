from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from packages.event_store import (
    CheckpointRecord,
    EventRecord,
    EventStore,
    RunRecord,
    TaskRecord,
)
from packages.mcp_server import MCPRemoteClient, RemoteMCPError
from packages.model_gateway import ModelGateway
from packages.tool_registry import ToolDefinition, ToolRegistry

from .planner import PlannedTask, TaskPlan

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

RUN_TRANSITIONS: dict[str, set[str]] = {
    "created": {"queued", "running", "paused", "failed", "cancelled"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "paused", "cancelled"},
    "paused": {"running", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

TASK_TRANSITIONS: dict[str, set[str]] = {
    "created": {"queued", "running", "cancelled", "failed"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled", "paused"},
    "paused": {"running", "failed", "cancelled"},
    "completed": set(),
    "failed": {"running"},
    "cancelled": set(),
}


class InvalidStateTransition(RuntimeError):
    """Raised when a run or task is asked to move to an illegal status."""


class ToolCallResult(BaseModel):
    status: Literal["awaiting_approval", "completed"]
    approval_id: str | None = None
    output: dict[str, Any] | None = None


class TaskExecutionItem(BaseModel):
    task_id: str
    name: str
    status: Literal["completed", "failed", "paused"]
    output: dict[str, Any] | None = None
    error: str | None = None


class PlanExecutionResult(BaseModel):
    run_id: str
    status: Literal["completed", "failed", "paused"]
    tasks: list[TaskExecutionItem]


class _PendingApproval(BaseModel):
    approval_id: str
    run_id: str
    tool_name: str
    payload: dict[str, Any]


class RuntimeEngine:
    """Execution boundary between the planner, tools, model and the event store."""

    def __init__(
        self,
        store: EventStore,
        *,
        model_gateway: ModelGateway | None = None,
        mcp_client: MCPRemoteClient | None = None,
        mcp_fallback_to_local: bool = False,
    ) -> None:
        self.store = store
        self.model_gateway = model_gateway
        self.mcp_client = mcp_client
        self.mcp_fallback_to_local = mcp_fallback_to_local
        self.registry = ToolRegistry()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.pending: dict[str, _PendingApproval] = {}

    # ------------------------------------------------------------------ tools
    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.registry.register(definition)
        self.handlers[definition.name] = handler

    # ------------------------------------------------------------------- runs
    def start_run(self, task: str) -> RunRecord:
        session = self.store.create_session()
        run = self.store.create_run(
            RunRecord(session_id=session.session_id, metadata={"task": task})
        )
        self.store.append_event(
            EventRecord(
                run_id=run.run_id,
                event_type="run.created",
                payload={"task": task},
            )
        )
        return run

    def get_run(self, run_id: str) -> RunRecord:
        return self.store.get_run(run_id)

    def trace(self, run_id: str) -> list[EventRecord]:
        return self.store.list_events(run_id)

    def _set_run_status(self, run: RunRecord, status: str) -> RunRecord:
        if status != run.status:
            allowed = RUN_TRANSITIONS.get(run.status, set())
            if status not in allowed:
                raise InvalidStateTransition(
                    f"run {run.run_id}: illegal transition {run.status} -> {status}"
                )
            run.status = status  # type: ignore[assignment]
        return self.store.update_run(run)

    def _set_task_status(self, task: TaskRecord, status: str) -> TaskRecord:
        if status != task.status:
            allowed = TASK_TRANSITIONS.get(task.status, set())
            if status not in allowed:
                raise InvalidStateTransition(
                    f"task {task.task_id}: illegal transition {task.status} -> {status}"
                )
            task.status = status  # type: ignore[assignment]
        return self.store.update_task(task)

    # ------------------------------------------------------------ checkpoints
    def save_checkpoint(self, run_id: str, state: dict[str, Any]) -> CheckpointRecord:
        run = self.get_run(run_id)
        checkpoint = CheckpointRecord(run_id=run_id, state=state)
        self.store.save_checkpoint(checkpoint)
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="checkpoint.saved",
                status="paused",
                payload={"checkpoint_id": checkpoint.checkpoint_id},
            )
        )
        self._set_run_status(run, "paused")
        return checkpoint

    def resume_run(self, run_id: str) -> CheckpointRecord:
        checkpoint = self.store.latest_checkpoint(run_id)
        if checkpoint is None:
            raise KeyError(f"checkpoint not found for run: {run_id}")
        run = self.get_run(run_id)
        self._set_run_status(run, "running")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="checkpoint.restored",
                status="running",
                payload={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "state": checkpoint.state,
                },
            )
        )
        return checkpoint

    # --------------------------------------------------------------- planning
    def execute_plan(self, run_id: str, plan: TaskPlan) -> PlanExecutionResult:
        run = self.get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            raise InvalidStateTransition(
                f"run {run_id} is already {run.status} and cannot be executed again"
            )
        if run.status in {"created", "queued"}:
            self._set_run_status(run, "running")

        remote_tools = self._discover_remote_tools()
        # Tasks finished by an earlier (interrupted) execution are reused, so a
        # resumed run only executes what is still outstanding.
        prior_tasks = {task.task_id: task for task in self.store.list_tasks(run_id)}
        completed: set[str] = set()
        outputs: dict[str, dict[str, Any]] = {}
        results: list[TaskExecutionItem] = []
        for prior in prior_tasks.values():
            if prior.status == "completed":
                completed.add(prior.task_id)
                outputs[prior.task_id] = prior.metadata.get("output", {})

        for planned_task in plan.tasks:
            missing = [
                dependency
                for dependency in planned_task.depends_on
                if dependency not in completed
            ]
            if missing:
                return self._fail_plan(
                    run_id,
                    planned_task,
                    results,
                    f"task dependencies are incomplete: {', '.join(missing)}",
                    outputs,
                )

            task_record = self._ensure_task(run_id, planned_task)
            already_done = prior_tasks.get(planned_task.task_id)
            if already_done is not None and already_done.status == "completed":
                continue

            self._set_task_status(task_record, "running")
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="task.started",
                    status="running",
                    payload={
                        "task_id": planned_task.task_id,
                        "name": planned_task.name,
                    },
                )
            )

            started_at = perf_counter()
            try:
                output = self._execute_planned_task(
                    run_id, plan, planned_task, outputs, remote_tools
                )
            except Exception as exc:  # noqa: BLE001 - failure is recorded, then raised to caller
                self._set_task_status(task_record, "failed")
                return self._fail_plan(
                    run_id, planned_task, results, str(exc), outputs
                )
            elapsed_ms = int((perf_counter() - started_at) * 1000)

            task_record.metadata["output"] = output
            self._set_task_status(task_record, "completed")
            outputs[planned_task.task_id] = output
            completed.add(planned_task.task_id)
            results.append(
                TaskExecutionItem(
                    task_id=planned_task.task_id,
                    name=planned_task.name,
                    status="completed",
                    output=output,
                )
            )
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="task.completed",
                    status="completed",
                    latency_ms=elapsed_ms,
                    payload={
                        "task_id": planned_task.task_id,
                        "name": planned_task.name,
                        "output": output,
                    },
                )
            )

        run = self.get_run(run_id)
        self._set_run_status(run, "completed")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="run.completed",
                status="completed",
                payload={"task_count": len(results)},
            )
        )
        return PlanExecutionResult(run_id=run_id, status="completed", tasks=results)

    def _ensure_task(self, run_id: str, planned_task: PlannedTask) -> TaskRecord:
        try:
            return self.store.get_task(planned_task.task_id)
        except KeyError:
            return self.store.create_task(
                TaskRecord(
                    task_id=planned_task.task_id,
                    run_id=run_id,
                    name=planned_task.name,
                    metadata={
                        "description": planned_task.description,
                        "depends_on": list(planned_task.depends_on),
                    },
                )
            )

    def _discover_remote_tools(self) -> set[str]:
        if self.mcp_client is None:
            return set()
        try:
            return {str(tool.get("name")) for tool in self.mcp_client.list_tools()}
        except RemoteMCPError:
            return set()

    def _execute_planned_task(
        self,
        run_id: str,
        plan: TaskPlan,
        planned_task: PlannedTask,
        outputs: dict[str, dict[str, Any]],
        remote_tools: set[str],
    ) -> dict[str, Any]:
        payload = {
            "goal": plan.goal,
            "task_id": planned_task.task_id,
            "description": planned_task.description,
            "inputs": outputs,
        }
        has_local = planned_task.name in self.handlers

        if self.mcp_client is not None and planned_task.name in remote_tools:
            try:
                return self.mcp_client.call_tool(planned_task.name, payload)
            except RemoteMCPError as exc:
                if not (self.mcp_fallback_to_local and has_local):
                    raise
                self.store.append_event(
                    EventRecord(
                        run_id=run_id,
                        event_type="mcp.fallback",
                        status="running",
                        payload={
                            "tool_name": planned_task.name,
                            "reason": str(exc),
                        },
                    )
                )

        if has_local:
            return self.handlers[planned_task.name](payload)

        if self.model_gateway is not None:
            content = self.model_gateway.generate_sync(  # type: ignore[attr-defined]
                [
                    {
                        "role": "system",
                        "content": "Execute the requested task and return a concise JSON object.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Goal: {plan.goal}\n"
                            f"Task: {planned_task.description}\n"
                            f"Inputs: {outputs}"
                        ),
                    },
                ]
            )
            return {"content": content}

        return {
            "mode": "deterministic_fallback",
            "task": planned_task.name,
            "description": planned_task.description,
        }

    def _fail_plan(
        self,
        run_id: str,
        planned_task: PlannedTask,
        results: list[TaskExecutionItem],
        error: str,
        outputs: dict[str, dict[str, Any]],
    ) -> PlanExecutionResult:
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="task.failed",
                status="failed",
                payload={
                    "task_id": planned_task.task_id,
                    "name": planned_task.name,
                    "error": error,
                },
                error_code="task_execution_failed",
            )
        )
        self.save_checkpoint(
            run_id,
            {
                "next_task_id": planned_task.task_id,
                "outputs": outputs,
                "error": error,
            },
        )
        results.append(
            TaskExecutionItem(
                task_id=planned_task.task_id,
                name=planned_task.name,
                status="failed",
                error=error,
            )
        )
        return PlanExecutionResult(run_id=run_id, status="paused", tasks=results)

    # ------------------------------------------------------------------ tools
    def call_tool(
        self,
        run_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> ToolCallResult:
        run = self.get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            raise InvalidStateTransition(
                f"run {run_id} is already {run.status} and cannot call tools"
            )
        definition = self.registry.get(tool_name)
        if tool_name not in self.handlers:
            raise KeyError(f"handler not registered: {tool_name}")

        needs_approval = (
            definition.requires_human_confirmation or definition.permission == "dangerous"
        )
        if needs_approval:
            approval = _PendingApproval(
                approval_id=str(uuid4()),
                run_id=run_id,
                tool_name=tool_name,
                payload=payload,
            )
            self.pending[approval.approval_id] = approval
            self._set_run_status(run, "paused")
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="approval.requested",
                    status="paused",
                    payload={
                        "approval_id": approval.approval_id,
                        "tool_name": tool_name,
                        "payload": payload,
                    },
                )
            )
            return ToolCallResult(
                status="awaiting_approval",
                approval_id=approval.approval_id,
            )

        return self._execute(run_id, tool_name, payload)

    def approve(self, run_id: str, approval_id: str | None) -> ToolCallResult:
        if not approval_id or approval_id not in self.pending:
            raise KeyError("approval not found")
        approval = self.pending[approval_id]
        if approval.run_id != run_id:
            # Keep the approval: a caller must not be able to destroy it by
            # sending the wrong run id.
            raise ValueError("approval does not belong to run")
        self.pending.pop(approval_id)

        run = self.get_run(run_id)
        self._set_run_status(run, "running")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="approval.granted",
                status="running",
                payload={"approval_id": approval_id},
            )
        )
        return self._execute(run_id, approval.tool_name, approval.payload)

    def _execute(
        self,
        run_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> ToolCallResult:
        run = self.get_run(run_id)
        if run.status != "running":
            self._set_run_status(run, "running")

        started_at = perf_counter()
        output = self.handlers[tool_name](payload)
        elapsed_ms = int((perf_counter() - started_at) * 1000)

        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="tool.completed",
                status="running",
                latency_ms=elapsed_ms,
                payload={"tool_name": tool_name, "output": output},
            )
        )
        self._set_run_status(run, "completed")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="run.completed",
                status="completed",
                payload={"tool_name": tool_name},
            )
        )
        return ToolCallResult(status="completed", output=output)