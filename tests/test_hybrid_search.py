"""Tests for src/search/hybrid_search.py — RRF fusion, FTS lifecycle, fallback."""

from unittest.mock import MagicMock

import pytest

from src.search.hybrid_search import HybridSearcher


@pytest.fixture
def mock_db():
    """Create a mock LanceDB connection with a chainable table."""
    db = MagicMock()
    table = MagicMock()

    search_chain = MagicMock()
    search_chain.where.return_value = search_chain
    search_chain.limit.return_value = search_chain
    search_chain.to_list.return_value = []
    table.search.return_value = search_chain

    db.open_table.return_value = table
    return db, table


class TestEnsureFtsIndex:
    def test_success(self, mock_db):
        db, table = mock_db
        searcher = HybridSearcher(db=db)
        result = searcher.ensure_fts_index()
        assert result is True
        assert searcher._fts_verified is True
        table.create_fts_index.assert_called_once()

    def test_already_exists(self, mock_db):
        db, table = mock_db
        table.create_fts_index.side_effect = Exception("index already exists for column")
        searcher = HybridSearcher(db=db)
        result = searcher.ensure_fts_index()
        assert result is True

    def test_real_failure(self, mock_db):
        db, table = mock_db
        table.create_fts_index.side_effect = RuntimeError("corrupt index file")
        searcher = HybridSearcher(db=db)
        result = searcher.ensure_fts_index()
        assert result is False


class TestRRFFusion:
    def test_doc_in_both_results(self, mock_db):
        """Document in both vector and FTS gets combined RRF score."""
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        vector_results = [
            {
                "id": "a",
                "content": "test",
                "document_id": "d1",
                "_distance": 0.1,
                "source_path": "f.txt",
                "parent_id": "p1",
                "chunk_index": 0,
                "tags": "",
            },
        ]
        fts_results = [
            {
                "id": "a",
                "content": "test",
                "document_id": "d1",
                "_score": 5.0,
                "source_path": "f.txt",
                "parent_id": "p1",
                "chunk_index": 0,
                "tags": "",
            },
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results,
            fts_results,
            vector_weight=0.7,
            fts_weight=0.3,
            debug=False,
        )

        assert len(fused) == 1
        # Rank 1 in both: 0.7/(60+1) + 0.3/(60+1) = 1.0/61
        assert fused[0].rrf_score == pytest.approx(1.0 / 61, rel=1e-3)

    def test_doc_in_vector_only(self, mock_db):
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        vector_results = [
            {
                "id": "a",
                "content": "test",
                "document_id": "d1",
                "_distance": 0.1,
                "source_path": "f.txt",
                "parent_id": "p1",
                "chunk_index": 0,
                "tags": "",
            },
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results,
            [],
            vector_weight=0.7,
            fts_weight=0.3,
            debug=False,
        )

        assert len(fused) == 1
        assert fused[0].rrf_score == pytest.approx(0.7 / 61, rel=1e-3)

    def test_ordering_by_rrf_score(self, mock_db):
        """Results sorted descending by RRF score."""
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        # "a" is rank 1 vector-only, "b" is rank 2 vector + rank 1 FTS
        vector_results = [
            {
                "id": "a",
                "content": "low",
                "document_id": "d1",
                "_distance": 0.9,
                "source_path": "f.txt",
                "parent_id": "p1",
                "chunk_index": 0,
                "tags": "",
            },
            {
                "id": "b",
                "content": "high",
                "document_id": "d2",
                "_distance": 0.1,
                "source_path": "g.txt",
                "parent_id": "p2",
                "chunk_index": 0,
                "tags": "",
            },
        ]
        fts_results = [
            {
                "id": "b",
                "content": "high",
                "document_id": "d2",
                "_score": 10.0,
                "source_path": "g.txt",
                "parent_id": "p2",
                "chunk_index": 0,
                "tags": "",
            },
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results,
            fts_results,
            vector_weight=0.7,
            fts_weight=0.3,
            debug=False,
        )

        assert fused[0].id == "b"  # b in both → higher score
        assert fused[1].id == "a"

    def test_empty_inputs(self, mock_db):
        db, _ = mock_db
        searcher = HybridSearcher(db=db)
        fused = searcher._reciprocal_rank_fusion([], [], 0.7, 0.3, False)
        assert fused == []
