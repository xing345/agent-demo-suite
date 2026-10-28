"""Guards for the golden set: consistency plus a baseline quality floor."""

import json
from pathlib import Path

from packages.rag import HashingEmbedder, RagRetriever, evaluate

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden"


def _load(name: str) -> list[dict]:
    path = GOLDEN / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_golden_set_is_consistent() -> None:
    corpus = _load("corpus.jsonl")
    cases = _load("qa.jsonl")

    doc_ids = [row["doc_id"] for row in corpus]
    assert len(doc_ids) == len(set(doc_ids))
    assert all(case["gold_doc_id"] in set(doc_ids) for case in cases)
    assert all(case.get("synthetic") is True for case in cases)


def test_baseline_retrieval_meets_quality_floor() -> None:
    corpus = _load("corpus.jsonl")
    cases = _load("qa.jsonl")
    retriever = RagRetriever(embedder=HashingEmbedder(dim=256), chunk_size=240, overlap=40)
    retriever.index_documents({row["doc_id"]: row["text"] for row in corpus})

    report = evaluate(retriever, cases, k_values=(1, 3))

    assert report["recall@1"] >= 0.8
    assert report["recall@3"] >= 0.9
    assert report["mrr"] >= 0.8
    assert 0.0 <= report["ndcg@3"] <= 1.0