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


class UploadFileRequest(BaseModel):
    """Base64 upload keeps the demo free of a multipart dependency."""

    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    media_type: str | None = None


class CreateExperimentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str = Field(min_length=1)
    rank: int = Field(default=8, ge=1, le=256)
    alpha: int = Field(default=16, ge=1, le=1024)
    learning_rate: float = Field(default=0.0002, gt=0, le=1)
    epochs: int = Field(default=1, ge=1, le=100)
    quant_bits: Literal[4, 8] | None = None