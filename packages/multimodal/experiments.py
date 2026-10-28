"""Experiment records and before/after comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .adapters import DependencyMissing
from .lora import LoRAConfig, LoRARunner


@dataclass
class ExperimentRecord:
    experiment_id: str
    name: str
    dataset_id: str
    dataset_version: int
    config: dict[str, Any]
    status: str
    metrics: dict[str, float] | None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "config": dict(self.config),
            "status": self.status,
            "metrics": None if self.metrics is None else dict(self.metrics),
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


class ExperimentRegistry:
    def __init__(self, *, runner: LoRARunner) -> None:
        self.runner = runner
        self._records: dict[str, ExperimentRecord] = {}

    def create(
        self,
        *,
        name: str,
        dataset_id: str,
        dataset_version: int,
        config: LoRAConfig,
    ) -> ExperimentRecord:
        status = "completed"
        metrics: dict[str, float] | None = None
        error: str | None = None

        probe = self.runner.probe()
        if not probe.available:
            status = "unavailable"
            error = probe.reason
        else:
            try:
                metrics = self.runner.train(config, f"{dataset_id}@v{dataset_version}")
            except DependencyMissing as exc:
                status = "failed"
                error = str(exc)

        record = ExperimentRecord(
            experiment_id=str(uuid4()),
            name=name,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            config=config.model_dump(mode="json"),
            status=status,
            metrics=metrics,
            error=error,
        )
        self._records[record.experiment_id] = record
        return record

    def get(self, experiment_id: str) -> ExperimentRecord:
        try:
            return self._records[experiment_id]
        except KeyError as exc:
            raise KeyError(f"unknown experiment: {experiment_id}") from exc

    def list(self) -> list[ExperimentRecord]:
        return list(self._records.values())

    def compare(self, candidate_id: str, baseline_id: str) -> dict[str, float | None]:
        candidate = self.get(candidate_id)
        baseline = self.get(baseline_id)
        return compare_metrics(baseline.metrics, candidate.metrics)


def compare_metrics(
    baseline: dict[str, float] | None,
    candidate: dict[str, float] | None,
) -> dict[str, float | None]:
    """Delta = candidate - baseline; ``None`` when either side is missing."""
    keys = sorted(set(baseline or {}) | set(candidate or {}))
    deltas: dict[str, float | None] = {}
    for key in keys:
        before = (baseline or {}).get(key)
        after = (candidate or {}).get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            deltas[key] = round(float(after) - float(before), 6)
        else:
            deltas[key] = None
    return deltas