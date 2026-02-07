"""
Cross-Encoder Re-ranking

Re-ranks search results using a cross-encoder model that reads
both the query and candidate together for more accurate relevance scoring.

Bi-encoders (embedding models) are fast but approximate.
Cross-encoders are slower but more accurate.

Pipeline: Bi-encoder (top 50) → Cross-encoder (top 5)
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from src.exceptions import SearchError

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Result after cross-encoder re-ranking."""

    id: str
    content: str
    document_id: str
    original_score: float
    rerank_score: float
    original_rank: int
    final_rank: int
    metadata: dict


class CrossEncoderReranker:
    """
    Re-rank search results using a cross-encoder model.

    Supports multiple backends:
    - MLX (Apple Silicon optimized)
    - sentence-transformers (CPU/CUDA)

    Recommended models for M4 Max:
    - mixedbread-ai/mxbai-rerank-base-v1 (fastest, English)
    - BAAI/bge-reranker-v2-m3 (multilingual)
    """

    def __init__(
        self,
        model_name: str = "mixedbread-ai/mxbai-rerank-base-v1",
        backend: str = "auto",
        batch_size: int = 32,
        max_length: int = 512,
    ):
        """
        Initialize re-ranker.

        Args:
            model_name: HuggingFace model identifier
            backend: "mlx", "transformers", or "auto"
            batch_size: Batch size for inference
            max_length: Maximum sequence length (query + document)
        """
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = None
        self._backend = self._detect_backend(backend)
        logger.info(f"Re-ranker backend: {self._backend}, model: {model_name}")

    def _detect_backend(self, requested: str) -> str:
        """Detect best available backend."""
        if requested != "auto":
            return requested

        # Prefer MLX on Apple Silicon
        try:
            import importlib.util
            import platform

            if importlib.util.find_spec("mlx.core") and platform.processor() == "arm":
                return "mlx"
        except ImportError:
            pass

        # Fallback to transformers
        try:
            import importlib.util

            if importlib.util.find_spec("sentence_transformers"):
                return "transformers"
        except ImportError:
            pass

        raise SearchError("No re-ranking backend available. Install sentence-transformers or mlx.")

    def _load_model(self):
        """Lazy-load the model."""
        if self._model is not None:
            return

        if self._backend == "mlx":
            self._model = self._load_mlx_model()
        else:
            self._model = self._load_transformers_model()

    def _load_mlx_model(self):
        """Load model for MLX inference."""
        # MLX cross-encoder loading
        # Note: MLX doesn't have native cross-encoder support yet,
        # so we use a custom implementation or fallback
        try:
            from mlx_lm import load

            model, tokenizer = load(self.model_name)
            return {"model": model, "tokenizer": tokenizer}
        except Exception as e:
            logger.warning(f"MLX model load failed, falling back to transformers: {e}")
            self._backend = "transformers"
            return self._load_transformers_model()

    def _load_transformers_model(self):
        """Load model using sentence-transformers."""
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(self.model_name, max_length=self.max_length)
        return model

    def rerank(
        self,
        query: str,
        candidates: List[dict],
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        """
        Re-rank candidates using cross-encoder.

        Args:
            query: Search query
            candidates: List of candidate documents with "id", "content", "document_id"
            top_k: Number of results to return after re-ranking
            score_threshold: Minimum score to include (0-1)

        Returns:
            Re-ranked results, sorted by rerank_score descending
        """
        if not candidates:
            return []

        self._load_model()
        start_time = time.time()

        # Prepare pairs
        pairs = [(query, c["content"][: self.max_length * 4]) for c in candidates]

        # Score with cross-encoder
        if self._backend == "mlx":
            scores = self._score_mlx(pairs)
        else:
            scores = self._score_transformers(pairs)

        # Build results
        results = []
        for i, (candidate, score) in enumerate(zip(candidates, scores)):
            if score_threshold is not None and score < score_threshold:
                continue

            results.append(
                RerankResult(
                    id=candidate["id"],
                    content=candidate["content"],
                    document_id=candidate["document_id"],
                    original_score=candidate.get("score", 0),
                    rerank_score=score,
                    original_rank=i + 1,
                    final_rank=0,  # Set after sorting
                    metadata=candidate.get("metadata", {}),
                )
            )

        # Sort by rerank score
        results.sort(key=lambda x: x.rerank_score, reverse=True)

        # Set final ranks and truncate
        for i, r in enumerate(results[:top_k]):
            r.final_rank = i + 1

        elapsed = (time.time() - start_time) * 1000
        logger.debug(f"Re-ranked {len(candidates)} candidates in {elapsed:.1f}ms")

        return results[:top_k]

    def _score_transformers(self, pairs: List[tuple]) -> List[float]:
        """Score using sentence-transformers CrossEncoder."""
        scores = self._model.predict(pairs, batch_size=self.batch_size)
        # Normalize to 0-1 range using sigmoid if needed
        return [float(s) for s in scores]

    def _score_mlx(self, pairs: List[tuple]) -> List[float]:
        """Score using MLX (custom implementation)."""
        # MLX cross-encoder scoring
        # This is a placeholder - real implementation depends on model architecture
        import mlx.core as mx

        model = self._model["model"]
        tokenizer = self._model["tokenizer"]

        scores = []
        for query, doc in pairs:
            # Tokenize pair
            inputs = tokenizer(
                query,
                doc,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np",
            )

            # Convert to MLX arrays
            input_ids = mx.array(inputs["input_ids"])
            attention_mask = mx.array(inputs["attention_mask"])

            # Forward pass
            outputs = model(input_ids, attention_mask)

            # Get score (implementation depends on model)
            score = float(outputs[0, 0])
            scores.append(score)

        return scores


class RerankerPipeline:
    """
    Complete retrieval + re-ranking pipeline.

    Usage:
        pipeline = RerankerPipeline(retriever, reranker)
        results = await pipeline.search(query, k=5, rerank_candidates=50)
    """

    def __init__(
        self,
        retriever,  # HybridSearcher or ParentChildRetriever
        reranker: Optional[CrossEncoderReranker] = None,
    ):
        self.retriever = retriever
        self.reranker = reranker or CrossEncoderReranker()

    async def search(
        self,
        query: str,
        query_vector: List[float],
        k: int = 5,
        rerank_candidates: int = 50,
        use_reranker: bool = True,
        **retriever_kwargs,
    ) -> List[RerankResult]:
        """
        Search with optional re-ranking.

        Args:
            query: Search query text
            query_vector: Embedded query vector
            k: Final number of results
            rerank_candidates: Number of candidates to retrieve for re-ranking
            use_reranker: Whether to apply cross-encoder re-ranking
            **retriever_kwargs: Additional args for retriever

        Returns:
            Final ranked results
        """
        # Step 1: Retrieve candidates
        candidates = await self.retriever.search(
            query=query,
            query_vector=query_vector,
            k=rerank_candidates if use_reranker else k,
            **retriever_kwargs,
        )

        if not use_reranker:
            # Return retrieval results directly
            return [
                RerankResult(
                    id=c.get("id", c.get("parent_id")),
                    content=c["content"],
                    document_id=c["document_id"],
                    original_score=c.get("score", c.get("rrf_score", 0)),
                    rerank_score=c.get("score", c.get("rrf_score", 0)),
                    original_rank=i + 1,
                    final_rank=i + 1,
                    metadata=c.get("metadata", {}),
                )
                for i, c in enumerate(candidates[:k])
            ]

        # Step 2: Re-rank with cross-encoder
        return self.reranker.rerank(
            query=query,
            candidates=[
                {
                    "id": c.get("id", c.get("parent_id")),
                    "content": c["content"],
                    "document_id": c["document_id"],
                    "score": c.get("score", c.get("rrf_score", 0)),
                    "metadata": c.get("metadata", {}),
                }
                for c in candidates
            ],
            top_k=k,
        )


# Convenience function
def create_reranker(model: str = "auto", backend: str = "auto") -> CrossEncoderReranker:
    """
    Create a re-ranker with sensible defaults for M4 Max.

    Args:
        model: Model name or "auto" for best default
        backend: Backend or "auto" for detection
    """
    if model == "auto":
        # Default to fast English model
        model = "mixedbread-ai/mxbai-rerank-base-v1"

    return CrossEncoderReranker(model_name=model, backend=backend, batch_size=32, max_length=512)
