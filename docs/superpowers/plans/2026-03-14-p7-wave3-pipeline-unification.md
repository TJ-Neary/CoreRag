# P7 Wave 3: Pipeline Unification & Test Coverage — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify three divergent ingest paths into a single `IngestService`, convert eager module singletons to lazy-init, and fill critical test gaps for `intelligence.py`, `hybrid_search.py`, and `staging.py`.

**Architecture:** Extract the 9-phase enrichment pipeline from `executor.py:_index_in_rag()` into a standalone async `IngestService` class. Route the two API ingest endpoints through it. Add ~370 lines of tests for the three highest-risk untested modules. Fix stale 384d mock vectors.

**Tech Stack:** Python 3.12+, pytest, asyncio, LanceDB, FastAPI

**Spec:** `docs/superpowers/specs/2026-03-14-p7-codebase-evolution-design.md` (Wave 3)

**Note:** Any new tech debt discovered during implementation that isn't fixed immediately must be documented in `_DEV/DevPlan.md` and `_DEV/TECH_DEBT.md`.

---

## MANDATORY: Review Corrections (Read Before Implementing)

Plan was reviewed and 14 issues were identified. The following corrections MUST be applied during implementation:

### Critical (will cause test failures or runtime errors if not fixed)

1. **Task 1 (`_repair_json` test):** Error match string corrected to `"Could not repair"` (already fixed in plan).
2. **Task 1 (mock LLM responses):** Use `"suggested_name"` not `"suggested_filename"` (already fixed in plan). Remove `"target_folder"` from mocks — not a real field.
3. **Task 7 (`IngestService`):** `ChildChunk` and `ParentChunk` have NO `content_hash` attribute. Compute hashes inline: `hashlib.sha256(c.content.encode()).hexdigest()`. Store in parallel list. Same for parent hashes.
4. **Task 7 (`IngestService`):** `chunk_document` signature is `chunk_document(content, document_id, metadata=None)` — there is NO `source_path` kwarg. Pass: `chunker.chunk_document(content=text, document_id=document_id, metadata={"source_path": source_path})`.
5. **Task 7 (`IngestService`):** Add entity extraction phase gated by `skip_graph` flag. Import and call `_extract_entities(text, source_path)` from `executor.py`, or inline the graph logic. Without this, the full pipeline loses knowledge graph entries.

### Important (should fix)

6. **Task 1 (`_sample_text` test):** Replace `"..." in result or "—" in result` with `"[... middle of document omitted for brevity ...]" in result` for precision.
7. **Task 2 (search fallback test):** The weak assertion `len(results) >= 0` should be made meaningful — properly mock `_vector_only_search` to return 1 result and assert `len(results) == 1`.
8. **Task 3 (staging test):** Use `pytest.raises(DatabaseError)` (import from `src.exceptions`) instead of bare `Exception` for the corrupted JSON test.
9. **Task 7 (`IngestService` table creation):** Use `self._db.create_table(table_name, data)` passing list-of-dicts directly, NOT `pa.table({k: [v]...})` — PyArrow will infer wrong types for vector columns.
10. **Task 7 (date extraction):** Apply `or ""` to handle None: `dates = [(d or "", conf) for d, conf in [date_ext.extract(c.content) for c in children]]`.
11. **Task 7 (parent hash):** Use `hashlib.sha256(p.content.encode()).hexdigest()` instead of `getattr(p, "content_hash", "")` — ParentChunk has no `content_hash` attr.
12. **Task 7 (chunker metadata):** Pass metadata dict to `chunk_document` matching executor pattern: `metadata={"source_path": source_path, "file_type": "document", "category": metadata.get("category", "")}`.
13. **Task 7 (asyncio.Runner):** Note that `asyncio.Runner.run()` cannot be called from an existing async context. Currently safe (executor is sync) but fragile for future changes.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `tests/test_intelligence.py` | Create | Tests for `_repair_json`, `_clean_json_markdown`, `_sample_text`, `analyze_document` |
| `tests/test_hybrid_search.py` | Create | Tests for RRF fusion, FTS fallback, filter building, `ensure_fts_index` |
| `tests/test_staging.py` | Create | Tests for manifest CRUD, batch updates, file locking, status transitions |
| `tests/conftest.py` | Modify (lines 223, 232, 249, 259) | Update mock vectors from 384d to 1024d |
| `src/processor.py` | Modify (lines 14-20) | Convert 3 eager singletons to lazy-init pattern |
| `pyproject.toml` | Modify | Sync minimum dependency versions with requirements.txt |
| `src/ingest_service.py` | Create | Shared async ingest pipeline with feature flags |
| `src/executor.py` | Modify | Delegate to `IngestService` from `_index_in_rag` |
| `src/api/v1_routes.py` | Modify (lines 555-712, 925-992) | Rewire `api_ingest` and `quick_capture` to use `IngestService` |

