"""LoRA / QLoRA configuration and runner contracts.

No runner ships with real training here: without a GPU the honest answer is
``RunnerStatus(available=False)``, and no metrics are invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .adapters import DependencyMissing


class LoRAConfig(BaseModel):
    rank: int = Field(ge=1, le=256)
    alpha: int = Field(ge=1, le=1024)
    dropout: float = Field(default=0.0, ge=0.0, le=1.0)
    learning_rate: float = Field(gt=0.0, le=1.0)
    epochs: int = Field(ge=1, le=100)
    batch_size: int = Field(default=1, ge=1, le=1024)
    target_modules: list[str] = Field(default_factory=lambda: ["q_proj", "v_proj"])


class QLoRAConfig(LoRAConfig):
    quant_bits: Literal[4, 8] = 4


@dataclass(frozen=True)
class RunnerStatus:
    available: bool
    reason: str | None = None
    device: str | None = None


class LoRARunner(Protocol):
    def probe(self) -> RunnerStatus: ...

    def train(self, config: LoRAConfig, dataset_ref: str) -> dict[str, float]: ...


class UnavailableRunner:
    """Default runner: reports the truth instead of fabricating metrics."""

    def __init__(self, reason: str = "no_cuda") -> None:
        self.reason = reason

    def probe(self) -> RunnerStatus:
        return RunnerStatus(available=False, reason=self.reason, device=None)

    def train(self, config: LoRAConfig, dataset_ref: str) -> dict[str, float]:
        raise DependencyMissing(f"LoRA runner unavailable: {self.reason}")