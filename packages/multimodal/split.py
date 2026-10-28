"""Deterministic train/validation splitting."""

from __future__ import annotations

import random
from collections.abc import Sequence


def split_ids(
    ids: Sequence[str],
    *,
    train_ratio: float = 0.8,
    seed: int = 42,
) -> dict[str, list[str]]:
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio must be strictly between 0 and 1")

    ordered = sorted(ids)
    rng = random.Random(seed)
    rng.shuffle(ordered)

    if len(ordered) < 2:
        return {"train": ordered, "val": []}

    cut = max(1, min(len(ordered) - 1, int(round(len(ordered) * train_ratio))))
    return {"train": sorted(ordered[:cut]), "val": sorted(ordered[cut:])}