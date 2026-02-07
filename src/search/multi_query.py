"""
Multi-Query Fusion for CoreRag.

Handle complex questions by decomposing into sub-queries:
- Break complex questions into simpler parts
- Execute sub-queries in parallel
- Fuse results with reciprocal rank fusion
- Remove duplicates across results
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.utils.retry import RetryStrategies, with_retry

logger = logging.getLogger(__name__)


@dataclass
class SubQuery:
    """A decomposed sub-query."""

    query: str
    query_type: str  # "factual", "conceptual", "procedural", "comparison"
    focus: Optional[str] = None  # Key concept to find
    weight: float = 1.0  # Importance weight


@dataclass
class FusedResult:
    """A result from multi-query fusion."""

    content: str
    source_path: str
    fused_score: float
    contributing_queries: List[str]
    original_ranks: Dict[str, int]  # query -> rank
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiQueryResult:
    """Result of multi-query search."""

    original_query: str
    sub_queries: List[SubQuery]
    results: List[FusedResult]
    total_results_before_fusion: int
    fusion_method: str


class QueryDecomposer:
    """
    Decompose complex queries into simpler sub-queries.

    Strategies:
    - Compound splitting (A and B -> A, B)
    - Comparison extraction (A vs B -> A, B, comparison)
    - Multi-aspect queries (how, why, what)
    - Entity extraction
    """

    # Patterns for decomposition
    COMPOUND_PATTERNS = [
        (r"(.+)\s+and\s+(.+)", "compound"),
        (r"(.+)\s+as well as\s+(.+)", "compound"),
        (r"(.+)\s+along with\s+(.+)", "compound"),
        (r"(.+),\s+(.+),\s+and\s+(.+)", "triple_compound"),
    ]

    COMPARISON_PATTERNS = [
        (r"(.+)\s+vs\.?\s+(.+)", "comparison"),
        (r"(.+)\s+versus\s+(.+)", "comparison"),
        (r"(.+)\s+compared to\s+(.+)", "comparison"),
        (r"difference between\s+(.+)\s+and\s+(.+)", "comparison"),
        (r"(.+)\s+or\s+(.+)\s*\?", "choice"),
    ]

    MULTI_ASPECT_PATTERNS = [
        (r"what is (.+) and how", "what_how"),
        (r"why (.+) and how", "why_how"),
        (r"explain (.+) including (.+)", "explain_include"),
    ]

    def __init__(
        self,
        llm_decomposer: Optional[Callable[[str], List[str]]] = None,
        use_llm: bool = False,
    ):
        """
        Initialize decomposer.

        Args:
            llm_decomposer: Optional LLM function for smart decomposition
            use_llm: Whether to use LLM for decomposition
        """
        self.llm_decomposer = llm_decomposer
        self.use_llm = use_llm and llm_decomposer is not None

    def decompose(self, query: str) -> List[SubQuery]:
        """
        Decompose a query into sub-queries.

        Args:
            query: Complex query

        Returns:
            List of SubQuery objects
        """
        query = query.strip()

        # Try LLM decomposition first
        if self.use_llm:
            return self._llm_decompose(query)

        # Fall back to rule-based decomposition
        return self._rule_decompose(query)

    def _rule_decompose(self, query: str) -> List[SubQuery]:
        """Rule-based query decomposition."""
        sub_queries = []

        # Check comparison patterns
        for pattern, qtype in self.COMPARISON_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                parts = [g for g in match.groups() if g]
                for part in parts:
                    sub_queries.append(
                        SubQuery(
                            query=part.strip(),
                            query_type="entity",
                            focus=part.strip(),
                        )
                    )
                # Add comparison query
                sub_queries.append(
                    SubQuery(
                        query=query,
                        query_type="comparison",
                        weight=1.2,  # Higher weight for original
                    )
                )
                return sub_queries

        # Check compound patterns
        for pattern, qtype in self.COMPOUND_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                parts = [g for g in match.groups() if g]
                for part in parts:
                    sub_queries.append(
                        SubQuery(
                            query=part.strip(),
                            query_type="factual",
                            focus=self._extract_focus(part),
                        )
                    )
                return sub_queries

        # Check multi-aspect patterns
        for pattern, qtype in self.MULTI_ASPECT_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                parts = [g for g in match.groups() if g]
                for i, part in enumerate(parts):
                    sub_queries.append(
                        SubQuery(
                            query=f"what is {part}" if i == 0 else f"how {part}",
                            query_type="conceptual" if i == 0 else "procedural",
                            focus=part.strip(),
                        )
                    )
                return sub_queries

        # No decomposition needed - return original
        return [
            SubQuery(
                query=query,
                query_type=self._classify_query(query),
                focus=self._extract_focus(query),
            )
        ]

    def _llm_decompose(self, query: str) -> List[SubQuery]:
        """LLM-based query decomposition."""
        try:
            sub_query_texts = self.llm_decomposer(query)
            return [
                SubQuery(
                    query=sq,
                    query_type="llm_generated",
                    focus=self._extract_focus(sq),
                )
                for sq in sub_query_texts
            ]
        except Exception as e:
            logger.warning(f"LLM decomposition failed: {e}, falling back to rules")
            return self._rule_decompose(query)

    def _classify_query(self, query: str) -> str:
        """Classify query type."""
        query_lower = query.lower()

        if query_lower.startswith(("how to", "how do", "how can")):
            return "procedural"
        elif query_lower.startswith(("what is", "what are", "define")):
            return "conceptual"
        elif query_lower.startswith(("why", "explain why")):
            return "explanatory"
        elif query_lower.startswith(("when", "where", "who")):
            return "factual"
        else:
            return "general"

    def _extract_focus(self, query: str) -> Optional[str]:
        """Extract key focus/entity from query."""
        # Remove common question words
        focus = re.sub(
            r"^(what|how|why|when|where|who|is|are|do|does|can|should)\s+",
            "",
            query.lower(),
            flags=re.IGNORECASE,
        )
        focus = re.sub(r"\?$", "", focus).strip()
        return focus if focus else None


class ReciprocalRankFusion:
    """
    Fuse results from multiple queries using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each query i where doc appears
    """

    def __init__(self, k: int = 60):
        """
        Initialize RRF.

        Args:
            k: Ranking constant (higher = less aggressive fusion)
        """
        self.k = k

    def fuse(
        self,
        query_results: Dict[str, List[Dict]],
        id_key: str = "source_path",
        score_key: str = "_distance",
    ) -> List[FusedResult]:
        """
        Fuse results from multiple queries.

        Args:
            query_results: Map of query -> results list
            id_key: Key for document ID
            score_key: Key for similarity score

        Returns:
            Fused and ranked results
        """
        # Track scores and metadata for each document
        doc_scores: Dict[str, float] = {}
        doc_queries: Dict[str, List[str]] = {}
        doc_ranks: Dict[str, Dict[str, int]] = {}
        doc_data: Dict[str, Dict] = {}

        for query, results in query_results.items():
            for rank, result in enumerate(results, 1):
                doc_id = result.get(id_key, str(rank))

                # Compute RRF score
                rrf_score = 1.0 / (self.k + rank)

                if doc_id not in doc_scores:
                    doc_scores[doc_id] = 0
                    doc_queries[doc_id] = []
                    doc_ranks[doc_id] = {}
                    doc_data[doc_id] = result

                doc_scores[doc_id] += rrf_score
                doc_queries[doc_id].append(query)
                doc_ranks[doc_id][query] = rank

        # Sort by fused score
        sorted_docs = sorted(
            doc_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        # Build fused results
        fused_results = []
        for doc_id, score in sorted_docs:
            data = doc_data[doc_id]
            fused_results.append(
                FusedResult(
                    content=data.get("text", ""),
                    source_path=doc_id,
                    fused_score=score,
                    contributing_queries=doc_queries[doc_id],
                    original_ranks=doc_ranks[doc_id],
                    metadata={k: v for k, v in data.items() if k not in {"text", id_key}},
                )
            )

        return fused_results


class MultiQuerySearcher:
    """
    Execute multi-query search with fusion.

    Process:
    1. Decompose complex query into sub-queries
    2. Execute each sub-query (parallel)
    3. Fuse results using RRF
    4. Deduplicate and rank
    """

    def __init__(
        self,
        searcher: Callable[[str, int], List[Dict]],
        decomposer: Optional[QueryDecomposer] = None,
        max_workers: int = 4,
        fusion_k: int = 60,
    ):
        """
        Initialize multi-query searcher.

        Args:
            searcher: Function to execute single query search
            decomposer: Query decomposer (default created if not provided)
            max_workers: Max parallel query threads
            fusion_k: RRF fusion constant
        """
        self.searcher = searcher
        self.decomposer = decomposer or QueryDecomposer()
        self.max_workers = max_workers
        self.fusion = ReciprocalRankFusion(k=fusion_k)

    def search(
        self,
        query: str,
        k: int = 10,
        per_query_k: int = 20,
        min_sub_queries: int = 1,
    ) -> MultiQueryResult:
        """
        Execute multi-query search.

        Args:
            query: Complex query
            k: Number of final results
            per_query_k: Results per sub-query
            min_sub_queries: Minimum sub-queries to use

        Returns:
            MultiQueryResult with fused results
        """
        # Decompose query
        sub_queries = self.decomposer.decompose(query)

        # Ensure minimum sub-queries
        if len(sub_queries) < min_sub_queries:
            # Add query variations
            sub_queries.extend(self._generate_variations(query))

        logger.info(f"Decomposed into {len(sub_queries)} sub-queries")

        # Execute sub-queries in parallel
        query_results: Dict[str, List[Dict]] = {}
        total_before = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.searcher, sq.query, per_query_k): sq for sq in sub_queries
            }

            for future in as_completed(futures):
                sq = futures[future]
                try:
                    results = future.result()
                    query_results[sq.query] = results
                    total_before += len(results)
                except Exception as e:
                    logger.warning(f"Sub-query failed '{sq.query}': {e}")

        # Fuse results
        fused = self.fusion.fuse(query_results)

        # Apply query weights (boost results matching weighted queries)
        weight_map = {sq.query: sq.weight for sq in sub_queries}
        for result in fused:
            boost = sum(weight_map.get(q, 1.0) - 1.0 for q in result.contributing_queries)
            result.fused_score *= 1 + boost * 0.1

        # Re-sort after weighting
        fused.sort(key=lambda x: x.fused_score, reverse=True)

        return MultiQueryResult(
            original_query=query,
            sub_queries=sub_queries,
            results=fused[:k],
            total_results_before_fusion=total_before,
            fusion_method="reciprocal_rank_fusion",
        )

    def _generate_variations(self, query: str) -> List[SubQuery]:
        """Generate query variations for diversity."""
        variations = []

        # Add focused version
        focus = self.decomposer._extract_focus(query)
        if focus and focus != query:
            variations.append(
                SubQuery(
                    query=focus,
                    query_type="focused",
                    weight=0.8,
                )
            )

        # Add question-form if not already
        if not query.endswith("?"):
            variations.append(
                SubQuery(
                    query=f"{query}?",
                    query_type="question",
                    weight=0.9,
                )
            )

        return variations


# Convenience function
def multi_query_search(
    query: str,
    searcher: Callable[[str, int], List[Dict]],
    k: int = 10,
) -> List[FusedResult]:
    """
    Quick multi-query search.

    Args:
        query: Complex query
        searcher: Search function
        k: Number of results

    Returns:
        Fused results
    """
    mqs = MultiQuerySearcher(searcher)
    result = mqs.search(query, k=k)
    return result.results


# Factory for LLM-powered decomposition
def create_llm_decomposer(
    backend: str = "ollama",
    model: str = "llama3.2:3b",
) -> Callable[[str], List[str]]:
    """
    Create LLM-powered query decomposer.

    Args:
        backend: LLM backend
        model: Model name

    Returns:
        Decomposer function
    """
    prompt_template = """Break this complex question into 2-4 simpler sub-questions that together would help answer the original. Return only the sub-questions, one per line.

Original question: {query}

Sub-questions:"""

    if backend == "ollama":
        import requests

        @with_retry(**RetryStrategies.ollama_call())
        def decompose(query: str) -> List[str]:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt_template.format(query=query),
                    "stream": False,
                    "options": {"num_predict": 200, "temperature": 0.3},
                },
                timeout=15,
            )
            response.raise_for_status()
            text = response.json().get("response", "")

            # Parse sub-questions
            lines = [
                line.strip().lstrip("0123456789.-) ")
                for line in text.strip().split("\n")
                if line.strip() and not line.strip().startswith("Sub-question")
            ]
            return [line for line in lines if len(line) > 10][:4]

        return decompose

    else:
        raise ValueError(f"Unknown backend: {backend}")
