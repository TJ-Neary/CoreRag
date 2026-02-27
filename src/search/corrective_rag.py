"""
Corrective RAG (CRAG)

Post-retrieval relevance filtering that classifies each retrieved chunk as
Correct / Ambiguous / Incorrect based on reranker scores. Removes irrelevant
results before they reach answer synthesis.

Three-tier classification:
- Correct (score > 0.7): high confidence match, keep as-is
- Ambiguous (0.3-0.7): uncertain, keep but flag for cautious use
- Incorrect (< 0.3): likely irrelevant, filter out

If all results are filtered, returns top-3 with a warning flag.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CRAGResult:
    """Result of corrective RAG filtering."""

    results: list[dict[str, Any]]
    correct_count: int = 0
    ambiguous_count: int = 0
    incorrect_count: int = 0
    all_filtered: bool = False


class CorrectiveRAG:
    """Post-retrieval relevance filter using reranker scores."""

    def __init__(
        self,
        correct_threshold: float = 0.7,
        ambiguous_threshold: float = 0.3,
    ):
        self.correct_threshold = correct_threshold
        self.ambiguous_threshold = ambiguous_threshold

    def filter_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        reranker_scores: list[float] | None = None,
    ) -> CRAGResult:
        """Filter search results by relevance classification.

        Args:
            query: Original search query.
            results: Search results (dicts with at least 'content').
            reranker_scores: Cross-encoder scores per result. If None,
                uses 'reranker_score' or 'score' from result dicts.

        Returns:
            CRAGResult with filtered results and counts.
        """
        if not results:
            return CRAGResult(results=[], all_filtered=True)

        scores = reranker_scores or [
            r.get("reranker_score", r.get("score", r.get("rrf_score", 0.5))) for r in results
        ]

        correct = []
        ambiguous = []
        correct_count = 0
        ambiguous_count = 0
        incorrect_count = 0

        for result, score in zip(results, scores):
            if score > self.correct_threshold:
                result["crag_label"] = "correct"
                correct.append(result)
                correct_count += 1
            elif score >= self.ambiguous_threshold:
                result["crag_label"] = "ambiguous"
                ambiguous.append(result)
                ambiguous_count += 1
            else:
                result["crag_label"] = "incorrect"
                incorrect_count += 1

        filtered = correct + ambiguous

        # Safety fallback: if everything was filtered, return top 3
        if not filtered:
            logger.warning(
                f"CRAG: all {len(results)} results filtered for query '{query[:80]}', "
                "returning top-3 as fallback"
            )
            fallback = results[:3]
            for r in fallback:
                r["crag_label"] = "fallback"
            return CRAGResult(
                results=fallback,
                correct_count=0,
                ambiguous_count=0,
                incorrect_count=incorrect_count,
                all_filtered=True,
            )

        logger.info(
            f"CRAG: {correct_count} correct, {ambiguous_count} ambiguous, "
            f"{incorrect_count} filtered for '{query[:60]}'"
        )

        return CRAGResult(
            results=filtered,
            correct_count=correct_count,
            ambiguous_count=ambiguous_count,
            incorrect_count=incorrect_count,
        )
