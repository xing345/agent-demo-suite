"""Execution boundary between planner, tools, model, approvals and the store.

The engine is a thin orchestrator: status legality lives in
``packages.runtime.state``, timeouts/retries in ``packages.runtime.executor``,
approvals in ``packages.runtime.approvals`` and checkpoint payloads in
``packages.runtime.checkpoint``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal

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
from packages.planner import PlannedTask, TaskPlan, topological_order
from packages.runtime.approvals import ApprovalRecord, ApprovalStore
from packages.runtime.checkpoint import build_checkpoint_state
from packages.runtime.executor import AttemptResult, HandlerCall, TaskExecutor
from packages.runtime.state import (
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    InvalidTransition,
    ensure_transition,
)
from packages.tool_registry import ToolDefinition, ToolRegistry

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# Kept as an alias so existing imports keep working.
InvalidStateTransition = InvalidTransition

DEFAULT_TOOL_TIMEOUT_SECONDS = 30.0


class ToolCallResult(BaseModel):
    status: Literal["awaiting_approval", "completed"]
    approval_id: str | None = None
    output: dict[str, Any] | None = None


class TaskExecutionItem(BaseModel):
    task_id: str
    name: str
    status: Literal["completed", "failed", "paused", "cancelled"]
    output: dict[str, Any] | None = None
    error: str | None = None


class PlanExecutionResult(BaseModel):
    run_id: str
    status: Literal["completed", "failed", "paused", "cancelled"]
    tasks: list[TaskExecutionItem]


class RuntimeEngine:
    def __init__(
        self,
        store: EventStore,
        *,
        model_gateway: ModelGateway | None = None,
        mcp_client: MCPRemoteClient | None = None,
        mcp_fallback_to_local: bool = False,
        replanner: Any | None = None,
        max_concurrency: int = 1,
        approval_ttl_seconds: int = 900,
        clock_now: Callable[[], Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        executor: TaskExecutor | None = None,
    ) -> None:
        self.store = store
        self.model_gateway = model_gateway
        self.mcp_client = mcp_client
        self.mcp_fallback_to_local = mcp_fallback_to_local
        self.replanner = replanner
        self.registry = ToolRegistry()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.executor = executor or TaskExecutor(
            max_concurrency=max_concurrency, sleeper=sleeper
        )
        self.approvals = ApprovalStore(
            store, clock_now=clock_now, ttl_seconds=approval_ttl_seconds
        )
        self._lock = threading.RLock()

    def close(self) -> None:
        self.executor.close()

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

    def describe_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        tasks = self.store.list_tasks(run_id)
        return {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
            "metadata": run.metadata,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "name": task.name,
                    "status": task.status,
                    "error": task.metadata.get("error"),
                }
                for task in tasks
            ],
        }

    def _set_run_status(self, run: RunRecord, status: str) -> RunRecord:
        ensure_transition(
            run.status,
            status,
            transitions=RUN_TRANSITIONS,
            entity="run",
            entity_id=run.run_id,
        )
        run.status = status  # type: ignore[assignment]
        return self.store.update_run(run)

    def _set_task_status(self, task: TaskRecord, status: str) -> TaskRecord:
        ensure_transition(
            task.status,
            status,
            transitions=TASK_TRANSITIONS,
            entity="task",
            entity_id=task.task_id,
        )
        task.status = status  # type: ignore[assignment]
        return self.store.update_task(task)

    # -------------------------------------------------------------- cancel
    def cancel_run(self, run_id: str) -> RunRecord:
        with self._lock:
            run = self.get_run(run_id)
            if run.status in TERMINAL_STATUSES:
                raise InvalidTransition(
                    f"run {run_id} is already {run.status} and cannot be cancelled"
                )
            run.metadata["cancel_requested"] = True
            self.store.update_run(run)
            self.store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_type="run.cancel_requested",
                    status=run.status,
                    payload={"status": run.status},
                )
            )
            if run.status != "running":
                self._set_run_status(run, "cancelled")
                self.store.append_event(
                    EventRecord(
                        run_id=run_id,
                        event_type="run.cancelled",
                        status="cancelled",
                        payload={"immediate": True},
                    )
                )
            return run

    def _cancel_requested(self, run: RunRecord) -> bool:
        return bool(run.metadata.get("cancel_requested"))

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
            raise InvalidTransition(
                f"run {run_id} is already {run.status} and cannot be executed again"
            )

        # Reject illegal plans before touching run state.
        ordered = topological_order(plan)
        by_id = {task.task_id: task for task in plan.tasks}

        if run.status in {"created", "queued"}:
            self._set_run_status(run, "running")

        prior = {task.task_id: task for task in self.store.list_tasks(run_id)}
        completed = {task_id for task_id, task in prior.items() if task.status == "completed"}
        outputs = {
            task_id: prior[task_id].metadata.get("output", {}) for task_id in completed
        }
        attempts = {
            task_id: int(task.metadata.get("attempts", 0))
            for task_id, task in prior.items()
        }
        remaining = [task_id for task_id in ordered if task_id not in completed]
        results: list[TaskExecutionItem] = []
        remote_tools = self._discover_remote_tools()

        while remaining:
            run = self.get_run(run_id)
            if self._cancel_requested(run):
                return self._finish_cancelled(run, plan, remaining, results, outputs, completed)
            ready = [
                task_id
                for task_id in remaining
                if all(dep in completed for dep in by_id[task_id].depends_on)
            ]
            if not ready:
                return self._fail(
                    run_id,
                    plan,
                    by_id[remaining[0]],
                    results,
                    "dependency deadlock: no task is ready",
                    outputs,
                    completed,
                    attempts,
                )

            batch = ready[: self.executor.max_concurrency]
            calls = [
                self._build_call(run_id, plan, by_id[task_id], outputs, remote_tools)
                for task_id in batch
            ]
            outcomes = self.executor.run_batch(calls)

            failure: tuple[PlannedTask, AttemptResult] | None = None
            for planned, outcome in zip(
                [by_id[task_id] for task_id in batch], outcomes, strict=False
            ):
                task = self.store.get_task(planned.task_id)
                attempts[planned.task_id] = attempts.get(planned.task_id, 0) + outcome.attempts
                task.metadata["attempts"] = attempts[planned.task_id]
                if outcome.ok:
                    task.metadata["output"] = outcome.output
                    self._set_task_status(task, "completed")
                    outputs[planned.task_id] = outcome.output or {}
                    completed.add(planned.task_id)
                    remaining.remove(planned.task_id)
                    results.append(
                        TaskExecutionItem(
                            task_id=planned.task_id,
                            name=planned.name,
                            status="completed",
                            output=outcome.output,
                        )
                    )
                    self.store.append_event(
                        EventRecord(
                            run_id=run_id,
                            event_type="task.completed",
                            status="completed",
                            latency_ms=outcome.latency_ms,
                            payload={
                                "task_id": planned.task_id,
                                "name": planned.name,
                                "output": outcome.output,
                                "attempts": attempts[planned.task_id],
                            },
                        )
                    )
                else:
                    task.metadata["error"] = outcome.error
                    task.metadata["error_type"] = outcome.error_type
                    self._set_task_status(task, "failed")
                    self.store.append_event(
                        EventRecord(
                            run_id=run_id,
                            event_type="task.failed",
                            status="failed",
                            latency_ms=outcome.latency_ms,
                            payload={
                                "task_id": planned.task_id,
                                "name": planned.name,
                                "error": outcome.error,
                                "error_type": outcome.error_type,
                                "attempts": attempts[planned.task_id],
                            },
                            error_code=outcome.error_type or "task_execution_failed",
                        )
                    )
                    if failure is None:
                        failure = (planned, outcome)

            if failure is not None:
                return self._handle_failure(
                    run_id, plan, failure[0], failure[1], results, outputs, completed, attempts
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

    def _build_call(
        self,
        run_id: str,
        plan: TaskPlan,
        planned: PlannedTask,
        outputs: dict[str, dict[str, Any]],
        remote_tools: set[str],
    ) -> HandlerCall:
        task = self._ensure_task(run_id, planned)
        if task.status == "failed":
            self._set_task_status(task, "queued")
        self._set_task_status(task, "running")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="task.started",
                status="running",
                payload={
                    "task_id": planned.task_id,
                    "name": planned.name,
                    "attempt": int(task.metadata.get("attempts", 0)) + 1,
                },
            )
        )
        payload = {
            "goal": plan.goal,
            "task_id": planned.task_id,
            "description": planned.description,
            "inputs": outputs,
        }
        return HandlerCall(
            task_id=planned.task_id,
            handler=self._resolve_handler(run_id, planned, remote_tools),
            payload=payload,
            timeout_seconds=float(
                planned.timeout_seconds or self._tool_timeout(planned)
            ),
            max_retries=planned.max_retries,
        )

    def _tool_timeout(self, planned: PlannedTask) -> float:
        name = planned.tool_name or planned.name
        try:
            return float(self.registry.get(name).timeout_seconds)
        except KeyError:
            return DEFAULT_TOOL_TIMEOUT_SECONDS

    def _resolve_handler(
        self,
        run_id: str,
        planned: PlannedTask,
        remote_tools: set[str],
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        local = self.handlers.get(planned.tool_name or planned.name)

        if self.mcp_client is not None and planned.name in remote_tools:
            client = self.mcp_client

            def call_remote(payload: dict[str, Any]) -> dict[str, Any]:
                try:
                    return client.call_tool(planned.name, payload)
                except RemoteMCPError as exc:
                    if not (self.mcp_fallback_to_local and local is not None):
                        raise
                    self.store.append_event(
                        EventRecord(
                            run_id=run_id,
                            event_type="mcp.fallback",
                            status="running",
                            payload={"tool_name": planned.name, "reason": str(exc)},
                        )
                    )
                    return local(payload)

            return call_remote

        if local is not None:
            return local

        if self.model_gateway is not None:
            gateway = self.model_gateway

            def call_model(payload: dict[str, Any]) -> dict[str, Any]:
                content = gateway.generate_sync(  # type: ignore[attr-defined]
                    [
                        {
                            "role": "system",
                            "content": "Execute the requested task and return a concise JSON object.",
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Goal: {payload['goal']}\n"
                                f"Task: {payload['description']}\n"
                                f"Inputs: {payload['inputs']}"
                            ),
                        },
                    ]
                )
                return {"content": content}

            return call_model

        def fallback(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "mode": "deterministic_fallback",
                "task": planned.name,
                "description": planned.description,
            }

        return fallback

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

    def _model_version(self) -> str | None:
        return getattr(self.model_gateway, "model", None) if self.model_gateway else None

    # ------------------------------------------------------------- outcomes
    def _handle_failure(
        self,
        run_id: str,
        plan: TaskPlan,
        planned: PlannedTask,
        outcome: AttemptResult,
        results: list[TaskExecutionItem],
        outputs: dict[str, dict[str, Any]],
        completed: set[str],
        attempts: dict[str, int],
    ) -> PlanExecutionResult:
        results.append(
            TaskExecutionItem(
                task_id=planned.task_id,
                name=planned.name,
                status="failed",
                error=outcome.error,
            )
        )
        self.save_checkpoint(
            run_id,
            build_checkpoint_state(
                plan=plan,
                completed_ids=completed,
                outputs=outputs,
                attempts=attempts,
                next_task_id=planned.task_id,
                error=outcome.error,
                model_version=self._model_version(),
                registry=self.registry,
            ),
        )

        new_plan: TaskPlan | None = None
        if self.replanner is not None:
            new_plan = self.replanner.next_plan(
                plan,
                failed_task_id=planned.task_id,
                error=outcome.error or "task failed",
                completed_ids=completed,
            )
        if new_plan is None:
            return PlanExecutionResult(run_id=run_id, status="paused", tasks=results)

        run = self.get_run(run_id)
        run.metadata["plan"] = new_plan.model_dump(mode="json")
        self.store.update_run(run)
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="plan.replanned",
                status="paused",
                payload={
                    "from_plan_id": plan.plan_id,
                    "to_plan_id": new_plan.plan_id,
                    "replan_count": new_plan.replan_count,
                    "failed_task_id": planned.task_id,
                },
            )
        )

        # The checkpoint paused the run; resume it before continuing.
        self._set_run_status(run, "running")
        continuation = self.execute_plan(run_id, new_plan)
        results.extend(continuation.tasks)
        return PlanExecutionResult(
            run_id=run_id, status=continuation.status, tasks=results
        )

    def _fail(
        self,
        run_id: str,
        plan: TaskPlan,
        planned: PlannedTask,
        results: list[TaskExecutionItem],
        error: str,
        outputs: dict[str, dict[str, Any]],
        completed: set[str],
        attempts: dict[str, int],
    ) -> PlanExecutionResult:
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="task.failed",
                status="failed",
                payload={
                    "task_id": planned.task_id,
                    "name": planned.name,
                    "error": error,
                },
                error_code="plan_deadlock",
            )
        )
        self.save_checkpoint(
            run_id,
            build_checkpoint_state(
                plan=plan,
                completed_ids=completed,
                outputs=outputs,
                attempts=attempts,
                next_task_id=planned.task_id,
                error=error,
                model_version=self._model_version(),
                registry=self.registry,
            ),
        )
        results.append(
            TaskExecutionItem(
                task_id=planned.task_id,
                name=planned.name,
                status="failed",
                error=error,
            )
        )
        return PlanExecutionResult(run_id=run_id, status="paused", tasks=results)

    def _finish_cancelled(
        self,
        run: RunRecord,
        plan: TaskPlan,
        remaining: list[str],
        results: list[TaskExecutionItem],
        outputs: dict[str, dict[str, Any]],
        completed: set[str],
    ) -> PlanExecutionResult:
        cancellable = {"created", "queued", "running", "paused", "waiting_approval"}
        for task_id in remaining:
            try:
                task = self.store.get_task(task_id)
            except KeyError:
                continue
            if task.status not in cancellable:
                continue
            self._set_task_status(task, "cancelled")
            self.store.append_event(
                EventRecord(
                    run_id=run.run_id,
                    event_type="task.cancelled",
                    status="cancelled",
                    payload={"task_id": task_id, "name": task.name},
                )
            )
            results.append(
                TaskExecutionItem(task_id=task_id, name=task.name, status="cancelled")
            )

        self._set_run_status(run, "cancelled")
        self.store.append_event(
            EventRecord(
                run_id=run.run_id,
                event_type="run.cancelled",
                status="cancelled",
                payload={"remaining_tasks": len(remaining)},
            )
        )
        self.store.save_checkpoint(
            CheckpointRecord(
                run_id=run.run_id,
                state=build_checkpoint_state(
                    plan=plan,
                    completed_ids=completed,
                    outputs=outputs,
                    attempts={},
                    next_task_id=remaining[0] if remaining else None,
                    error="cancelled",
                    model_version=self._model_version(),
                    registry=self.registry,
                ),
            )
        )
        return PlanExecutionResult(run_id=run.run_id, status="cancelled", tasks=results)

    # ------------------------------------------------------------------ tools
    def call_tool(
        self,
        run_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> ToolCallResult:
        run = self.get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            raise InvalidTransition(
                f"run {run_id} is already {run.status} and cannot call tools"
            )
        definition = self.registry.get(tool_name)
        if tool_name not in self.handlers:
            raise KeyError(f"handler not registered: {tool_name}")

        needs_approval = (
            definition.requires_human_confirmation or definition.permission == "dangerous"
        )
        if needs_approval:
            record = self.approvals.request(run_id, tool_name, payload)
            self._set_run_status(run, "waiting_approval")
            return ToolCallResult(
                status="awaiting_approval",
                approval_id=record.approval_id,
            )

        return self._execute(run_id, tool_name, payload)

    def approve(self, run_id: str, approval_id: str | None) -> ToolCallResult:
        if not approval_id:
            raise KeyError("approval not found")
        record: ApprovalRecord = self.approvals.grant(run_id, approval_id)
        run = self.get_run(run_id)
        self._set_run_status(run, "running")
        return self._execute(run_id, record.tool_name, record.payload)

    def reject_approval(
        self,
        run_id: str,
        approval_id: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = self.approvals.reject(run_id, approval_id, reason)
        run = self.get_run(run_id)
        self._set_run_status(run, "failed")
        self.store.append_event(
            EventRecord(
                run_id=run_id,
                event_type="run.failed",
                status="failed",
                payload={"reason": "approval_rejected", "approval_id": approval_id},
                error_code="approval_rejected",
            )
        )
        return record

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


__all__ = [
    "InvalidStateTransition",
    "InvalidTransition",
    "PlanExecutionResult",
    "RuntimeEngine",
    "TaskExecutionItem",
    "ToolCallResult",
]