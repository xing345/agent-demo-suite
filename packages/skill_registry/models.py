from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    prompt_template: str = ""
    tool_names: list[str] = Field(default_factory=list)
