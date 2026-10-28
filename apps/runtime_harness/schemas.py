from typing import Any

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateRunResponse(BaseModel):
    session_id: str
    run_id: str
    status: str


class ToolCallRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class CheckpointRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
