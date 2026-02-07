"""Embeddings module for generating and caching text embeddings."""

from .embedding_service import EmbeddingCache, EmbeddingResult, EmbeddingService

__all__ = ["EmbeddingService", "EmbeddingResult", "EmbeddingCache"]
