"""Embedders.

``HashingEmbedder`` is a deterministic lexical baseline (hashed token counts,
L2-normalised). It is deliberately *not* a semantic model: it makes the RAG
pipeline runnable offline and makes metrics reproducible. Real deployments
should pass a provider-backed embedder via ``GatewayEmbedder``.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in TOKEN_PATTERN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            vector[int(digest, 16) % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class GatewayEmbedder:
    """Adapter over a model gateway that exposes ``embed_sync``."""

    def __init__(self, gateway: Any) -> None:
        embed = getattr(gateway, "embed_sync", None)
        if embed is None:
            raise TypeError("gateway does not expose embed_sync")
        self._embed = embed

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)