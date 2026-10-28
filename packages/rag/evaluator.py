"""Ranking metrics computed from real retrieval output."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol


class _Searchable(Protocol):
    def search(self, query: str, k: int = 5) -> list[Any]: ...


def _check(rankings: Sequence[Sequence[str]], golds: Sequence[str]) -> None:
    if len(rankings) != len(golds):
        raise ValueError("rankings and golds must have the same length")


def recall_at_k(
    rankings: Sequence[Sequence[str]],
    golds: Sequence[str],
    k: int,
) -> float:
    _check(rankings, golds)
    if not rankings:
        return 0.0
    hits = sum(1 for ranking, gold in zip(rankings, golds, strict=False) if gold in list(ranking)[:k])
    return round(hits / len(rankings), 4)


def mrr(rankings: Sequence[Sequence[str]], golds: Sequence[str]) -> float:
    _check(rankings, golds)
    if not rankings:
        return 0.0
    total = 0.0
    for ranking, gold in zip(rankings, golds, strict=False):
        ordered = list(ranking)
        if gold in ordered:
            total += 1.0 / (ordered.index(gold) + 1)
    return round(total / len(rankings), 4)


def ndcg_at_k(
    rankings: Sequence[Sequence[str]],
    golds: Sequence[str],
    k: int,
) -> float:
    """Binary-relevance nDCG with a single relevant document per query."""
    _check(rankings, golds)
    if not rankings:
        return 0.0
    total = 0.0
    for ranking, gold in zip(rankings, golds, strict=False):
        ordered = list(ranking)[:k]
        if gold in ordered:
            rank = ordered.index(gold)
            total += 1.0 / math.log2(rank + 2)
    return round(total / len(rankings), 4)


def evaluate(
    retriever: _Searchable,
    cases: Sequence[dict[str, Any]],
    *,
    k_values: Sequence[int] = (1, 3),
) -> dict[str, Any]:
    rankings: list[list[str]] = []
    golds: list[str] = []
    for case in cases:
        hits = retriever.search(str(case["query"]), k=max(k_values))
        rankings.append([str(hit.doc_id) for hit in hits])
        golds.append(str(case["gold_doc_id"]))

    report: dict[str, Any] = {
        "query_count": len(cases),
        "mrr": mrr(rankings, golds),
    }
    for k in k_values:
        report[f"recall@{k}"] = recall_at_k(rankings, golds, k)
        report[f"ndcg@{k}"] = ndcg_at_k(rankings, golds, k)
    return report