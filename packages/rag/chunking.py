"""Deterministic character-window chunking with overlap."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    start: int = 0


def chunk_text(
    text: str,
    *,
    size: int = 200,
    overlap: int = 20,
    doc_id: str = "doc",
) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be greater than or equal to 0 and smaller than size")
    if not text:
        return []

    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(text):
        piece = text[start : start + size]
        if not piece:
            break
        chunks.append(Chunk(f"{doc_id}:{index}", doc_id, piece, start))
        index += 1
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks