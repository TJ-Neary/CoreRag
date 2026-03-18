# P8 SP3: Dual RAG Database + Export Routing — Implementation Plan

> **Status: COMPLETE** — Implemented (Session 32, 2026-03-15/16). 5 commits, ~105 lines.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a restricted LanceDB instance for unredacted sensitive documents, dual-track commit in executor, search fan-out with scope parameter, and split RAG checkboxes in the dashboard.

**Architecture:** Second LanceDB at `~/.corerag/lancedb-restricted/` with identical schema. Executor indexes sensitive docs in both databases (redacted → main, unredacted → restricted). HybridSearcher gains `search_scope` parameter for fan-out search. All consumers default to main-only scope for cloud LLM safety. Cross-DB dedup via `catalog_id` stored in chunk metadata.

**Tech Stack:** Python 3.12+, LanceDB, FastAPI, FastMCP, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-15-p8-sp3-dual-rag-export-routing-spec.md`

**Context files to read before implementing:**
- `src/executor.py` — commit pipeline (where dual-track goes)
- `src/search/hybrid_search.py` — HybridSearcher + _ResultCache (refactor target)
- `src/ingest_service.py` — IngestService (runs enrichment pipeline)
- `src/chunking/parent_child.py` — chunk schemas (add catalog_id field)
- `src/config.py` — path constants
- `src/server.py` — FastAPI lifespan (HybridSearcher init)
- `src/mcp_server/server.py` — MCP startup (also inits HybridSearcher)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/config.py` | Modify | Add `RESTRICTED_DB_PATH` |
| `src/chunking/parent_child.py` | Modify | Add `catalog_id` field to chunk schemas |
| `src/ingest_service.py` | Modify | Accept + store `catalog_id` in chunk metadata |
| `src/executor.py` | Modify | Dual-track commit (restricted before redaction, main after) |
| `src/search/hybrid_search.py` | Modify | `_search_single()` refactor, `search_scope`, fan-out merge, cache key fix |
| `src/server.py` | Modify | Init restricted DB in lifespan, fix embedder= bug |
| `src/mcp_server/server.py` | Modify | `search_scope` on search_knowledge, init restricted DB |
| `src/api/v1_routes.py` | Modify | `search_scope` on REST search |
| `src/ui/templates/dashboard.html` | Modify | Split RAG checkbox into Main + Restricted |
| `tests/test_hybrid_search.py` | Modify | Fan-out, scope, cache tests |
| `tests/test_executor.py` | Modify | Dual-track commit tests |

---

## Task 1: Config + Chunk Schema Changes

**Files:**
- Modify: `src/config.py`
- Modify: `src/chunking/parent_child.py`

- [ ] **Step 1: Add RESTRICTED_DB_PATH to config**

In `src/config.py`, after the `DB_PATH` line (~57), add:

```python
RESTRICTED_DB_PATH = Path(
    os.getenv("CORERAG_RESTRICTED_DB_PATH", str(STATE_DIR / "lancedb-restricted"))
)
```

- [ ] **Step 2: Add catalog_id to chunk schemas**

In `src/chunking/parent_child.py`, find the `ChildChunk` dataclass. Add a `catalog_id` field:

```python
catalog_id: str = ""  # Cross-DB identifier from SQLite catalog
```

Add the same field to `ParentChunk`:

```python
catalog_id: str = ""  # Cross-DB identifier from SQLite catalog
```

Also update the LanceDB schema dicts (`CHILD_SCHEMA` and `PARENT_SCHEMA`) to include the new field.

- [ ] **Step 3: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass (additive change, no behavior difference).

- [ ] **Step 4: Commit**

```bash
git add src/config.py src/chunking/parent_child.py
git commit -m "feat: add RESTRICTED_DB_PATH config + catalog_id field on chunk schemas"
```

---

## Task 2: IngestService catalog_id Support

**Files:**
- Modify: `src/ingest_service.py`

- [ ] **Step 1: Add catalog_id parameter to ingest()**

In `src/ingest_service.py`, update the `ingest()` method signature to accept an optional `catalog_id: str = ""` parameter. Pass it through to the chunk creation so each child and parent chunk gets the `catalog_id` set in its metadata.

Find where `ChildChunk` instances are created and add `catalog_id=catalog_id`.
Find where `ParentChunk` instances are created and add `catalog_id=catalog_id`.

- [ ] **Step 2: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/ingest_service.py
git commit -m "feat: IngestService passes catalog_id to chunk metadata"
```

---

## Task 3: Executor Dual-Track Commit

**Files:**
- Modify: `src/executor.py`

- [ ] **Step 1: Add restricted RAG indexing before redaction**

In `execute_approved_item()`, find the text extraction section (~line 215) and the PII redaction section (~line 233). Between extraction and redaction, add the restricted RAG indexing:

```python
# After: export_text = extract_text(current_path) OR fallback to staged text
# Before: if is_sensitive: export_text = _redact_pii(...)

