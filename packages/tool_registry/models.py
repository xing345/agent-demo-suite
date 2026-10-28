from typing import Any, Literal

from pydantic import BaseModel, Field

ToolSource = Literal["builtin", "mcp", "skill"]


class ToolDefinition(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    source: ToolSource = "builtin"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permission: Literal["read", "write", "dangerous"] = "read"
    requires_human_confirmation: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=600)
