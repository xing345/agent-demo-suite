"""Offline RAG baseline: chunking, hashing embeddings, evaluation."""

from .chunking import Chunk, chunk_text
from .embedder import Embedder, GatewayEmbedder, HashingEmbedder
from .evaluator import evaluate, mrr, ndcg_at_k, recall_at_k
from .index import InMemoryVectorIndex
from .retriever import Hit, RagRetriever

__all__ = [
    "Chunk",
    "Embedder",
    "GatewayEmbedder",
    "HashingEmbedder",
    "Hit",
    "InMemoryVectorIndex",
    "RagRetriever",
    "chunk_text",
    "evaluate",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
]