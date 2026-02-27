"""Tests for the RAGAS-inspired RAG evaluator."""

from unittest.mock import AsyncMock

import pytest

from src.quality.rag_evaluator import EvaluationResult, RAGEvaluator


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="0.8")
    return provider


@pytest.fixture
def evaluator(mock_provider, tmp_path):
    return RAGEvaluator(llm_provider=mock_provider, eval_dir=tmp_path / "evals")


class TestRAGEvaluator:
    async def test_context_precision(self, evaluator):
        score = await evaluator.context_precision("what is RAG?", ["RAG stands for..."])
        assert 0.0 <= score <= 1.0

    async def test_context_precision_empty(self, evaluator):
        score = await evaluator.context_precision("query", [])
        assert score == 0.0

    async def test_context_recall(self, evaluator):
        contexts = ["Machine learning uses data to learn patterns."]
        gt = "Machine learning uses data patterns"
        score = await evaluator.context_recall("what is ML?", contexts, gt)
        assert score > 0.0

    async def test_faithfulness(self, evaluator):
        score = await evaluator.faithfulness(
            "RAG combines retrieval and generation",
            ["RAG uses retrieval to improve LLM answers"],
        )
        assert 0.0 <= score <= 1.0

    async def test_answer_relevancy(self, evaluator):
        score = await evaluator.answer_relevancy(
            "What is Python?",
            "Python is a programming language.",
        )
        assert 0.0 <= score <= 1.0

    async def test_full_evaluate(self, evaluator):
        result = await evaluator.evaluate(
            query="What is RAG?",
            contexts=["RAG combines retrieval and generation."],
            answer="RAG is a technique that uses search to augment LLM answers.",
            ground_truth="Retrieval-Augmented Generation",
        )
        assert isinstance(result, EvaluationResult)
        assert result.overall_score > 0

    async def test_save_result(self, evaluator, tmp_path):
        result = EvaluationResult(
            query="test",
            context_precision=0.8,
            context_recall=0.7,
            faithfulness=0.9,
            answer_relevancy=0.85,
        )
        result.compute_overall()
        path = evaluator.save_result(result)
        assert path.exists()

    def test_parse_score(self, evaluator):
        assert evaluator._parse_score("0.85") == 0.85
        assert evaluator._parse_score("Score: 0.7") == 0.7
        assert evaluator._parse_score("no number") == 0.5
        assert evaluator._parse_score("2.0") == 1.0  # Clamped

    def test_evaluation_result_overall(self):
        r = EvaluationResult(
            query="test",
            context_precision=1.0,
            context_recall=1.0,
            faithfulness=1.0,
            answer_relevancy=1.0,
        )
        r.compute_overall()
        assert r.overall_score == pytest.approx(1.0)