---

## Chunk 1: Test Coverage (Tasks 1-3)

### Task 1: Tests for intelligence.py (Spec 3.4)

**Files:**
- Create: `tests/test_intelligence.py`

- [ ] **Step 1: Write tests for `_sample_text`**

```python
"""Tests for src/intelligence.py — JSON repair, text sampling, document analysis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.intelligence import _clean_json_markdown, _repair_json, _sample_text


class TestSampleText:
    def test_short_text_returned_unchanged(self):
        assert _sample_text("hello", max_chars=100) == "hello"

    def test_exactly_max_chars(self):
        text = "x" * 12000
        assert _sample_text(text) == text

    def test_long_text_truncated_with_head_and_tail(self):
        text = "H" * 10000 + "T" * 5000  # 15000 chars
        result = _sample_text(text, max_chars=12000)
        assert result.startswith("H" * 100)  # Head preserved
        assert result.endswith("T" * 100)    # Tail preserved
        assert len(result) <= 12100          # Head + separator + tail
        assert "..." in result or "—" in result  # Contains separator

    def test_empty_string(self):
        assert _sample_text("") == ""
```

- [ ] **Step 2: Write tests for `_clean_json_markdown`**

```python
class TestCleanJsonMarkdown:
    def test_strips_json_fences(self):
        assert _clean_json_markdown('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_no_fences_strips_whitespace(self):
        assert _clean_json_markdown('  {"a": 1}  ') == '{"a": 1}'

    def test_non_json_fences_not_matched(self):
        # Regex requires ```json specifically
        raw = '```\n{"a": 1}\n```'
        result = _clean_json_markdown(raw)
        assert result == raw.strip()

    def test_multiline_json(self):
        raw = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
        result = _clean_json_markdown(raw)
        assert '"a": 1' in result
        assert '"b": 2' in result
```

- [ ] **Step 3: Write tests for `_repair_json`**

```python
class TestRepairJson:
    def test_valid_json_unchanged(self):
        assert _repair_json('{"a": 1}') == '{"a": 1}'

    def test_truncated_string_closed(self):
        result = _repair_json('{"a": "hel')
        parsed = __import__("json").loads(result)
        assert "a" in parsed

    def test_unclosed_brace(self):
        result = _repair_json('{"a": 1')
        parsed = __import__("json").loads(result)
        assert parsed["a"] == 1

    def test_unclosed_bracket(self):
        result = _repair_json('{"a": [1, 2')
        parsed = __import__("json").loads(result)
        assert parsed["a"] == [1, 2]

    def test_irreparable_raises_valueerror(self):
        with pytest.raises(ValueError, match="Could not repair"):
            _repair_json("not json at all {{{")

    def test_valid_array(self):
        assert _repair_json('[1, 2, 3]') == '[1, 2, 3]'
