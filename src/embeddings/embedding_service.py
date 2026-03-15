"""
Centralized Embedding Service for CoreRag.

Provides a single interface for all embedding operations:
- Text embedding with sentence-transformers
- Batch processing with automatic throttling
- Caching to avoid redundant computations
- Model versioning support

Optimized for Apple Silicon M4 Max with Metal acceleration.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.config import EMBEDDING_BATCH_SIZE
from src.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# Check for sentence-transformers
ST_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer

    ST_AVAILABLE = True
except ImportError:
    logger.warning("sentence-transformers not installed")


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    text: str
    embedding: List[float]
    model: str
    cached: bool = False
    latency_ms: float = 0.0


@dataclass
class EmbeddingStats:
    """Statistics for embedding operations."""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def cache_hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.cache_misses == 0:
            return 0.0
        return self.total_latency_ms / self.cache_misses


class EmbeddingCache:
    """
    LRU cache for embeddings with disk persistence.

    Avoids recomputing embeddings for identical text.
    """

    def __init__(
        self,
        max_size: int = 10000,
        cache_dir: Optional[Path] = None,
        persist: bool = True,
    ):
        """
        Initialize embedding cache.

        Args:
            max_size: Maximum entries in memory
            cache_dir: Directory for disk persistence
            persist: Whether to persist to disk
        """
        self.max_size = max_size
        from src.config import STATE_DIR

        self.cache_dir = cache_dir or STATE_DIR / "embedding_cache"
        self.persist = persist

        self._cache: Dict[str, List[float]] = {}
        self._access_order: List[str] = []
        self._lock = threading.Lock()

        if persist:
            self._load_cache()

    def get(self, text: str, model: str) -> Optional[List[float]]:
        """Get cached embedding if exists."""
        key = self._make_key(text, model)

        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._access_order.remove(key)
                self._access_order.append(key)
                return self._cache[key]

        return None

    def put(self, text: str, model: str, embedding: List[float]) -> None:
        """Cache an embedding."""
        key = self._make_key(text, model)

        with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_size:
                oldest = self._access_order.pop(0)
                del self._cache[oldest]

            self._cache[key] = embedding
            self._access_order.append(key)

    def _make_key(self, text: str, model: str) -> str:
        """Create cache key from text and model."""
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _load_cache(self) -> None:
        """Load cache from disk."""
        cache_file = self.cache_dir / "embeddings.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                    self._cache = data.get("cache", {})
                    self._access_order = data.get("order", list(self._cache.keys()))
                logger.info(f"Loaded {len(self._cache)} cached embeddings")
            except Exception as e:
                logger.warning(f"Failed to load embedding cache: {e}")

    def save(self) -> None:
        """Save cache to disk."""
        if not self.persist:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / "embeddings.json"

        try:
            with open(cache_file, "w") as f:
                json.dump(
                    {
                        "cache": self._cache,
                        "order": self._access_order,
                    },
                    f,
                )
        except Exception as e:
            logger.warning(f"Failed to save embedding cache: {e}")

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()

    def __len__(self) -> int:
        return len(self._cache)


class EmbeddingService:
    """
    Centralized service for all embedding operations.

    Features:
    - Single model instance (memory efficient)
    - Automatic batching with throttling
    - Caching for repeated text
    - Statistics tracking
    - Model versioning support
    """

    # Supported models with their dimensions and full HuggingFace paths
    SUPPORTED_MODELS = {
        "nomic-ai/nomic-embed-text-v1.5": 768,
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "multi-qa-mpnet-base-dot-v1": 768,
        "paraphrase-multilingual-MiniLM-L12-v2": 384,
        "BAAI/bge-m3": 1024,
    }

    # Model name aliases for backwards compatibility
    MODEL_ALIASES = {
        "nomic-embed-text-v1.5": "nomic-ai/nomic-embed-text-v1.5",
        "bge-m3": "BAAI/bge-m3",
    }

    # Models that need a query instruction prefix for asymmetric search
    QUERY_INSTRUCTION_MODELS = {
        "BAAI/bge-m3": "Represent this sentence for searching relevant passages: ",
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_enabled: bool = True,
        cache_dir: Optional[Path] = None,
        device: str = "mps",  # Apple Silicon
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        """
        Initialize embedding service.

        Args:
            model_name: Name of the embedding model
            cache_enabled: Whether to cache embeddings
            cache_dir: Directory for cache storage
            device: Device for inference ("mps", "cuda", "cpu")
            batch_size: Default batch size for encoding
        """
        if not ST_AVAILABLE:
            raise EmbeddingError("sentence-transformers required", model_name=model_name)

        # Default to config if not specified
        if model_name is None:
            from src.config import EMBEDDING_MODEL

            model_name = EMBEDDING_MODEL

        # Resolve model name aliases
        self.model_name = self.MODEL_ALIASES.get(model_name, model_name)
        self.device = device
        self.batch_size = batch_size

        # Initialize model
        logger.info(f"Loading embedding model: {self.model_name}")

        try:
            # nomic models require trust_remote_code
            trust_remote = "nomic" in self.model_name.lower()
            self._model = SentenceTransformer(
                self.model_name, device=device, trust_remote_code=trust_remote
            )
            self._dimension: int = self._model.get_sentence_embedding_dimension() or 0
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(
                f"Failed to load embedding model: {e}", model_name=self.model_name
            ) from e

        # Initialize cache
        self.cache_enabled = cache_enabled
        self._cache = EmbeddingCache(cache_dir=cache_dir) if cache_enabled else None

        # Statistics
        self._stats = EmbeddingStats()
        self._lock = threading.Lock()

        logger.info(f"Embedding service ready: {model_name} ({self._dimension}D) on {device}")

    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        return self._dimension

    @property
    def stats(self) -> EmbeddingStats:
        """Get current statistics."""
        return self._stats

    def embed(self, text: str) -> EmbeddingResult:
        """
        Embed a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with embedding vector
        """
        results = self.embed_batch([text])
        return results[0]

    def embed_batch(
        self,
        texts: List[str],
        show_progress: bool = False,
    ) -> List[EmbeddingResult]:
        """
        Embed a batch of texts.

        Args:
            texts: List of texts to embed
            show_progress: Show progress bar

        Returns:
            List of EmbeddingResult objects
        """
        results = []
        texts_to_embed = []
        cache_indices = []

        # Check cache first
        for i, text in enumerate(texts):
            with self._lock:
                self._stats.total_requests += 1

            if self.cache_enabled and self._cache is not None:
                cached = self._cache.get(text, self.model_name)
                if cached is not None:
                    with self._lock:
                        self._stats.cache_hits += 1
                    results.append(
                        EmbeddingResult(
                            text=text,
                            embedding=cached,
                            model=self.model_name,
                            cached=True,
                        )
                    )
                    continue

            with self._lock:
                self._stats.cache_misses += 1

            texts_to_embed.append(text)
            cache_indices.append(i)

        # Embed uncached texts
        if texts_to_embed:
            start_time = time.time()

            embeddings = self._model.encode(
                texts_to_embed,
                batch_size=self.batch_size,
                show_progress_bar=show_progress,
                convert_to_numpy=True,
            )

            latency = (time.time() - start_time) * 1000

            with self._lock:
                self._stats.total_latency_ms += latency

            # Process results
            for j, (text, embedding) in enumerate(zip(texts_to_embed, embeddings)):
                embedding_list = embedding.tolist()

                # Cache the result
                if self.cache_enabled and self._cache is not None:
                    self._cache.put(text, self.model_name, embedding_list)

                result = EmbeddingResult(
                    text=text,
                    embedding=embedding_list,
                    model=self.model_name,
                    cached=False,
                    latency_ms=latency / len(texts_to_embed),
                )

                # Insert at correct position
                results.insert(cache_indices[j], result)

        return results

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a search query.

        Applies model-specific query instruction prefix (e.g., BGE-M3 needs
        a prefix for asymmetric retrieval). Document embedding does NOT get
        the prefix — only queries.
        """
        prefix = self.QUERY_INSTRUCTION_MODELS.get(self.model_name, "")
        text = prefix + query if prefix else query
        result = self.embed(text)
        return result.embedding

    def embed_documents(
        self,
        documents: List[str],
        show_progress: bool = True,
    ) -> List[List[float]]:
        """
        Embed multiple documents.

        Convenience method that returns just the embedding vectors.
        """
        results = self.embed_batch(documents, show_progress=show_progress)
        return [r.embedding for r in results]

    def similarity(self, text1: str, text2: str) -> float:
        """
        Compute cosine similarity between two texts.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Cosine similarity score (0-1)
        """
        import numpy as np

        emb1 = self.embed(text1).embedding
        emb2 = self.embed(text2).embedding

        # Cosine similarity
        dot = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)

        return float(dot / (norm1 * norm2))

    def save_cache(self) -> None:
        """Persist cache to disk."""
        if self._cache:
            self._cache.save()

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        if self._cache:
            self._cache.clear()

    def embed_with_sparse(
        self,
        documents: List[str],
        show_progress: bool = True,
    ) -> tuple:
        """Return (dense_vectors, sparse_vectors) using BGE-M3's dual output.

        Sparse vectors are dicts of {token_id: weight}. Only available for BGE-M3.
        For other models, returns empty dicts as sparse vectors.
        """
        if "bge-m3" not in self.model_name.lower():
            dense = self.embed_documents(documents, show_progress=show_progress)
            return dense, [{}] * len(documents)

        if not hasattr(self, "_flag_model"):
            # Patch missing import for transformers 5.0+ compatibility
            import transformers.utils.import_utils as _iu

            if not hasattr(_iu, "is_torch_fx_available"):
                _iu.is_torch_fx_available = lambda: False

            from FlagEmbedding import BGEM3FlagModel

            device = "mps" if self.device == "mps" else "cpu"
            self._flag_model = BGEM3FlagModel(
                self.model_name, use_fp16=(device != "cpu"), devices=device
            )

        output = self._flag_model.encode(
            documents, return_dense=True, return_sparse=True, batch_size=32
        )

        dense_vecs = output["dense_vecs"].tolist()
        sparse_vecs = [
            {int(k): float(v) for k, v in weights.items()} for weights in output["lexical_weights"]
        ]

        return dense_vecs, sparse_vecs

    def embed_query_with_sparse(self, query: str) -> tuple:
        """Embed a query returning both dense vector and sparse weights."""
        dense_list, sparse_list = self.embed_with_sparse([query], show_progress=False)
        return dense_list[0], sparse_list[0]

    def get_info(self) -> dict:
        """Get service information."""
        return {
            "model": self.model_name,
            "dimension": self._dimension,
            "device": self.device,
            "cache_enabled": self.cache_enabled,
            "cache_size": len(self._cache) if self._cache else 0,
            "stats": {
                "total_requests": self._stats.total_requests,
                "cache_hit_rate": f"{self._stats.cache_hit_rate:.2%}",
                "avg_latency_ms": f"{self._stats.avg_latency_ms:.2f}",
            },
        }


# Singleton instance
_default_service: Optional[EmbeddingService] = None


def get_embedding_service(
    model_name: Optional[str] = None,
    **kwargs,
) -> EmbeddingService:
    """
    Get or create the default embedding service.

    Uses singleton pattern for memory efficiency.
    """
    global _default_service

    if _default_service is None:
        _default_service = EmbeddingService(model_name=model_name, **kwargs)
    elif _default_service.model_name != model_name:
        logger.warning(
            f"Requested model {model_name} but {_default_service.model_name} is loaded. "
            "Use create_embedding_service() for a new instance."
        )

    return _default_service


def create_embedding_service(
    model_name: Optional[str] = None,
    **kwargs,
) -> EmbeddingService:
    """
    Create a new embedding service instance.

    Use this when you need multiple models or isolated instances.
    """
    return EmbeddingService(model_name=model_name, **kwargs)
