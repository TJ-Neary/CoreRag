"""
RAG Evaluation Framework (RAGAS-inspired)

Provides metrics for evaluating retrieval and generation quality:
- Context Precision: Are retrieved contexts relevant?
- Context Recall: Did we find all relevant contexts?
- Faithfulness: Is the answer grounded in contexts?
- Answer Relevancy: Does the answer address the query?

Uses LLM-as-judge for evaluation. Results stored in ~/.corerag/evaluations/.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of a single evaluation run."""

    query: str
    context_precision: float = 0.0
    context_recall: float = 0.0
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    overall_score: float = 0.0
    details: dict = field(default_factory=dict)

    def compute_overall(self) -> None:
        """Compute weighted average of all metrics."""
        self.overall_score = (
            self.context_precision * 0.25
            + self.context_recall * 0.25
            + self.faithfulness * 0.30
            + self.answer_relevancy * 0.20
        )


PRECISION_PROMPT = """\
Given the query and retrieved context, rate how relevant the context is (0.0-1.0).
Query: {query}
Context: {context}
Score (0.0 = irrelevant, 1.0 = highly relevant):"""

FAITHFULNESS_PROMPT = """\
Given the answer and supporting contexts, rate if the answer is grounded in the contexts (0.0-1.0).
Answer: {answer}
Contexts: {contexts}
Score (0.0 = hallucinated, 1.0 = fully grounded):"""

RELEVANCY_PROMPT = """\
Given the query and answer, rate if the answer addresses the query (0.0-1.0).
Query: {query}
Answer: {answer}
Score (0.0 = off-topic, 1.0 = directly answers):"""


class RAGEvaluator:
    """Evaluates RAG pipeline quality using LLM-as-judge."""

    def __init__(self, llm_provider=None, eval_dir: Optional[Path] = None):
        self._provider = llm_provider
        from src.config import STATE_DIR

        self._eval_dir = eval_dir or STATE_DIR / "evaluations"
        self._eval_dir.mkdir(parents=True, exist_ok=True)

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_default_provider

            self._provider = get_default_provider()
        return self._provider

    async def context_precision(self, query: str, contexts: list[str]) -> float:
        """Rate how relevant retrieved contexts are to the query."""
        if not contexts:
            return 0.0

        scores = []
        for ctx in contexts[:5]:  # Limit to avoid excessive LLM calls
            prompt = PRECISION_PROMPT.format(query=query, context=ctx[:500])
            try:
                response = await self.provider.generate(prompt, max_tokens=10)
                score = self._parse_score(response)
                scores.append(score)
            except Exception:
                scores.append(0.5)  # Neutral default

        return sum(scores) / len(scores) if scores else 0.0

    async def context_recall(self, query: str, contexts: list[str], ground_truth: str) -> float:
        """Rate if contexts contain the information needed to answer."""
        if not contexts or not ground_truth:
            return 0.0

        combined = " ".join(c[:300] for c in contexts[:5])
        # Simple heuristic: what fraction of ground truth keywords appear in contexts
        gt_words = set(ground_truth.lower().split())
        ctx_words = set(combined.lower().split())
        if not gt_words:
            return 0.0

        overlap = len(gt_words & ctx_words)
        return min(overlap / max(len(gt_words) * 0.5, 1), 1.0)

    async def faithfulness(self, answer: str, contexts: list[str]) -> float:
        """Rate if the answer is grounded in the contexts."""
        if not answer or not contexts:
            return 0.0

        combined = "\n---\n".join(c[:500] for c in contexts[:5])
        prompt = FAITHFULNESS_PROMPT.format(answer=answer[:500], contexts=combined)

        try:
            response = await self.provider.generate(prompt, max_tokens=10)
            return self._parse_score(response)
        except Exception:
            return 0.5

    async def answer_relevancy(self, query: str, answer: str) -> float:
        """Rate if the answer addresses the query."""
        if not answer:
            return 0.0

        prompt = RELEVANCY_PROMPT.format(query=query, answer=answer[:500])
        try:
            response = await self.provider.generate(prompt, max_tokens=10)
            return self._parse_score(response)
        except Exception:
            return 0.5

    async def evaluate(
        self,
        query: str,
        contexts: list[str],
        answer: str,
        ground_truth: str = "",
    ) -> EvaluationResult:
        """Run all evaluation metrics."""
        result = EvaluationResult(query=query)

        result.context_precision = await self.context_precision(query, contexts)
        result.context_recall = await self.context_recall(query, contexts, ground_truth)
        result.faithfulness = await self.faithfulness(answer, contexts)
        result.answer_relevancy = await self.answer_relevancy(query, answer)
        result.compute_overall()

        return result

    def save_result(self, result: EvaluationResult) -> Path:
        """Save evaluation result to disk."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._eval_dir / f"eval_{timestamp}.json"
        path.write_text(
            json.dumps(
                {
                    "query": result.query,
                    "context_precision": result.context_precision,
                    "context_recall": result.context_recall,
                    "faithfulness": result.faithfulness,
                    "answer_relevancy": result.answer_relevancy,
                    "overall_score": result.overall_score,
                    "timestamp": timestamp,
                },
                indent=2,
            )
        )
        return path

    def _parse_score(self, response: str) -> float:
        """Extract a float score from LLM response."""
        import re

        match = re.search(r"(\d+\.?\d*)", response.strip())
        if match:
            score = float(match.group(1))
            return max(0.0, min(1.0, score))
        return 0.5