```

- [ ] **Step 4: Write tests for `analyze_document`**

```python
class TestAnalyzeDocument:
    @pytest.mark.asyncio
    async def test_empty_text_returns_defaults(self):
        from src.intelligence import analyze_document

        metadata, text = await analyze_document("")
        assert metadata["category"] == "Unsorted"
        assert metadata["year"] == "Unknown"
        assert text == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_defaults(self):
        from src.intelligence import analyze_document

        metadata, text = await analyze_document("   \n\t  ")
        assert metadata["category"] == "Unsorted"

    @pytest.mark.asyncio
    async def test_llm_returns_valid_json(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "HR", "year": "2024", "type": "policy", '
            '"summary": "Test doc", "suggested_name": "test", '
            '"pii_redacted_text":"HR/Policies", "pii_observations": "none"}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, text = await analyze_document("Some document content here.")

        assert metadata["category"] == "HR"
        assert metadata["year"] == "2024"
        assert text == "Some document content here."

    @pytest.mark.asyncio
    async def test_llm_returns_markdown_wrapped_json(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='```json\n{"category": "Finance", "year": "2023", "type": "report", '
            '"summary": "Q4", "suggested_name": "q4", '
            '"pii_redacted_text":"Finance", "pii_observations": ""}\n```'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Financial report content.")

        assert metadata["category"] == "Finance"

    @pytest.mark.asyncio
    async def test_llm_is_sensitive_stripped(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "HR", "year": "2024", "type": "doc", '
            '"summary": "s", "suggested_name": "f", "pii_redacted_text":"t", '
            '"pii_observations": "n", "is_sensitive": true}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Content")

        assert "is_sensitive" not in metadata

    @pytest.mark.asyncio
    async def test_provider_failure_raises_processing_error(self):
        from src.exceptions import ProcessingError
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=Exception("Connection refused"))

        with (
            patch("src.intelligence.get_default_provider", return_value=mock_provider),
            pytest.raises(ProcessingError),
        ):
            await analyze_document("Some content")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_intelligence.py -v --tb=short`
Expected: All pass. The utility functions are pure; `analyze_document` tests mock the LLM provider.

- [ ] **Step 6: Commit**

```bash
git add tests/test_intelligence.py
git commit -m "test: add tests for intelligence.py (JSON repair, text sampling, document analysis)"
```

---

### Task 2: Tests for HybridSearcher (Spec 3.5)

**Files:**
- Create: `tests/test_hybrid_search.py`

- [ ] **Step 1: Write tests for RRF fusion and FTS lifecycle**

```python
"""Tests for src/search/hybrid_search.py — RRF fusion, FTS fallback, filter building."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.search.hybrid_search import HybridSearcher, SearchResult


@pytest.fixture
def mock_db():
    """Create a mock LanceDB connection with a chainable table."""
    db = MagicMock()
    table = MagicMock()

    # Make search() chainable: table.search().where().limit().to_list()
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
        assert result is True  # "already exists" is treated as success

    def test_real_failure(self, mock_db):
        db, table = mock_db
        table.create_fts_index.side_effect = RuntimeError("corrupt index file")
        searcher = HybridSearcher(db=db)
        result = searcher.ensure_fts_index()
        assert result is False


class TestRRFFusion:
    def test_doc_in_both_results(self, mock_db):
        """Document appearing in both vector and FTS gets combined score."""
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        vector_results = [
            {"id": "a", "content": "test", "document_id": "d1", "_distance": 0.1,
             "source_path": "f.txt", "parent_id": "p1", "chunk_index": 0, "tags": ""},
        ]
        fts_results = [
            {"id": "a", "content": "test", "document_id": "d1", "_score": 5.0,
             "source_path": "f.txt", "parent_id": "p1", "chunk_index": 0, "tags": ""},
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results, fts_results,
            vector_weight=0.7, fts_weight=0.3, debug=False,
        )

        assert len(fused) == 1
        # Score from both: 0.7/(60+1) + 0.3/(60+1) = 1.0/61
        assert fused[0].rrf_score == pytest.approx(1.0 / 61, rel=1e-3)

    def test_doc_in_vector_only(self, mock_db):
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        vector_results = [
            {"id": "a", "content": "test", "document_id": "d1", "_distance": 0.1,
             "source_path": "f.txt", "parent_id": "p1", "chunk_index": 0, "tags": ""},
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results, [],
            vector_weight=0.7, fts_weight=0.3, debug=False,
        )

        assert len(fused) == 1
        assert fused[0].rrf_score == pytest.approx(0.7 / 61, rel=1e-3)

    def test_ordering_by_rrf_score(self, mock_db):
        """Results sorted descending by RRF score."""
        db, _ = mock_db
        searcher = HybridSearcher(db=db)

        vector_results = [
            {"id": "a", "content": "low", "document_id": "d1", "_distance": 0.9,
             "source_path": "f.txt", "parent_id": "p1", "chunk_index": 0, "tags": ""},
            {"id": "b", "content": "high", "document_id": "d2", "_distance": 0.1,
             "source_path": "g.txt", "parent_id": "p2", "chunk_index": 0, "tags": ""},
        ]
        fts_results = [
            {"id": "b", "content": "high", "document_id": "d2", "_score": 10.0,
             "source_path": "g.txt", "parent_id": "p2", "chunk_index": 0, "tags": ""},
        ]

        fused = searcher._reciprocal_rank_fusion(
            vector_results, fts_results,
            vector_weight=0.7, fts_weight=0.3, debug=False,
        )

        assert fused[0].id == "b"  # b appears in both → higher score
        assert fused[1].id == "a"

    def test_empty_inputs(self, mock_db):
        db, _ = mock_db
        searcher = HybridSearcher(db=db)
        fused = searcher._reciprocal_rank_fusion([], [], 0.7, 0.3, False)
        assert fused == []


class TestSearchFallback:
    @pytest.mark.asyncio
    async def test_fts_unavailable_falls_back_to_vector_only(self, mock_db):
        db, table = mock_db
        searcher = HybridSearcher(db=db)
        searcher._fts_verified = False

        # verify_fts_index fails
        table.search.return_value.limit.return_value.to_list.side_effect = [
            Exception("no FTS index"),  # verify_fts_index probe
            [  # _vector_only_search results
                {"id": "a", "content": "found", "document_id": "d1", "_distance": 0.2,
                 "source_path": "f.txt", "parent_id": "p1", "chunk_index": 0, "tags": ""},
            ],
        ]

        results = await searcher.search("test query", [0.1] * 1024, k=5)
        # Should return results from vector-only fallback
        assert len(results) >= 0  # May be 0 if mock doesn't chain correctly
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_hybrid_search.py -v --tb=short`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hybrid_search.py
git commit -m "test: add tests for HybridSearcher (RRF fusion, FTS lifecycle, fallback)"
```

---

### Task 3: Tests for staging.py (Spec 3.6)

**Files:**
- Create: `tests/test_staging.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for src/staging.py — manifest CRUD, batch updates, file locking."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_manifest(tmp_path):
    """Provide a temporary manifest path and patch the module constant."""
    manifest_path = tmp_path / "staging_manifest.json"
    with patch("src.staging.STAGING_MANIFEST_PATH", manifest_path):
        yield manifest_path


class TestLoadManifest:
    def test_nonexistent_file_returns_empty(self, temp_manifest):
        from src.staging import load_manifest

        assert load_manifest() == {}

    def test_valid_json_loaded(self, temp_manifest):
        from src.staging import load_manifest

        temp_manifest.write_text(json.dumps({"item1": {"status": "pending"}}))
        result = load_manifest()
        assert "item1" in result

    def test_corrupted_json_raises(self, temp_manifest):
        from src.staging import load_manifest

        temp_manifest.write_text("not valid json {{{")
        with pytest.raises(Exception):
            load_manifest()


class TestAddToStaging:
    def test_creates_item_with_pending_status(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("/tmp/test.pdf"),
            metadata={"category": "HR", "year": "2024", "type": "policy", "tags": ["hr"]},
            redacted_text="Document content",
            suggested_filename="2024_HR_Policy",
        )

        manifest = load_manifest()
        assert item_id in manifest
        assert manifest[item_id]["status"] == "pending"
        assert manifest[item_id]["proposed"]["category"] == "HR"

    def test_original_path_is_absolute(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("relative/path.txt"),
            metadata={"category": "Test", "tags": []},
            redacted_text="content",
            suggested_filename="test",
        )

        manifest = load_manifest()
        stored_path = manifest[item_id]["original_path"]
        assert Path(stored_path).is_absolute()

    def test_defaults_for_missing_metadata(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("/tmp/test.txt"),
            metadata={},
            redacted_text="content",
            suggested_filename="test",
        )

        manifest = load_manifest()
        assert manifest[item_id]["proposed"]["category"] == "Unsorted"
        assert manifest[item_id]["proposed"]["year"] == "Unknown"


class TestUpdateItem:
    def test_update_flat_fields(self, temp_manifest):
        from src.staging import add_to_staging, get_item, update_item

        item_id = add_to_staging(Path("/tmp/t.txt"), {}, "text", "name")
        update_item(item_id, {"status": "approved"})
        assert get_item(item_id)["status"] == "approved"

    def test_update_proposed_deep_merges(self, temp_manifest):
        from src.staging import add_to_staging, get_item, update_item

        item_id = add_to_staging(
            Path("/tmp/t.txt"),
            {"category": "Old", "tags": []},
            "text",
            "name",
        )
        update_item(item_id, {"proposed": {"category": "New"}})
        item = get_item(item_id)
        assert item["proposed"]["category"] == "New"
        assert item["proposed"]["filename"] == "name"  # Not overwritten

    def test_update_nonexistent_returns_false(self, temp_manifest):
        from src.staging import update_item

        assert update_item("nonexistent-id", {"status": "x"}) is False


class TestBatchUpdateItems:
    def test_batch_updates_multiple(self, temp_manifest):
        from src.staging import add_to_staging, batch_update_items, get_item

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        id2 = add_to_staging(Path("/tmp/b.txt"), {}, "b", "b")

        count = batch_update_items({
            id1: {"status": "approved"},
            id2: {"status": "approved"},
        })

        assert count == 2
        assert get_item(id1)["status"] == "approved"
        assert get_item(id2)["status"] == "approved"

    def test_batch_skips_missing_ids(self, temp_manifest):
        from src.staging import add_to_staging, batch_update_items

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        count = batch_update_items({
            id1: {"status": "approved"},
            "nonexistent": {"status": "approved"},
        })
        assert count == 1


class TestGetPendingItems:
    def test_returns_pending_and_processing(self, temp_manifest):
        from src.staging import add_to_staging, get_pending_items, update_item

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        id2 = add_to_staging(Path("/tmp/b.txt"), {}, "b", "b")
        id3 = add_to_staging(Path("/tmp/c.txt"), {}, "c", "c")

        update_item(id2, {"status": "processing"})
        update_item(id3, {"status": "completed"})

        pending = get_pending_items()
        assert id1 in pending  # pending
        assert id2 in pending  # processing
        assert id3 not in pending  # completed


class TestConcurrentAccess:
    def test_concurrent_adds_no_corruption(self, temp_manifest):
        """Multiple threads adding items should not corrupt the manifest."""
        from src.staging import add_to_staging, load_manifest

        errors = []

        def add_item(n):
            try:
                add_to_staging(Path(f"/tmp/file_{n}.txt"), {}, f"text_{n}", f"name_{n}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_item, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        manifest = load_manifest()
        assert len(manifest) == 10
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_staging.py -v --tb=short`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_staging.py
git commit -m "test: add tests for staging.py (manifest CRUD, batch updates, concurrent access)"
```

---

## Chunk 2: Infrastructure Fixes (Tasks 4-6)

### Task 4: Fix mock vector dimensions (Spec 3.7)

**Files:**
- Modify: `tests/conftest.py:223,232,249,259`

- [ ] **Step 1: Update all 384d vectors to 1024d**

Find all occurrences of `[0.1] * 384` and `[0.2] * 384` in `tests/conftest.py` and replace with `[0.1] * 1024` and `[0.2] * 1024`.

There are 4 locations:
- Line ~223: `"vector": [0.1] * 384` (mock_lancedb_with_data, chunk_1)
- Line ~232: `"vector": [0.2] * 384` (mock_lancedb_with_data, chunk_2)
- Line ~249: `embedder.embed_documents.return_value = [[0.1] * 384]` (mock_embedder)
- Line ~259: `return [0.1] * 384` (mock_async_embedder)

Replace each `384` with `1024`.

- [ ] **Step 2: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All pass (583+). The dimension change only affects mock data — no production code references these fixtures' dimension directly.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "fix: update mock vectors from 384d to 1024d (matches BGE-M3 post-migration)"
```

---

### Task 5: Lazy-init module singletons in processor.py (Spec 3.2)

**Files:**
- Modify: `src/processor.py:14-20`

- [ ] **Step 1: Read current code**

Current pattern (lines 14-20):
```python
_dedup = DuplicateDetector()
_pii_scanner = PrivacyScanner()
_custom_pii_terms = load_custom_pii_terms()
_auto_tagger = None  # Already lazy
```

- [ ] **Step 2: Convert to lazy-init**

Replace the three eager inits with:
```python
_dedup: DuplicateDetector | None = None
_pii_scanner: PrivacyScanner | None = None
_custom_pii_terms: list | None = None
_auto_tagger = None  # Already lazy


def _get_dedup() -> DuplicateDetector:
    global _dedup
    if _dedup is None:
        _dedup = DuplicateDetector()
    return _dedup


def _get_pii_scanner() -> PrivacyScanner:
    global _pii_scanner
    if _pii_scanner is None:
        _pii_scanner = PrivacyScanner()
    return _pii_scanner


def _get_custom_pii_terms():
    global _custom_pii_terms
    if _custom_pii_terms is None:
        _custom_pii_terms = load_custom_pii_terms()
    return _custom_pii_terms
```

- [ ] **Step 3: Update all references in processor.py**

Search for `_dedup.`, `_pii_scanner.`, and `_custom_pii_terms` throughout the file and replace with `_get_dedup().`, `_get_pii_scanner().`, and `_get_custom_pii_terms()`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ --tb=short -q`
Expected: All pass. The lazy-init returns the same objects — behavior is identical, only timing of construction changes.

- [ ] **Step 5: Commit**

```bash
git add src/processor.py
git commit -m "refactor: lazy-init module singletons in processor.py (avoid import-time model load)"
```

---

### Task 6: Sync pyproject.toml dependency versions (Spec 3.8)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current pyproject.toml dependencies**

Compare against `requirements.txt` to find the actual minimum versions in use.

- [ ] **Step 2: Update minimum versions**

Key updates (the rest stay as-is if they're reasonable):
```
"lancedb>=0.4.0"  →  "lancedb>=0.27.1"
"sentence-transformers>=2.2.0"  →  "sentence-transformers>=5.2.0"
"fastmcp>=0.1.0"  →  "fastmcp>=2.14.0"
```

Verify each by checking the `>=` bound in `requirements.txt`. The goal is to prevent anyone installing via `pip install .` from getting an incompatible version.

- [ ] **Step 3: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass (no behavior change).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "fix: sync pyproject.toml minimum dep versions with requirements.txt"
```

---

## Chunk 3: IngestService Unification (Task 7)

### Task 7: Create IngestService and rewire endpoints (Spec 3.1)

This is the largest task. It extracts the 9-phase enrichment pipeline from `executor.py:_index_in_rag()` into a reusable async service.

**Files:**
- Create: `src/ingest_service.py`
- Modify: `src/executor.py` (delegate to IngestService)
- Modify: `src/api/v1_routes.py:555-712,925-992` (rewire api_ingest + quick_capture)

- [ ] **Step 1: Create `src/ingest_service.py` with the core class**

The `IngestService` wraps the 9 phases from `_index_in_rag()` with feature flags. It accepts an `EmbeddingService` via dependency injection (from FastAPI lifespan or direct construction).

Key design decisions:
- Async interface (`async def ingest(...)`) — callers in API routes can `await` directly
- Feature flags for skipping expensive phases (context gen, PII, graph)
- Returns an `IngestResult` dataclass with counts and document_id
- Does NOT handle file archiving, vault export, or status updates — those remain in `executor.py`

```python
# src/ingest_service.py
"""Unified document ingestion service for CoreRag.

All paths that store content in LanceDB should route through this service
to ensure consistent enrichment (context prefixes, quality scores, source
authority, date extraction, content hash dedup, parent summaries).
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src import config
from src.exceptions import ProcessingError

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Result of an ingest operation."""

    document_id: str
    parent_chunks: int = 0
    child_chunks: int = 0
    skipped_dedup: int = 0
    source: str = ""


class IngestService:
    """Shared ingestion pipeline with configurable enrichment phases.

    Usage:
        service = IngestService(embedding_service=embedder, db=db)
        result = await service.ingest(text, metadata)
    """

    def __init__(self, embedding_service, db):
        self._embedder = embedding_service
        self._db = db

    async def ingest(
        self,
        text: str,
        metadata: dict,
        *,
        source_path: str = "api_ingest",
        skip_context: bool = False,
        skip_quality: bool = False,
        skip_graph: bool = False,
        skip_parents: bool = False,
    ) -> IngestResult:
        """Ingest text into LanceDB with configurable enrichment.

        This is the single entry point for all ingestion paths.
        The full pipeline (executor) calls with all defaults.
        API ingest may set skip_context=True for speed.
        Quick-capture sets skip_parents=True.
        """
        # Import here to avoid circular deps and keep service lightweight
        from src.chunking.parent_child import ParentChildChunker
        from src.utils.query_sanitize import build_eq_clause

        # Generate document ID
        document_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]

        # Chunk
        chunker = ParentChildChunker()
        parents, children = chunker.chunk_document(
            text, source_path=source_path, document_id=document_id
        )

        if not children:
            return IngestResult(document_id=document_id, source=source_path)

        # Phase: Content hash dedup
        skipped = 0
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if "child_chunks" in self._db.table_names():
                    existing_table = self._db.open_table("child_chunks")
                    doc_filter = build_eq_clause("document_id", document_id)
                    existing = existing_table.search().where(doc_filter).limit(10000).to_list()
                    existing_hashes = {r.get("content_hash", "") for r in existing}
                    original_count = len(children)
                    children = [
                        c for c in children if c.content_hash not in existing_hashes
                    ]
                    skipped = original_count - len(children)
                    if skipped:
                        logger.info(f"Dedup: {skipped} unchanged chunks skipped")
        except Exception as e:
            logger.debug(f"Content hash dedup skipped: {e}")

        if not children:
            return IngestResult(
                document_id=document_id,
                source=source_path,
                skipped_dedup=skipped,
            )

        # Phase: Source authority
        authority = config.SOURCE_AUTHORITY_DEFAULT
        if not skip_quality:
            try:
                from src.classification.source_authority import SourceAuthorityClassifier

                authority = SourceAuthorityClassifier().classify(metadata).value
            except Exception:
                pass

        # Phase: Chunk quality scoring
        quality_scores = [0.0] * len(children)
        if not skip_quality:
            try:
                from src.quality.chunk_scorer import ChunkScorer

                scorer = ChunkScorer()
                quality_scores = [scorer.score(c.content).overall for c in children]
            except Exception:
                pass

        # Phase: Date extraction
        dates = [("", 0.0)] * len(children)
        if not skip_quality:
            try:
                from src.quality.date_extractor import DateExtractor

                date_ext = DateExtractor()
                dates = [date_ext.extract(c.content) for c in children]
            except Exception:
                pass

        # Phase: Contextual retrieval
        context_prefixes = [""] * len(children)
        if not skip_context and config.CONTEXT_GENERATION:
            try:
                from src.chunking.context_generator import ContextGenerator

                ctx_gen = ContextGenerator()
                child_texts = [c.content for c in children]
                context_prefixes = await ctx_gen.generate_contexts_batch(
                    text, child_texts, concurrency=3
                )
            except Exception as e:
                logger.warning(f"Context generation failed: {e}")

        # Phase: Embed (context + content)
        embed_texts = []
        for c, ctx in zip(children, context_prefixes):
            embed_texts.append(f"{ctx}\n\n{c.content}" if ctx else c.content)
        embeddings = self._embedder.embed_documents(embed_texts, show_progress=False)

        # Phase: Parent summaries
        parent_summaries: dict[str, str] = {}
        if not skip_parents:
            try:
                from src.chunking.summarizer import MultiResolutionSummarizer

                summarizer = MultiResolutionSummarizer()
                for p in parents:
                    p_children = [c.content for c in children if c.parent_id == p.id]
                    try:
                        summary = await summarizer.summarize_parent(p.content, p_children)
                        parent_summaries[p.id] = summary
                    except Exception:
                        pass
            except Exception:
                pass

        # Build tags string
        raw_tags = metadata.get("tags", [])
        tags_str = "," + ",".join(raw_tags) + "," if isinstance(raw_tags, list) and raw_tags else ""

        # Build data dicts
        now_iso = datetime.now(timezone.utc).isoformat()

        parent_data = []
        if not skip_parents:
            for p in parents:
                parent_data.append({
                    "id": p.id,
                    "document_id": p.document_id,
                    "content": p.content,
                    "source_path": source_path,
                    "section_title": getattr(p, "section_title", ""),
                    "token_count": getattr(p, "token_count", len(p.content.split())),
                    "created_at": now_iso,
                    "tags": tags_str,
                    "content_hash": getattr(p, "content_hash", ""),
                    "summary": parent_summaries.get(p.id, ""),
                })

        child_data = []
        for i, c in enumerate(children):
            child_data.append({
                "id": c.id,
                "parent_id": c.parent_id,
                "document_id": c.document_id,
                "content": c.content,
                "vector": embeddings[i],
                "chunk_index": i,
                "source_path": source_path,
                "tags": tags_str,
                "content_hash": c.content_hash,
                "context_prefix": context_prefixes[i],
                "quality_score": quality_scores[i],
                "source_authority": authority,
                "date_extracted": dates[i][0],
                "date_confidence": dates[i][1],
            })

        # Write to LanceDB
        import pyarrow as pa

        for table_name, data in [("parent_chunks", parent_data), ("child_chunks", child_data)]:
            if not data:
                continue
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    tbl = self._db.open_table(table_name)
                    tbl.add(data)
                except Exception:
                    try:
                        self._db.create_table(table_name, pa.table({k: [v] for k, v in data[0].items()}))
                        if len(data) > 1:
                            self._db.open_table(table_name).add(data[1:])
                    except Exception:
                        self._db.open_table(table_name).add(data)

        return IngestResult(
            document_id=document_id,
            parent_chunks=len(parent_data),
            child_chunks=len(child_data),
            skipped_dedup=skipped,
            source=source_path,
        )
```

- [ ] **Step 2: Rewire `executor.py:_index_in_rag` to delegate to IngestService**

Replace the body of `_index_in_rag(text, file_name, metadata)` with:

```python
def _index_in_rag(text: str, file_name: str, metadata: dict) -> None:
    """Chunk, embed, and store document text in the LanceDB vector database."""
    import lancedb

    from src.embeddings.embedding_service import create_embedding_service
    from src.ingest_service import IngestService

    db = lancedb.connect(str(config.DB_PATH))
    embedder = create_embedding_service()
    service = IngestService(embedding_service=embedder, db=db)

    with asyncio.Runner() as runner:
        runner.run(service.ingest(text, metadata, source_path=file_name))
```

This preserves the sync interface that `execute_approved_item` expects while delegating to the async IngestService.

- [ ] **Step 3: Rewire `api_ingest` endpoint**

Replace the inline chunking/embedding logic in the `api_ingest` function (lines ~555-712 of v1_routes.py) with:

```python
from src.ingest_service import IngestService

embedder = getattr(request.app.state, "embedding_service", None)
db = getattr(request.app.state, "db", None)
if not embedder or not db:
    # fallback...

service = IngestService(embedding_service=embedder, db=db)
result = await service.ingest(
    text=content,
    metadata={"category": metadata.get("category", ""), "tags": metadata.get("tags", [])},
    source_path=source,
    skip_context=True,  # API ingest skips context gen for speed
)

return IngestResponse(
    document_id=result.document_id,
    source=source,
    chunks_created=result.child_chunks,
    parent_chunks=result.parent_chunks,
)
```

- [ ] **Step 4: Rewire `quick_capture` endpoint**

Replace the inline logic with:

```python
service = IngestService(embedding_service=embedder, db=db)
result = await service.ingest(
    text=body.text,
    metadata={"tags": body.tags or []},
    source_path=body.source or "quick-capture",
    skip_context=True,
    skip_quality=True,
    skip_parents=True,
)
```

- [ ] **Step 5: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All pass. The IngestService produces the same enriched output as the old inline code. API endpoints now produce richer chunks (with content_hash, quality_score, etc.).

- [ ] **Step 6: Commit**

```bash
git add src/ingest_service.py src/executor.py src/api/v1_routes.py
git commit -m "feat: unified IngestService — all ingest paths share the same enrichment pipeline"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --tb=short -q`
Expected: 583+ tests pass, no regressions. New tests from Tasks 1-3 add ~30 tests.

- [ ] **Verify IngestService is the single entry point**

Run: `grep -rn "ParentChildChunker" src/api/v1_routes.py`
Expected: No matches (chunking is now inside IngestService, not inline in API routes).

- [ ] **Update TECH_DEBT.md**

Mark TD-008 (three ingest paths), TD-011 (module singletons), TD-012 (pyproject versions) as resolved.
Update TD-001 if enrichment backfill progressed.

---

## Summary

| Task | Spec | Files | New Tests | Lines |
|------|------|-------|-----------|-------|
| 1 | 3.4 | test_intelligence.py | ~15 | ~150 |
| 2 | 3.5 | test_hybrid_search.py | ~8 | ~120 |
| 3 | 3.6 | test_staging.py | ~12 | ~120 |
| 4 | 3.7 | conftest.py | 0 | 4 |
| 5 | 3.2 | processor.py | 0 | ~25 |
| 6 | 3.8 | pyproject.toml | 0 | ~5 |
| 7 | 3.1 | ingest_service.py, executor.py, v1_routes.py | 0 | ~250 |

**Total: 7 tasks, ~35 new tests, ~675 lines, estimated 1-2 sessions.**