# Index in RESTRICTED RAG (unredacted) — before PII redaction
if is_sensitive and not item.get("skip_restricted_rag", False):
    try:
        import lancedb
        from src.ingest_service import IngestService

        restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
        restricted_embedder = create_embedding_service()
        restricted_service = IngestService(
            embedding_service=restricted_embedder, db=restricted_db
        )

        with asyncio.Runner() as runner:
            runner.run(
                restricted_service.ingest(
                    export_text,  # Original unredacted text
                    final_metadata,
                    source_path=current_path.name,
                    skip_graph=True,
                    catalog_id=document_id,
                )
            )

        logger.info(f"Restricted RAG indexed (unredacted): {current_path.name}")
    except Exception as e:
        logger.warning(f"Restricted RAG indexing failed (non-fatal): {e}")
```

Also update the catalog registration section to set `restricted_rag_doc_id` and record the export:

```python
if is_sensitive and not item.get("skip_restricted_rag", False):
    catalog.update(document_id, restricted_rag_doc_id=document_id)
    catalog.record_export(ExportRecord(
        document_id=document_id,
        destination="restricted_rag",
        path=document_id,
        redacted=False,
    ))
```

Also pass `catalog_id=document_id` to the existing main RAG `IngestService.ingest()` call.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_executor.py --no-cov -v --tb=short`
Expected: All pass (restricted indexing is non-fatal, tests won't have restricted DB).

- [ ] **Step 3: Commit**

```bash
git add src/executor.py
git commit -m "feat: dual-track commit — restricted RAG (unredacted) + main RAG (redacted)"
```

---

## Task 4: HybridSearcher Refactor + Search Scope

**Files:**
- Modify: `src/search/hybrid_search.py`
- Modify: `tests/test_hybrid_search.py`

This is the most complex task. It requires:
1. Adding `restricted_db` to constructor
2. Extracting `_search_single()` from `search()`
3. Adding `search_scope` parameter
4. Adding `source_db` to SearchResult
5. Fixing cache key to include scope
6. Implementing fan-out merge by `catalog_id`

- [ ] **Step 1: Add source_db to SearchResult**

Find the `SearchResult` dataclass in `hybrid_search.py`. Add:

```python
source_db: str = "main"  # "main" or "restricted"
```

- [ ] **Step 2: Fix cache key to include search_scope**

In `_ResultCache._key()`, change from:

```python
return f"{query}|{k}|{filters}"
```

To:

```python
def _key(self, query: str, k: int, filters: dict | None, search_scope: str = "main") -> str:
    return f"{query}|{k}|{filters}|{search_scope}"
```

Update all callers of `_key()` and cache `get()`/`put()` to pass `search_scope`.

- [ ] **Step 3: Add restricted_db to constructor**

Update `HybridSearcher.__init__`:

```python
def __init__(self, db, table_name: str = "child_chunks", restricted_db=None):
    self.db = db
    self.restricted_db = restricted_db
    # ... existing init ...
```

- [ ] **Step 4: Extract _search_single() from search()**

Create a new private method that encapsulates the core search logic (vector search, BM25 FTS, RRF fusion, reranking) for a single database. The existing `search()` method becomes a dispatcher that calls `_search_single()` based on scope.

```python
async def _search_single(
    self, db, query: str, query_vector: list[float], k: int = 10,
    filters: dict | None = None, source_db: str = "main", **kwargs
) -> list[SearchResult]:
    """Run hybrid search against a single LanceDB instance."""
    # Move existing search logic here
    # Set source_db on each result
```

- [ ] **Step 5: Add search_scope to search() and implement fan-out**

```python
async def search(
    self, query, query_vector, k=10, filters=None, search_scope="main", **kwargs
) -> list[SearchResult]:
    # Check cache (with scope in key)
    if search_scope == "main":
        return await self._search_single(self.db, query, query_vector, k, filters, "main", **kwargs)
    elif search_scope == "restricted":
        if not self.restricted_db:
            return []
        return await self._search_single(self.restricted_db, query, query_vector, k, filters, "restricted", **kwargs)
    elif search_scope == "all":
        main = await self._search_single(self.db, query, query_vector, k, filters, "main", **kwargs)
        if not self.restricted_db:
            return main
        restricted = await self._search_single(self.restricted_db, query, query_vector, k, filters, "restricted", **kwargs)
        return self._merge_results(main, restricted, k)
```

- [ ] **Step 6: Implement _merge_results()**

```python
def _merge_results(self, main: list, restricted: list, k: int) -> list:
    """Merge results from both DBs, deduplicate by catalog_id."""
    seen_catalog_ids = {}
    merged = []
    # Prefer restricted versions (has full text)
    for r in restricted:
        cid = getattr(r, 'catalog_id', '') or r.document_id
        seen_catalog_ids[cid] = True
        merged.append(r)
    for r in main:
        cid = getattr(r, 'catalog_id', '') or r.document_id
        if cid not in seen_catalog_ids:
            merged.append(r)
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:k]
```

- [ ] **Step 7: Ensure FTS index lazy init for restricted DB**

In `_search_single()`, when operating on the restricted DB, check if the FTS index exists before attempting BM25 search. If not, gracefully fall back to vector-only search for that DB.

- [ ] **Step 8: Write tests**

Add to `tests/test_hybrid_search.py`:
- `test_search_scope_main` — default scope returns only main results
- `test_search_scope_restricted` — restricted scope queries restricted DB
- `test_search_scope_all_merges` — all scope merges both, deduplicates by catalog_id
- `test_search_scope_all_prefers_restricted` — same doc in both, restricted version kept
- `test_cache_key_includes_scope` — same query with different scopes returns different results
- `test_restricted_db_none_fallback` — scope="all" with no restricted DB returns main only

- [ ] **Step 9: Run tests**

Run: `pytest tests/test_hybrid_search.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add src/search/hybrid_search.py tests/test_hybrid_search.py
git commit -m "feat: search fan-out with scope parameter + cross-DB merge by catalog_id"
```

---

## Task 5: Server + MCP Initialization

**Files:**
- Modify: `src/server.py`
- Modify: `src/mcp_server/server.py`

- [ ] **Step 1: Update FastAPI lifespan**

In `src/server.py` lifespan, after the main DB connection, add restricted DB:

```python
import lancedb
restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
```

Update the `HybridSearcher` construction to pass `restricted_db`. Also fix the pre-existing bug where `embedder=embedding_service` is passed (remove it — HybridSearcher doesn't accept that kwarg).

- [ ] **Step 2: Update MCP server startup**

In `src/mcp_server/server.py`, find the `_startup()` function where `HybridSearcher` is constructed. Add `restricted_db` parameter.

- [ ] **Step 3: Add search_scope to search_knowledge MCP tool**

In the `search_knowledge` tool definition, add `search_scope: str = "main"` parameter. Pass it through to `HybridSearcher.search()`.

- [ ] **Step 4: Add search_scope to REST search endpoint**

In `src/api/v1_routes.py`, add `search_scope: str = "main"` to the search endpoint request model. Pass through to the search call.

- [ ] **Step 5: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/mcp_server/server.py src/api/v1_routes.py
git commit -m "feat: initialize restricted DB in server lifespan + search_scope on MCP/REST"
```

---

## Task 6: Dashboard Checkbox Split

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Split the RAG checkbox into Main RAG + Restricted RAG**

Find the existing export destination checkboxes in the card template (around line 600). Currently there's a single "Send to RAG" checkbox. Replace with two:

```html
<label class="flex items-center space-x-2 mt-1 cursor-pointer">
    <input type="checkbox" id="main-rag-${id}" checked
        class="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500">
    <span class="text-sm text-gray-300">Main RAG (redacted)</span>
</label>
<label class="flex items-center space-x-2 mt-1 cursor-pointer">
    <input type="checkbox" id="restricted-rag-${id}" ${isSensitive ? 'checked' : ''}
        class="w-4 h-4 rounded border-gray-600 bg-gray-700 text-purple-500 focus:ring-purple-500">
    <span class="text-sm text-gray-300">Restricted RAG (unredacted)</span>
</label>
```

- [ ] **Step 2: Update sensitivity toggle to auto-check/uncheck Restricted RAG**

In the `togglePii()` function, add logic to auto-check Restricted RAG when sensitivity is toggled on, and uncheck when toggled off:

```javascript
function togglePii(id, checked) {
    // ... existing logic ...
    // Auto-toggle restricted RAG
    const restrictedCb = document.getElementById('restricted-rag-' + id);
    if (restrictedCb) restrictedCb.checked = checked;
}
```

- [ ] **Step 3: Update commit payload to include skip_restricted_rag**

In the commit function (where it reads checkbox states), add:

```javascript
const restrictedRagChecked = document.getElementById('restricted-rag-' + id)?.checked ?? false;
// Include in the update payload:
skip_restricted_rag: !restrictedRagChecked,
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: split RAG checkbox into Main + Restricted with sensitivity auto-toggle"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --no-cov --tb=short -q`
Expected: 665+ pass, no regressions.

- [ ] **Manual verification**

1. Start server, process a sensitive document through the dashboard
2. Verify both Main RAG and Restricted RAG checkboxes are checked
3. Commit — verify file appears in both `~/.corerag/lancedb/` and `~/.corerag/lancedb-restricted/`
4. Check catalog: `python -m src.cli.main catalog list --sensitive` — verify `restricted_rag_doc_id` is populated
5. Search via CLI: `python -m src.cli.main search "query"` — verify results come from main only
6. Uncheck Restricted RAG for a file, commit — verify it only goes to main

---

## Summary

| Task | What | Files | Effort |
|------|------|-------|--------|
| 1 | Config + chunk schema | config.py, parent_child.py | ~10 lines |
| 2 | IngestService catalog_id | ingest_service.py | ~15 lines |
| 3 | Executor dual-track commit | executor.py | ~40 lines |
| 4 | HybridSearcher refactor + fan-out | hybrid_search.py, tests | ~150 lines |
| 5 | Server/MCP initialization | server.py, mcp_server, v1_routes | ~30 lines |
| 6 | Dashboard checkbox split | dashboard.html | ~30 lines |

**Total: 6 tasks, ~275 lines. Task 4 (HybridSearcher) is the most complex.**
