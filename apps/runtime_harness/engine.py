from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from packages.event_store import CheckpointRecord, EventRecord, InMemoryEventStore, RunRecord
from packages.mcp_server import MCPRemoteClient
from packages.model_gateway import ModelGateway
from packages.tool_registry import ToolDefinition, ToolRegistry

from .planner import TaskPlan


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
    """First vertical slice of the Runtime and Harness execution boundary."""

    def __init__(
        self,
        store: InMemoryEventStore,
        *,
        model_gateway: ModelGateway | None = None,
        mcp_client: MCPRemoteClient | None = None,
    ) -> None:
        self.store = store
        self.model_gateway = model_gateway
        self.mcp_client = mcp_client
        self.registry = ToolRegistry()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.pending: dict[str, _PendingApproval] = {}

    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.registry.register(definition)
        self.handlers[definition.name] = handler

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
        return self.store.runs[run_id]

    def trace(self, run_id: str) -> list[EventRecord]:
        return self.store.list_events(run_id)

    def save_checkpoint(self, run_id: str, state: dict[str, Any]) -> CheckpointRecord:
        self.get_run(run_id)
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
        self.get_run(run_id).status = "paused"
        return checkpoint

    def resume_run(self, run_id: str) -> CheckpointRecord:
        checkpoint = self.store.latest_checkpoint(run_id)
        if checkpoint is None:
            raise KeyError(f"checkpoint not found for run: {run_id}")
        self.get_run(run_id).status = "running"
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

    def execute_plan(self, run_id: str, plan: TaskPlan) -> PlanExecutionResult:
        self.get_run(run_id)
        completed: set[str] = set()
        outputs: dict[str, dict[str, Any]] = {}
        results: list[TaskExecutionItem] = []

        for planned_task in plan.tasks:
            missing = [dependency for dependency in planned_task.depends_on if dependency not in completed]
            if missing:
                return self._fail_plan(
                    run_id,
                    planned_task.task_id,
                    results,
                    f"task dependencies are incomplete: {', '.join(missing)}",
                    outputs,
                )

            task_record = self._find_or_create_task(run_id, planned_task)
            task_record.status = "running"
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="task.started",
                    status="running",
                    payload={"task_id": planned_task.task_id, "name": planned_task.name},
                )
            )

            try:
                output = self._execute_planned_task(plan, planned_task, outputs)
            except Exception as exc:
                task_record.status = "failed"
                return self._fail_plan(run_id, planned_task.task_id, results, str(exc), outputs)

            task_record.status = "completed"
            task_record.metadata["output"] = output
            outputs[planned_task.task_id] = output
            completed.add(planned_task.task_id)
            item = TaskExecutionItem(
                task_id=planned_task.task_id,
                name=planned_task.name,
                status="completed",
                output=output,
            )
            results.append(item)
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="task.completed",
                    status="running",
                    payload={
                        "task_id": planned_task.task_id,
                        "name": planned_task.name,
                        "output": output,
                    },
                )
            )

        run = self.get_run(run_id)
        run.status = "completed"
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="run.completed",
                status="completed",
                payload={"task_count": len(results)},
            )
        )
        return PlanExecutionResult(run_id=run_id, status="completed", tasks=results)

    def _find_or_create_task(self, run_id: str, planned_task: Any):
        for task in self.store.tasks.values():
            if task.run_id == run_id and task.name == planned_task.name:
                return task
        from packages.event_store import TaskRecord

        return self.store.create_task(
            TaskRecord(
                task_id=planned_task.task_id,
                run_id=run_id,
                name=planned_task.name,
                metadata={
                    "description": planned_task.description,
                    "depends_on": planned_task.depends_on,
                },
            )
        )

    def _execute_planned_task(
        self,
        plan: TaskPlan,
        planned_task: Any,
        outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "goal": plan.goal,
            "task_id": planned_task.task_id,
            "description": planned_task.description,
            "inputs": outputs,
        }
        if planned_task.name in self.handlers:
            return self.handlers[planned_task.name](payload)
        if self.mcp_client is not None:
            remote_tools = {tool.get("name") for tool in self.mcp_client.list_tools()}
            if planned_task.name in remote_tools:
                return self.mcp_client.call_tool(planned_task.name, payload)
        if self.model_gateway is not None:
            content = self.model_gateway.generate_sync(
                [
                    {
                        "role": "system",
                        "content": "Execute the requested task and return a concise JSON object.",
                    },
                    {
                        "role": "user",
                        "content": f"Goal: {plan.goal}\nTask: {planned_task.description}\nInputs: {outputs}",
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
        next_task_id: str,
        results: list[TaskExecutionItem],
        error: str,
        outputs: dict[str, dict[str, Any]],
    ) -> PlanExecutionResult:
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="task.failed",
                status="failed",
                payload={"task_id": next_task_id, "error": error},
                error_code="task_execution_failed",
            )
        )
        self.save_checkpoint(
            run_id,
            {"next_task_id": next_task_id, "outputs": outputs, "error": error},
        )
        results.append(
            TaskExecutionItem(
                task_id=next_task_id,
                name=next_task_id,
                status="failed",
                error=error,
            )
        )
        return PlanExecutionResult(run_id=run_id, status="paused", tasks=results)

    def call_tool(
        self,
        run_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> ToolCallResult:
        run = self.get_run(run_id)
        definition = self.registry.get(tool_name)
        if tool_name not in self.handlers:
            raise KeyError(f"handler not registered: {tool_name}")

        needs_approval = definition.requires_human_confirmation or definition.permission == "dangerous"
        if needs_approval:
            approval = _PendingApproval(
                approval_id=str(uuid4()),
                run_id=run_id,
                tool_name=tool_name,
                payload=payload,
            )
            self.pending[approval.approval_id] = approval
            run.status = "paused"
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
        approval = self.pending.pop(approval_id)
        if approval.run_id != run_id:
            raise ValueError("approval does not belong to run")

        run = self.get_run(run_id)
        run.status = "running"
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
        output = self.handlers[tool_name](payload)
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="tool.completed",
                status="running",
                payload={"tool_name": tool_name, "output": output},
            )
        )
        run = self.get_run(run_id)
        run.status = "completed"
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="run.completed",
                status="completed",
                payload={"tool_name": tool_name},
            )
        )
        return ToolCallResult(status="completed", output=output)
