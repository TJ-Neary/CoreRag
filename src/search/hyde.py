"""
HyDE (Hypothetical Document Embedding) implementation for CoreRag.

Bridges the vocabulary gap between user queries and document content
by generating a hypothetical answer before embedding.

Process:
1. User asks: "How do I configure authentication?"
2. LLM generates: "To configure authentication, you need to set up OAuth2..."
3. We embed the generated text (not the question)
4. Vector search finds documents similar to the hypothetical answer

This dramatically improves retrieval for:
- Technical questions (matches jargon in docs)
- Conceptual queries (matches explanatory text)
- How-to questions (matches procedural content)
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.exceptions import SearchError
from src.utils.retry import RetryStrategies, with_retry

logger = logging.getLogger(__name__)


@dataclass
class HyDEResult:
    """Result of HyDE query expansion."""

    original_query: str
    hypothetical_document: str
    embedding: Optional[List[float]] = None
    cache_hit: bool = False


@dataclass
class HyDEConfig:
    """Configuration for HyDE generation."""

    # Generation parameters
    max_tokens: int = 150
    temperature: float = 0.7

    # Prompt template
    prompt_template: str = """You are an expert assistant. Given a question, write a short,
factual paragraph that directly answers it. Write as if this is from a technical document
or knowledge base. Be specific and use technical terms where appropriate.

Question: {query}

