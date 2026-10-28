from typing import Literal

from pydantic import BaseModel, Field


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_types: list[Literal["text", "code", "image", "audio", "video"]] = Field(min_length=1)


class DatasetResponse(BaseModel):
    dataset_id: str
    name: str
    source_types: list[str]
    status: str
