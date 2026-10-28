"""Runtime package: status machine, executor, approvals, checkpoints."""

from .approvals import ApprovalExpired, ApprovalRecord, ApprovalStore
from .checkpoint import build_checkpoint_state, context_digest, tool_fingerprint
from .executor import AttemptResult, HandlerCall, TaskExecutor, TaskTimeout
from .state import (
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    InvalidTransition,
    RunStatus,
    TaskStatus,
    ensure_transition,
)

__all__ = [
    "RUN_TRANSITIONS",
    "TASK_TRANSITIONS",
    "ApprovalExpired",
    "ApprovalRecord",
    "ApprovalStore",
    "AttemptResult",
    "HandlerCall",
    "InvalidTransition",
    "RunStatus",
    "TaskExecutor",
    "TaskStatus",
    "TaskTimeout",
    "build_checkpoint_state",
    "context_digest",
    "ensure_transition",
    "tool_fingerprint",
]