Answer:"""

    # Caching
    enable_cache: bool = True
    cache_dir: Optional[Path] = None

    # Query filtering
    min_query_length: int = 10
    skip_patterns: Optional[List[str]] = None

    def __post_init__(self):
        if self.skip_patterns is None:
            # Skip simple lookup queries that don't benefit from HyDE
            self.skip_patterns = [
                r"^what is",
                r"^define",
                r"^who is",
                r"^when did",
            ]


class HyDEExpander:
    """
    Expand queries using Hypothetical Document Embedding.

    Takes a user query, generates a hypothetical answer using an LLM,
    and returns the generated text for embedding instead of the original query.
    """

    def __init__(
        self,
        llm_generator: Callable[[str], str],
        embedder: Optional[Callable[[str], List[float]]] = None,
        config: Optional[HyDEConfig] = None,
    ):
        """
        Initialize HyDE expander.

        Args:
            llm_generator: Function that takes a prompt and returns generated text
            embedder: Optional function to generate embeddings
            config: HyDE configuration
        """
        self.llm_generator = llm_generator
        self.embedder = embedder
        self.config = config or HyDEConfig()

        # Setup cache
        self._cache: Dict[str, str] = {}
        if self.config.enable_cache and self.config.cache_dir:
            self._load_cache()

    def expand(self, query: str) -> HyDEResult:
        """
        Expand a query using HyDE.

        Args:
            query: User's search query

        Returns:
            HyDEResult with hypothetical document
        """
        query = query.strip()

        # Check if query should skip HyDE
        if self._should_skip(query):
            logger.debug(f"Skipping HyDE for query: {query[:50]}...")
            return HyDEResult(
                original_query=query,
                hypothetical_document=query,  # Use original
                cache_hit=False,
            )

        # Check cache
        cache_key = self._cache_key(query)
        if self.config.enable_cache and cache_key in self._cache:
            logger.debug(f"HyDE cache hit for: {query[:50]}...")
            hypothetical = self._cache[cache_key]
            result = HyDEResult(
                original_query=query,
                hypothetical_document=hypothetical,
                cache_hit=True,
            )
        else:
            # Generate hypothetical document
            hypothetical = self._generate_hypothetical(query)

            # Cache result
            if self.config.enable_cache:
                self._cache[cache_key] = hypothetical
                self._save_cache()

            result = HyDEResult(
                original_query=query,
                hypothetical_document=hypothetical,
                cache_hit=False,
            )

        # Generate embedding if embedder provided
        if self.embedder:
            result.embedding = self.embedder(result.hypothetical_document)

        return result

    def expand_batch(self, queries: List[str]) -> List[HyDEResult]:
        """
        Expand multiple queries.

        Args:
            queries: List of search queries

        Returns:
            List of HyDEResult objects
        """
        return [self.expand(q) for q in queries]

    def _generate_hypothetical(self, query: str) -> str:
        """Generate hypothetical document using LLM."""
        prompt = self.config.prompt_template.format(query=query)

        try:
            response = self.llm_generator(prompt)
            # Clean up response
            response = response.strip()

            # Validate response
            if len(response) < 20:
                logger.warning("HyDE generated short response, using original query")
                return query

            logger.debug(f"HyDE generated: {response[:100]}...")
            return response

        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}, using original query")
            return query

    def _should_skip(self, query: str) -> bool:
        """Check if query should skip HyDE expansion."""
        import re

        # Too short
        if len(query) < self.config.min_query_length:
            return True

        # Matches skip pattern
        query_lower = query.lower()
        for pattern in self.config.skip_patterns or []:
            if re.match(pattern, query_lower):
                return True

        return False

    def _cache_key(self, query: str) -> str:
        """Generate cache key for query."""
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        if self.config.cache_dir:
            cache_file = self.config.cache_dir / "hyde_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file) as f:
                        self._cache = json.load(f)
                    logger.info(f"Loaded {len(self._cache)} HyDE cache entries")
                except Exception as e:
                    logger.warning(f"Failed to load HyDE cache: {e}")

    def _save_cache(self) -> None:
        """Save cache to disk."""
        if self.config.cache_dir:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self.config.cache_dir / "hyde_cache.json"
            try:
                with open(cache_file, "w") as f:
                    json.dump(self._cache, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save HyDE cache: {e}")


class HyDESearcher:
    """
    Complete HyDE-enabled search pipeline.

    Combines:
    - HyDE query expansion
    - Vector similarity search
    - Optional re-ranking
    """

    def __init__(
        self,
        hyde_expander: HyDEExpander,
        vector_searcher: Callable[[List[float], int], List[Dict]],
        reranker: Optional[Callable[[str, List[Dict]], List[Dict]]] = None,
    ):
        """
        Initialize HyDE searcher.

        Args:
            hyde_expander: HyDE expander instance
            vector_searcher: Function that takes embedding and k, returns results
            reranker: Optional function to re-rank results
        """
        self.hyde_expander = hyde_expander
        self.vector_searcher = vector_searcher
        self.reranker = reranker

    def search(
        self,
        query: str,
        k: int = 10,
        use_hyde: bool = True,
        use_reranker: bool = True,
    ) -> Dict[str, Any]:
        """
        Search with HyDE expansion.

        Args:
            query: User's search query
            k: Number of results to return
            use_hyde: Whether to use HyDE expansion
            use_reranker: Whether to use re-ranking

        Returns:
            Search results with metadata
        """
        result = {
            "query": query,
            "hyde_used": False,
            "hypothetical_document": None,
            "results": [],
        }

        # Expand query with HyDE
        if use_hyde:
            hyde_result = self.hyde_expander.expand(query)
            result["hyde_used"] = True
            result["hypothetical_document"] = hyde_result.hypothetical_document

            if hyde_result.embedding:
                embedding = hyde_result.embedding
            else:
                # Need to generate embedding
                logger.warning("HyDE expander did not return embedding")
                return result
        else:
            # Use original query
            if self.hyde_expander.embedder:
                embedding = self.hyde_expander.embedder(query)
            else:
                logger.error("No embedder available")
                return result

        # Vector search
        search_k = k * 3 if use_reranker else k  # Oversample for re-ranking
        candidates = self.vector_searcher(embedding, search_k)

        # Re-rank using original query (not hypothetical)
        if use_reranker and self.reranker and candidates:
            candidates = self.reranker(query, candidates)

        # Trim to requested k
        result["results"] = candidates[:k]

        return result


# Factory function for common LLM backends
def create_hyde_expander(
    backend: str = "ollama",
    model: str = "llama3.2:3b",
    embedder: Optional[Callable[[str], List[float]]] = None,
    **kwargs,
) -> HyDEExpander:
    """
    Create HyDE expander with specified LLM backend.

    Args:
        backend: LLM backend ("ollama", "openai", "anthropic", "mlx")
        model: Model name
        embedder: Embedding function
        **kwargs: Additional config options

    Returns:
        Configured HyDEExpander
    """
    if backend == "ollama":

        @with_retry(**RetryStrategies.ollama_call())
        def ollama_generator(prompt: str) -> str:
            import requests

            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": kwargs.get("max_tokens", 150),
                        "temperature": kwargs.get("temperature", 0.7),
                    },
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("response", "")

        return HyDEExpander(
            llm_generator=ollama_generator,
            embedder=embedder,
            config=HyDEConfig(**{k: v for k, v in kwargs.items() if hasattr(HyDEConfig, k)}),
        )

    elif backend == "mlx":
        # MLX-LM for Apple Silicon
        def mlx_generator(prompt: str) -> str:
            try:
                from mlx_lm import generate, load

                mlx_model, tokenizer = load(model)
                response = generate(
                    mlx_model,
                    tokenizer,
                    prompt=prompt,
                    max_tokens=kwargs.get("max_tokens", 150),
                    temp=kwargs.get("temperature", 0.7),
                )
                return response
            except ImportError:
                raise ImportError("mlx-lm required for MLX backend. Install: pip install mlx-lm")

        return HyDEExpander(
            llm_generator=mlx_generator,
            embedder=embedder,
            config=HyDEConfig(**{k: v for k, v in kwargs.items() if hasattr(HyDEConfig, k)}),
        )

    else:
        raise SearchError(f"Unknown HyDE backend: {backend}")


# Convenience function
def hyde_search(
    query: str,
    vector_db,  # LanceDB table
    llm_generator: Callable[[str], str],
    embedder: Callable[[str], List[float]],
    k: int = 5,
) -> List[Dict]:
    """
    Quick HyDE search using LanceDB.

    Args:
        query: Search query
        vector_db: LanceDB table
        llm_generator: Function to generate hypothetical document
        embedder: Function to generate embeddings
        k: Number of results

    Returns:
        Search results
    """
    expander = HyDEExpander(llm_generator=llm_generator, embedder=embedder)
    hyde_result = expander.expand(query)

    # Generate embedding for hypothetical document
    embedding = embedder(hyde_result.hypothetical_document)

    # Search
    results = vector_db.search(embedding).limit(k).to_list()

    return results
