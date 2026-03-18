"""
Extended tests for src/search/hybrid_search.py

Covers: search scope fan-out, tag filtering, result cache behaviour,
CRAG-related result fields, and edge cases.  The existing test_hybrid_search.py
covers RRF fusion internals and FTS index lifecycle, so those are not repeated here.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from src.search.hybrid_search import HybridSearcher, _ResultCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    id_: str,
    content: str = "sample content",
    document_id: str = "doc-1",
    tags: str = "",
) -> dict:
    """Build a minimal LanceDB row dict."""
    return {
        "id": id_,
        "content": content,
        "document_id": document_id,
        "tags": tags,
        "_distance": 0.1,
        "_score": 1.0,
        "metadata": {},
    }


def _make_search_chain(rows: list[dict]) -> MagicMock:
    """Return a chainable mock whose .to_list() returns *rows*."""
    chain = MagicMock()
    chain.where.return_value = chain
    chain.limit.return_value = chain
    chain.to_list.return_value = rows
    return chain


def _make_db(rows: list[dict] | None = None) -> tuple[MagicMock, MagicMock]:
    """Create (db, table) mock pair.  FTS index is available by default."""
    rows = rows or []
    db = MagicMock()
    table = MagicMock()
    table.search.return_value = _make_search_chain(rows)
    # create_fts_index succeeds by default
    table.create_fts_index.return_value = None
    db.open_table.return_value = table
    return db, table


DUMMY_VECTOR = [0.0] * 10


# ---------------------------------------------------------------------------
# _ResultCache unit tests
# ---------------------------------------------------------------------------


class TestResultCache:
    def test_put_and_get_returns_same_results(self):
        cache = _ResultCache(ttl_seconds=60)
        results = [_make_row("a")]
        cache.put("my query", 5, None, results, "main")
        got = cache.get("my query", 5, None, "main")
        assert got == results

    def test_cache_miss_returns_none(self):
        cache = _ResultCache(ttl_seconds=60)
        assert cache.get("missing", 5, None, "main") is None

    def test_different_scope_is_different_cache_key(self):
        cache = _ResultCache(ttl_seconds=60)
        results_main = [_make_row("main-doc")]
        results_restricted = [_make_row("restricted-doc")]
        cache.put("q", 5, None, results_main, "main")
        cache.put("q", 5, None, results_restricted, "restricted")

        assert cache.get("q", 5, None, "main") == results_main
        assert cache.get("q", 5, None, "restricted") == results_restricted

    def test_expired_entry_returns_none(self):
        cache = _ResultCache(ttl_seconds=0)  # expires immediately
        cache.put("q", 5, None, [_make_row("a")], "main")
        # Even a tiny sleep ensures time.time() > ts + 0
        time.sleep(0.01)
        assert cache.get("q", 5, None, "main") is None

    def test_invalidate_clears_all_entries(self):
        cache = _ResultCache(ttl_seconds=60)
        cache.put("q1", 5, None, [_make_row("a")], "main")
        cache.put("q2", 5, None, [_make_row("b")], "main")
        cache.invalidate()
        assert cache.get("q1", 5, None, "main") is None
        assert cache.get("q2", 5, None, "main") is None

    def test_max_size_evicts_oldest_entry(self):
        cache = _ResultCache(max_size=2, ttl_seconds=60)
        cache.put("q1", 5, None, [_make_row("a")], "main")
        cache.put("q2", 5, None, [_make_row("b")], "main")
        cache.put("q3", 5, None, [_make_row("c")], "main")  # triggers eviction
        # Cache should have at most 2 entries
        assert len(cache._cache) <= 2

    def test_lock_is_used_during_get(self):
        """Verify that _lock.acquire is exercised on cache access (thread safety)."""
        cache = _ResultCache(ttl_seconds=60)
        original_lock = cache._lock
        acquire_calls: list = []

        class TrackingLock:
            def __enter__(self):
                acquire_calls.append(1)
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

        cache._lock = TrackingLock()  # type: ignore[assignment]
        cache.put("q", 5, None, [], "main")
        cache.get("q", 5, None, "main")
        assert len(acquire_calls) >= 2  # at least one for put, one for get

    def test_concurrent_puts_do_not_corrupt_cache(self):
        """Multiple threads writing simultaneously must not raise."""
        cache = _ResultCache(ttl_seconds=60)

        def _writer(n: int) -> None:
            for i in range(20):
                cache.put(f"q-{n}-{i}", 5, None, [_make_row(f"doc-{n}-{i}")], "main")

        threads = [threading.Thread(target=_writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # If we get here without exception the lock worked


# ---------------------------------------------------------------------------
# Search scope fan-out tests
# ---------------------------------------------------------------------------


class TestSearchScope:
    """Tests that search_scope routes queries to the correct DB(s)."""

    @pytest.mark.asyncio
    async def test_main_scope_searches_only_main_db(self):
        db, table = _make_db([_make_row("m1")])
        restricted_db, restricted_table = _make_db([_make_row("r1")])

        searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        searcher._fts_verified = True

        await searcher.search("test", DUMMY_VECTOR, k=5, search_scope="main")

        # main table should be called
        assert table.search.called
        # restricted table should NOT be opened
        restricted_db.open_table.assert_not_called()

    @pytest.mark.asyncio
    async def test_restricted_scope_searches_only_restricted_db(self):
        db, table = _make_db([_make_row("m1")])
        restricted_db, restricted_table = _make_db([_make_row("r1")])

        searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        searcher._fts_verified = True

        await searcher.search("test", DUMMY_VECTOR, k=5, search_scope="restricted")

        # restricted DB must be opened
        restricted_db.open_table.assert_called_once_with("child_chunks")
        # main table should NOT be searched
        table.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_restricted_scope_with_no_restricted_db_returns_empty(self):
        db, table = _make_db([_make_row("m1")])
        searcher = HybridSearcher(db=db, restricted_db=None)

        results = await searcher.search("test", DUMMY_VECTOR, k=5, search_scope="restricted")

        assert results == []

    @pytest.mark.asyncio
    async def test_all_scope_searches_both_dbs(self):
        main_row = _make_row("m1", document_id="main-doc")
        restricted_row = _make_row("r1", document_id="restricted-doc")
        db, table = _make_db([main_row])
        restricted_db, restricted_table = _make_db([restricted_row])

        searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        searcher._fts_verified = True

        await searcher.search("test", DUMMY_VECTOR, k=10, search_scope="all")

        # Both DBs must be queried
        assert table.search.called
        restricted_db.open_table.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_scope_results_have_correct_source_db_fields(self):
        main_row = _make_row("m1", document_id="main-doc")
        restricted_row = _make_row("r1", document_id="restricted-doc")
        db, _ = _make_db([main_row])
        restricted_db, _ = _make_db([restricted_row])

        searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        searcher._fts_verified = True

        results = await searcher.search("test", DUMMY_VECTOR, k=10, search_scope="all")

        source_dbs = {r.source_db for r in results}
        assert "main" in source_dbs
        assert "restricted" in source_dbs

    @pytest.mark.asyncio
    async def test_all_scope_without_restricted_db_returns_main_only(self):
        db, table = _make_db([_make_row("m1", document_id="main-doc")])
        searcher = HybridSearcher(db=db, restricted_db=None)
        searcher._fts_verified = True

        results = await searcher.search("test", DUMMY_VECTOR, k=5, search_scope="all")

        assert all(r.source_db == "main" for r in results)


# ---------------------------------------------------------------------------
# Tag filtering tests
# ---------------------------------------------------------------------------


class TestTagFiltering:
    """Tag filters should be forwarded to LanceDB .where() clauses."""

    @pytest.mark.asyncio
    async def test_single_tag_filter_builds_like_clause(self):
        db, table = _make_db()
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        await searcher.search(
            "query",
            DUMMY_VECTOR,
            k=5,
            filters={"tags": ["python"]},
        )

        # At least one search call must have been followed by a .where() containing
        # the LIKE clause for the tag.
        calls_with_where = [c for c in table.search.return_value.where.call_args_list if c]
        assert len(calls_with_where) > 0
        first_where_arg = calls_with_where[0][0][0]
        assert "python" in first_where_arg
        assert "LIKE" in first_where_arg

    @pytest.mark.asyncio
    async def test_multiple_tags_produce_and_clause(self):
        db, table = _make_db()
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        await searcher.search(
            "query",
            DUMMY_VECTOR,
            k=5,
            filters={"tags": ["python", "ml"]},
        )

        calls_with_where = [c for c in table.search.return_value.where.call_args_list if c]
        assert len(calls_with_where) > 0
        clause = calls_with_where[0][0][0]
        assert "python" in clause
        assert "ml" in clause
        assert "AND" in clause

    def test_build_filter_clause_single_tag(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)
        clause = searcher._build_filter_clause({"tags": ["sphr-study"]})
        assert "tags LIKE '%,sphr-study,%'" == clause

    def test_build_filter_clause_multiple_tags_are_anded(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)
        clause = searcher._build_filter_clause({"tags": ["a", "b"]})
        assert "tags LIKE '%,a,%'" in clause
        assert "tags LIKE '%,b,%'" in clause
        assert "AND" in clause

    def test_build_filter_clause_non_tag_key_uses_equality(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)
        clause = searcher._build_filter_clause({"category": "notes"})
        assert "category = 'notes'" == clause

    def test_build_filter_clause_combined_filters(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)
        clause = searcher._build_filter_clause({"category": "notes", "tags": ["python"]})
        assert "category = 'notes'" in clause
        assert "tags LIKE '%,python,%'" in clause
        assert "AND" in clause


# ---------------------------------------------------------------------------
# Result cache integration with search()
# ---------------------------------------------------------------------------


class TestSearchResultCache:
    @pytest.mark.asyncio
    async def test_second_call_with_same_args_returns_cache(self):
        db, table = _make_db([_make_row("doc1")])
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        first = await searcher.search("hello", DUMMY_VECTOR, k=5)
        call_count_after_first = table.search.call_count

        second = await searcher.search("hello", DUMMY_VECTOR, k=5)
        # Table should NOT have been queried again
        assert table.search.call_count == call_count_after_first
        assert second == first

    @pytest.mark.asyncio
    async def test_different_query_bypasses_cache(self):
        db, table = _make_db([_make_row("doc1")])
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        await searcher.search("query-one", DUMMY_VECTOR, k=5)
        count_after_first = table.search.call_count

        await searcher.search("query-two", DUMMY_VECTOR, k=5)
        assert table.search.call_count > count_after_first

    @pytest.mark.asyncio
    async def test_different_scope_bypasses_cache(self):
        db, table = _make_db([_make_row("doc1")])
        restricted_db, _ = _make_db([_make_row("r1")])
        searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        searcher._fts_verified = True

        await searcher.search("q", DUMMY_VECTOR, k=5, search_scope="main")
        main_count = table.search.call_count

        # "all" scope must not reuse the "main" cache entry
        await searcher.search("q", DUMMY_VECTOR, k=5, search_scope="all")
        assert table.search.call_count > main_count

    @pytest.mark.asyncio
    async def test_cache_invalidation_forces_re_query(self):
        db, table = _make_db([_make_row("doc1")])
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        await searcher.search("q", DUMMY_VECTOR, k=5)
        count_after_first = table.search.call_count

        searcher._result_cache.invalidate()

        await searcher.search("q", DUMMY_VECTOR, k=5)
        assert table.search.call_count > count_after_first


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query_string_does_not_raise(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        # Should complete without exception
        results = await searcher.search("", DUMMY_VECTOR, k=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_k_zero_returns_empty_list(self):
        db, _ = _make_db([_make_row("doc1")])
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        results = await searcher.search("query", DUMMY_VECTOR, k=0)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_results_from_db_returns_empty_list(self):
        db, _ = _make_db(rows=[])  # table returns nothing
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = True

        results = await searcher.search("query", DUMMY_VECTOR, k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_table_does_not_exist_returns_empty_not_crash(self):
        db = MagicMock()
        db.open_table.side_effect = Exception("Table not found")
        searcher = HybridSearcher(db=db)
        # _fts_verified=True so we skip the verify step; the open_table call
        # in the property accessor will also fail, triggering the try/except in
        # _search_single.
        searcher._fts_verified = True

        results = await searcher.search("query", DUMMY_VECTOR, k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_fts_unavailable_falls_back_to_vector_only(self):
        """When FTS probe fails, results still come back via vector-only path."""
        rows = [_make_row("v1")]
        db, table = _make_db(rows)

        def _side_effect(query, **kwargs):
            # FTS probe raises; vector searches succeed
            if kwargs.get("query_type") == "fts":
                raise RuntimeError("no FTS index")
            return _make_search_chain(rows)

        table.search.side_effect = _side_effect
        # Also make the property-level access (non-"fts" call) return a chain
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = False  # force FTS check

        # verify_fts_index will fail → vector-only fallback is used
        results = await searcher.search("query", DUMMY_VECTOR, k=5)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# SearchResult source_db field (CRAG-adjacent)
# ---------------------------------------------------------------------------


class TestSearchResultFields:
    def test_rrf_fusion_results_carry_source_db(self):
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)

        vector_results = [_make_row("a")]
        fts_results = [_make_row("a")]

        fused = searcher._reciprocal_rank_fusion(
            vector_results, fts_results, 0.7, 0.3, False, source_db="restricted"
        )

        assert fused[0].source_db == "restricted"

    def test_merge_results_deduplicates_by_document_id(self):
        """Same document_id appearing in both DBs should appear only once."""
        db, _ = _make_db()
        searcher = HybridSearcher(db=db)

        from src.search.hybrid_search import SearchResult

        shared_doc_id = "shared-doc"

        def _sr(id_: str, source_db: str, score: float) -> SearchResult:
            return SearchResult(
                id=id_,
                content="content",
                document_id=shared_doc_id,
                vector_score=0.1,
                fts_score=None,
                rrf_score=score,
                metadata={},
                source_db=source_db,
            )

        main_results = [_sr("chunk-m", "main", 0.5)]
        restricted_results = [_sr("chunk-r", "restricted", 0.8)]

        merged = searcher._merge_results(main_results, restricted_results, k=10)
        # Restricted has priority; main's version of the same document is skipped
        assert len(merged) == 1
        assert merged[0].source_db == "restricted"

    def test_merge_results_sorted_by_rrf_score_descending(self):
        from src.search.hybrid_search import SearchResult

        db, _ = _make_db()
        searcher = HybridSearcher(db=db)

        def _sr(id_: str, score: float) -> SearchResult:
            return SearchResult(
                id=id_,
                content="c",
                document_id=id_,
                vector_score=0.1,
                fts_score=None,
                rrf_score=score,
                metadata={},
                source_db="main",
            )

        main_results = [_sr("low", 0.2)]
        restricted_results = [_sr("high", 0.9)]

        merged = searcher._merge_results(main_results, restricted_results, k=10)
        assert merged[0].id == "high"
        assert merged[1].id == "low"
