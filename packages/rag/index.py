"""In-memory vector index with exact cosine similarity (small corpora only)."""

from __future__ import annotations

from .chunking import Chunk

__all__ = ["Chunk", "InMemoryVectorIndex"]


class InMemoryVectorIndex:
    """Brute-force index; documented limit is roughly 10k chunks."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        self._chunks.extend(chunks)
        self._vectors.extend(vectors)

    def search(self, vector: list[float], k: int = 5) -> list[tuple[str, float]]:
        if k <= 0:
            raise ValueError("k must be positive")
        scored = [
            (chunk.chunk_id, _dot(vector, candidate))
            for chunk, candidate in zip(self._chunks, self._vectors, strict=False)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def chunk(self, chunk_id: str) -> Chunk:
        for chunk in self._chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise KeyError(f"unknown chunk: {chunk_id}")


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))