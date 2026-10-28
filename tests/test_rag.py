"""RAG: chunking, hashing embeddings, retrieval and ranking metrics."""

import pytest

from packages.rag.chunking import chunk_text
from packages.rag.embedder import HashingEmbedder
from packages.rag.evaluator import evaluate, mrr, ndcg_at_k, recall_at_k
from packages.rag.index import Chunk, InMemoryVectorIndex
from packages.rag.retriever import RagRetriever


def test_chunking_splits_with_overlap() -> None:
    chunks = chunk_text("abcdefghij" * 10, size=40, overlap=10)

    assert len(chunks) >= 3
    assert chunks[0].text == "abcdefghij" * 4
    assert chunks[1].start == 30
    assert all(len(chunk.text) <= 40 for chunk in chunks)


def test_chunking_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        chunk_text("text", size=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("text", size=10, overlap=10)


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(dim=64)

    first = embedder.embed(["hello world"])[0]
    second = embedder.embed(["hello world"])[0]

    assert first == second
    assert len(first) == 64
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_index_returns_best_match_first() -> None:
    embedder = HashingEmbedder(dim=128)
    index = InMemoryVectorIndex()
    chunks = [
        Chunk(chunk_id="c1", doc_id="d1", text="alpha beta"),
        Chunk(chunk_id="c2", doc_id="d2", text="gamma delta"),
    ]
    index.add(chunks, embedder.embed([chunk.text for chunk in chunks]))

    hits = index.search(embedder.embed(["alpha beta"])[0], k=2)

    assert hits[0][0] == "c1"
    assert hits[0][1] > hits[1][1]


def test_retriever_returns_document_level_hits() -> None:
    retriever = RagRetriever(embedder=HashingEmbedder(dim=128))
    retriever.index_documents(
        {
            "d1": "the runtime executes plans and records events",
            "d2": "lora fine tuning for multimodal models",
        }
    )

    hits = retriever.search("runtime executes plans", k=1)

    assert hits[0].doc_id == "d1"
    assert hits[0].text


def test_relevance_metrics_have_expected_values() -> None:
    rankings = [["a", "b", "c"], ["c", "b", "a"]]
    golds = ["a", "b"]

    assert recall_at_k(rankings, golds, 1) == 0.5
    assert recall_at_k(rankings, golds, 2) == 1.0
    assert mrr(rankings, golds) == pytest.approx(0.75)
    assert ndcg_at_k([["a", "b"]], ["a"], 2) == pytest.approx(1.0)
    assert 0.0 < ndcg_at_k([["b", "a"]], ["a"], 2) < 1.0


def test_metrics_reject_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        recall_at_k([["a"]], ["a", "b"], 1)


def test_evaluate_reports_all_metrics() -> None:
    class FakeRetriever:
        def search(self, query: str, k: int = 5) -> list:
            class Hit:
                doc_id = "gold" if query.startswith("hit") else "other"

            return [Hit()]

    report = evaluate(
        FakeRetriever(),  # type: ignore[arg-type]
        [{"query": "hit one", "gold_doc_id": "gold"}, {"query": "miss", "gold_doc_id": "gold"}],
        k_values=(1, 3),
    )

    assert report["recall@1"] == 0.5
    assert report["recall@3"] == 0.5
    assert report["mrr"] == pytest.approx(0.5)
    assert report["query_count"] == 2
    assert "ndcg@3" in report