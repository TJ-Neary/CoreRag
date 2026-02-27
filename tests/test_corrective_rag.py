"""Tests for Corrective RAG (CRAG) post-retrieval filtering."""

import pytest

from src.search.corrective_rag import CorrectiveRAG


@pytest.fixture
def crag():
    return CorrectiveRAG()


class TestCorrectiveRAG:
    def test_all_correct(self, crag):
        results = [{"content": f"chunk {i}"} for i in range(3)]
        scores = [0.9, 0.8, 0.75]
        cr = crag.filter_results("test query", results, reranker_scores=scores)
        assert cr.correct_count == 3
        assert cr.ambiguous_count == 0
        assert cr.incorrect_count == 0
        assert len(cr.results) == 3

    def test_mixed_classification(self, crag):
        results = [{"content": f"chunk {i}"} for i in range(4)]
        scores = [0.9, 0.5, 0.2, 0.1]
        cr = crag.filter_results("test", results, reranker_scores=scores)
        assert cr.correct_count == 1
        assert cr.ambiguous_count == 1
        assert cr.incorrect_count == 2
        assert len(cr.results) == 2

    def test_all_incorrect_fallback(self, crag):
        results = [{"content": f"chunk {i}"} for i in range(5)]
        scores = [0.1, 0.1, 0.05, 0.0, 0.1]
        cr = crag.filter_results("test", results, reranker_scores=scores)
        assert cr.all_filtered is True
        assert len(cr.results) == 3  # Fallback top-3
        assert all(r["crag_label"] == "fallback" for r in cr.results)

    def test_empty_results(self, crag):
        cr = crag.filter_results("test", [])
        assert cr.all_filtered is True
        assert len(cr.results) == 0

    def test_uses_dict_scores(self, crag):
        results = [
            {"content": "a", "score": 0.9},
            {"content": "b", "score": 0.1},
        ]
        cr = crag.filter_results("test", results)
        assert cr.correct_count == 1
        assert cr.incorrect_count == 1

    def test_labels_added_to_results(self, crag):
        results = [{"content": "a"}, {"content": "b"}]
        scores = [0.9, 0.5]
        cr = crag.filter_results("test", results, reranker_scores=scores)
        labels = [r["crag_label"] for r in cr.results]
        assert "correct" in labels
        assert "ambiguous" in labels

    def test_custom_thresholds(self):
        crag = CorrectiveRAG(correct_threshold=0.9, ambiguous_threshold=0.5)
        results = [{"content": "a"}]
        cr = crag.filter_results("test", results, reranker_scores=[0.8])
        assert cr.ambiguous_count == 1  # 0.8 < 0.9 but >= 0.5
