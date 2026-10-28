"""Retriever: chunk documents, embed them, return document-level hits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .chunking import Chunk, chunk_text
from .embedder import Embedder
from .index import InMemoryVectorIndex


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    text: str
    score: float


class RagRetriever:
    def __init__(
        self,
        *,
        embedder: Embedder,
        chunk_size: int = 200,
        overlap: int = 20,
    ) -> None:
        self.embedder = embedder
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.index = InMemoryVectorIndex()
        self._chunks: dict[str, Chunk] = {}

    def index_documents(self, documents: Mapping[str, str]) -> int:
        chunks: list[Chunk] = []
        for doc_id, text in documents.items():
            chunks.extend(
                chunk_text(
                    text,
                    size=self.chunk_size,
                    overlap=self.overlap,
                    doc_id=doc_id,
                )
            )
        if not chunks:
            return 0

        vectors = self.embedder.embed([chunk.text for chunk in chunks])
        self.index.add(chunks, vectors)
        self._chunks.update({chunk.chunk_id: chunk for chunk in chunks})
        return len(chunks)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        if len(self.index) == 0 or not query.strip():
            return []

        vector = self.embedder.embed([query])[0]
        best: dict[str, Hit] = {}
        for chunk_id, score in self.index.search(vector, k=max(k * 3, k)):
            chunk = self._chunks[chunk_id]
            current = best.get(chunk.doc_id)
            if current is None or score > current.score:
                best[chunk.doc_id] = Hit(chunk.chunk_id, chunk.doc_id, chunk.text, score)

        ranked = sorted(best.values(), key=lambda hit: hit.score, reverse=True)
        return ranked[:k]