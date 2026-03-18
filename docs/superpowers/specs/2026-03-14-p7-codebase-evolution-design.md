# P7 Codebase Evolution — Design Spec

**Date:** 2026-03-14
**Author:** Claude Opus 4.6 (Session 31)
**Status:** Complete — P7 waves 1 and 2 implemented (Session 31, 2026-03-14)
**Scope:** Full codebase audit → prioritized improvement spec across safety, performance, architecture, and enhancement

---

## Context

CoreRag is a local-first, privacy-preserving knowledge engine published on GitHub (Tier 1 Public). All 12 wiring phases are complete, P5 retrieval enhancement is done, and P6 enrichment backfill is at 85.5%. The project is in maintenance mode per the master plan (priority #9).

A deep codebase audit on 2026-03-14 identified 30+ findings across 8 dimensions: code complexity, performance bottlenecks, security patterns, test coverage gaps, dead code, API consistency, dependency health, and architecture concerns. An ecosystem database survey across 9 active projects informed database evolution recommendations.

This spec organizes all findings into 4 execution waves, prioritized by impact. Each wave is independently executable. Items within waves are independently cherry-pickable.

---

## Wave 1: Safety & Correctness

**Goal:** Fix bugs and silent failure modes that exist right now.
**Effort:** ~25 lines across 8 files. Under 1 hour.

### 1.1 Replace assert guards in MCP tool handlers

**Files:** `src/mcp_server/server.py:954,961,970,982,992,999,1006`
**Problem:** 7 MCP tool handlers use `assert _corerag_tools is not None` as a runtime guard. Python's `assert` is stripped with `-O` flag, causing `AttributeError` on `None` instead of a clean error.
**Fix:** Replace each `assert` with `if not _corerag_tools: return {"error": "CoreRag tools not initialized"}`.
**Test:** Verify all 30 tool handlers use the same guard pattern.

### 1.2 Normalize API search score semantics

**Files:** `src/api/v1_routes.py:343`
**Problem:** `/api/v1/search` returns raw cosine distance as `score` — lower is better. Every other search path (MCP, dashboard) uses higher-is-better scoring. External consumers expect `score=0.95` to mean "highly relevant."
**Fix:** `score = max(0.0, 1.0 - float(r.get("_distance", 0)))` — converts to 0-1 similarity where 1.0 = perfect match. Document semantics in `/api/v1/manifest` response.
**Note:** LanceDB returns cosine distance in range [0, 2]. The formula produces [0, 1] for typical results; vectors pointing in opposite directions (distance > 1.0) are clamped to 0.0.
**Test:** Existing API tests should verify score range [0, 1].

### 1.3 Backfill script model resolution

**Files:** `scripts/backfill_enrichment.py`
**Problem:** `--provider ollama` without `--model` passed `gemini-2.5-pro` to Ollama, causing 404. The global `CORERAG_LLM_MODEL=opus` env var also overrode Ollama's model.
**Fix:** Already fixed this session — backfill-specific `_BACKFILL_MODEL_DEFAULTS` dict, `--model` default changed to `None`.
**Status:** Done.

### 1.4 Fix Gemini CLI install URL

**Files:** `src/llm/provider.py:378`
**Problem:** Error message says `npm install -g @anthropic-ai/gemini-cli` — copy-paste from ClaudeCliProvider. Gemini CLI is a Google product.
**Fix:** Replace `npm install -g @anthropic-ai/gemini-cli` with `pip install google-generativeai` or the correct Gemini CLI install command. Verify the exact package name before implementing — the Gemini CLI is installed via `pip install google-genai` or the standalone binary at `https://github.com/google-gemini/gemini-cli`.

### 1.5 Anchor staging manifest to STATE_DIR

**Files:** `src/staging.py:10`
**Problem:** `STAGING_MANIFEST_PATH = Path("staging_manifest.json")` creates the file in CWD. If the server starts from a different directory, the manifest is lost or created in the wrong location.
**Fix:** Add `from src import config` to imports. Then: `STAGING_MANIFEST_PATH = config.STATE_DIR / "staging_manifest.json"`. (`config.STATE_DIR` is already a `Path` — no wrapping needed.)

### 1.6 Anchor corrections log to STATE_DIR

**Files:** `src/correction_log.py:9`
**Problem:** Same CWD-relative path issue as 1.5.
**Fix:** Add `from src import config` to imports. Then: `CORRECTIONS_PATH = config.STATE_DIR / "corrections_log.json"`.

### 1.7 Centralize OLLAMA_MODEL references

**Files:** `src/config.py:68`, `src/mcp_server/server.py:113`, `src/api/v1_routes.py:306,413`, `src/api/dashboard_routes.py:819`
**Problem:** 4 consumer files call `os.getenv("OLLAMA_MODEL", "qwen2.5:32b")` directly instead of using `config.OLLAMA_MODEL`. The source of truth in `src/config.py:68` also has a stale default (`qwen2.5:32b` instead of `qwen3:32b` since Session 29).
**Fix:** (1) Update `src/config.py:68` default from `"qwen2.5:32b"` to `"qwen3:32b"`. (2) Replace all 4 consumer call sites with `from src.config import OLLAMA_MODEL`.

### 1.8 Warn when API auth is disabled

**Files:** `src/server.py:97-101`
**Problem:** When `CORERAG_API_KEY` is not set, all API v1 endpoints are open with no warning. An automated deployment could accidentally expose the server.
**Fix:** `if not CORERAG_API_KEY: logger.warning("API authentication disabled — all v1 endpoints are open")`.

### 1.9 Remove unused heavy dependencies

**Files:** `pyproject.toml:26-27`
**Problem:** `unstructured[all-docs]` and `pdfplumber` are declared as dependencies but never imported. `unstructured[all-docs]` installs tesseract, libmagic, and multiple ML models — gigabytes of unused packages.
**Fix:** Remove both lines from `[project.dependencies]`.

---

## Wave 2: Performance & Search Quality

**Goal:** Make CoreRag faster and ensure all interfaces return the same quality results.
**Effort:** ~160 lines across 4 files. One session.

### 2.1 Singleton EmbeddingService in FastAPI lifespan

**Files:** `src/api/v1_routes.py:297,404,512,877`, `src/server.py` (lifespan)
**Problem:** `create_embedding_service()` is called per API request. Each call potentially loads the BGE-M3 model (~2GB). The MCP server initializes the embedding service once at startup — the REST API should do the same.
**Fix:** Initialize `EmbeddingService` in the FastAPI lifespan context manager (alongside the existing auto-backup). Store on `app.state.embedding_service`. Replace all 4 call sites with `request.app.state.embedding_service`. Also remove the paired local `from src.embeddings.embedding_service import create_embedding_service` imports ~10-15 lines above each call site.
**Dependency:** None.

### 2.2 Route REST API search through HybridSearcher

**Files:** `src/api/v1_routes.py:310-345`, `src/server.py` (lifespan)
**Problem:** `/api/v1/search` does plain vector search via `child_table.search(query_vector).limit(k)`. It skips BM25 hybrid fusion, cross-encoder reranking, time-decay scoring, and Corrective RAG filtering that the MCP `search_knowledge` tool applies. External consumers (Kendra, Centaur) get worse results than Claude Desktop for identical queries.
**Fix:** Initialize `HybridSearcher` in lifespan (same as MCP server does). Route `/api/v1/search` through `hybrid_searcher.search()` with the full pipeline. A response mapping function is needed to convert `HybridSearcher` results (which use RRF combined scores) back into the `SearchResultItem` Pydantic model. The `score` field should use the normalized similarity semantics from item 1.2.
**Dependency:** 2.1 (needs embedding service for HybridSearcher), 1.2 (score semantics).
**Impact:** This is the highest-value item in the entire spec — it eliminates the split-quality problem.

### 2.3 Refactor chat endpoint to use LLMProvider

**Files:** `src/api/dashboard_routes.py:764-839`
**Problem:** The dashboard chat endpoint makes a direct `httpx` POST to Ollama's `/api/chat` with a hardcoded model default (`qwen2.5:32b`). It bypasses the `LLMProvider` abstraction entirely. `CORERAG_LLM_PROVIDER=claude-cli` has no effect on chat. The model default is stale.
**Fix:** Replace the raw httpx call with `get_default_provider()`. This gives: correct model resolution, think-tag stripping for qwen3, timeout configuration, and provider switching.
**Dependency:** None.

### 2.4 Optimize RAG index dashboard endpoint

**Files:** `src/api/dashboard_routes.py:432-433`
**Problem:** `p_dict = parents.to_arrow().to_pydict()` and `c_dict = children.to_arrow().to_pydict()` load the entire parent_chunks and child_chunks tables into Python dicts on every dashboard page view. Currently ~10MB with 7,329 child chunks. Grows linearly with database size.
**Fix:** Avoid loading `content` and `vector` columns. Use `table.to_arrow().select(["source_path", "document_id", "tags"]).to_pydict()` to load only metadata columns. The key win is avoiding the `vector` column (~30MB for 7,329 x 1024-dim float32 vectors). If LanceDB supports `SELECT DISTINCT`, use that; otherwise, deduplicate in Python after the lightweight select.
**Dependency:** None.

### 2.5 Batch manifest writes for commit-all

**Files:** `src/api/dashboard_routes.py:342-346`, `src/staging.py`
**Problem:** `commit_all` iterates pending items and calls `update_item()` per item. Each call acquires a file lock, reads, modifies, and rewrites the entire manifest. For 50 items, that's 50 lock-read-modify-write cycles.
**Fix:** Add a `batch_update_items(updates: dict[str, dict])` method to `StagingManager` that applies all updates in a single lock-read-modify-write cycle. Call from `commit_all`.
**Dependency:** None.

### 2.6 Single event loop for async operations in executor

**Files:** `src/executor.py:205-211,236-243,350-356`
**Problem:** `_index_in_rag()` creates and destroys a new `asyncio` event loop for each async call — context generation, each parent summary, and entity extraction. For a document with 10 parent chunks, that's 10+ event loop create/destroy cycles.
**Fix:** Create a single event loop at the top of `execute_approved_item()`. Pass it to `_index_in_rag()` and `_extract_entities()`. All `loop.run_until_complete()` calls reuse the same loop. Close it once at the end. Consider using `asyncio.Runner` (Python 3.12+) as the modern alternative to manual loop management.
**Caveat:** Verify that `generate_contexts_batch()`, `summarize_parent()`, and `extractor.extract()` all complete cleanly within a single `run_until_complete()` call. If any use fire-and-forget tasks, those must be awaited before the next `run_until_complete()`.
**Dependency:** None.

### 2.7 Eliminate double count_rows on delete

**Files:** `src/api/v1_routes.py:664-667,811-815`
**Problem:** Delete endpoints call `count_rows()` before and after deletion (2 tables = 4 calls) to compute a diff for the response.
**Fix:** Query the document by ID first to verify existence, then delete. Return the known count of deleted rows without post-counting.
**Dependency:** None.

---

## Wave 3: Pipeline Unification & Test Coverage

**Goal:** Eliminate the three-ingest-path divergence and fill critical test gaps.
**Effort:** ~575 lines across ~10 files. 1-2 sessions.

### 3.1 Unified ingest service

**Files:** `src/executor.py` (extract), `src/api/v1_routes.py:500-570,850-900` (rewire), new `src/ingest_service.py`
**Problem:** CoreRag has three distinct paths for getting content into LanceDB:
1. **Full pipeline** (executor): dedup, context gen, quality scoring, date extraction, PII, graph, versioning, tags
2. **API v1 ingest**: basic chunking + embedding only
3. **Quick-capture**: children only, no parents

Documents ingested via API are second-class citizens — no context prefixes, no quality scores, no graph entries, invisible to entity search.

**Fix:** Extract the enrichment pipeline from `executor.py:_index_in_rag()` into a standalone `IngestService` class with feature flags:

```python
class IngestService:
    async def ingest(
        self,
        text: str,
        metadata: dict,
        *,
        skip_context: bool = False,  # Quick mode
        skip_pii: bool = False,      # For pre-sanitized content
        skip_graph: bool = False,    # Lightweight ingest
    ) -> IngestResult:
```

Route all three paths through this service. The full pipeline uses defaults. API ingest uses `skip_context=True` for speed with an option to enrich later. Quick-capture uses all skip flags.

**Dependency:** 2.1 (`IngestService` should accept an `EmbeddingService` via dependency injection to reuse the singleton rather than creating its own). No dependency on 2.6 — as a properly async service, `IngestService` uses `await` natively rather than `loop.run_until_complete()`.

### 3.2 Lazy-init module singletons in processor.py

**Files:** `src/processor.py:14-20`
**Problem:** `_dedup = DuplicateDetector()`, `_pii_scanner = PrivacyScanner()`, `_custom_pii_terms = load_custom_pii_terms()` are initialized at import time. `PrivacyScanner()` loads the spaCy `en_core_web_lg` model (hundreds of MB). Any test importing `processor` triggers full model loading.
**Fix:** Convert to lazy-init pattern matching `_get_auto_tagger()` already in the file:

```python
_pii_scanner: PrivacyScanner | None = None

def _get_pii_scanner() -> PrivacyScanner:
    global _pii_scanner
    if _pii_scanner is None:
        _pii_scanner = PrivacyScanner()
    return _pii_scanner
```

### 3.3 Standardize MCP tool initialization guards

**Merged into 1.1.** When replacing the 7 `assert` guards, also audit the remaining tool handlers for the no-guard + try/except pattern and standardize all 30 handlers on `if not _corerag_tools: return {"error": "CoreRag tools not initialized"}`.

### 3.4 Tests for intelligence.py

**Files:** New `tests/test_intelligence.py`
**Problem:** `intelligence.py` contains `_repair_json()` which handles malformed LLM output — missing braces, markdown fences, trailing commas. Called on every document analysis. Zero tests.
**Coverage targets:**
- `_repair_json()`: malformed JSON (missing braces, extra commas, markdown fences, truncated responses)
- `_clean_json_markdown()`: various markdown wrapper patterns
- `_sample_text()`: truncation behavior
- `analyze_document()`: happy path + LLM error + timeout (mock LLM provider)

### 3.5 Tests for HybridSearcher

**Files:** New `tests/test_hybrid_search.py`
**Problem:** The core retrieval mechanism has no dedicated tests. RRF fusion, FTS fallback, and filter construction are untested.
**Coverage targets:**
- `_reciprocal_rank_fusion()`: correctness with overlapping/disjoint result sets
- `ensure_fts_index()`: retry on failure
- `search()`: vector-only fallback when FTS unavailable
- Filter clause building with tags and categories

### 3.6 Tests for staging.py

**Files:** New `tests/test_staging.py`
**Problem:** Manifest CRUD and file locking have no tests.
**Coverage targets:**
- `add_item()`, `update_item()`, `remove_item()`: basic CRUD
- Status transitions: processing → pending → approved → completed
- Concurrent access: two threads writing to the same manifest

### 3.7 Fix mock vector dimensions

**Files:** `tests/conftest.py:249,259`
**Problem:** Mock vectors use `[0.1] * 384` (pre-migration dimension) instead of `[0.1] * 1024` (current BGE-M3). Tests could pass with wrong dimensions while production schema expects 1024d.
**Fix:** Update to `[0.1] * 1024` (hardcoded to match BGE-M3). Importing `config.EMBEDDING_DIMENSIONS` could trigger `.env` loading side effects in CI. Alternatively, define a test constant `TEST_EMBEDDING_DIM = 1024` in conftest.py.

### 3.8 Sync pyproject.toml dependency versions

**Files:** `pyproject.toml`
**Problem:** Minimum versions (`lancedb>=0.4.0`, `sentence-transformers>=2.2.0`, `fastmcp>=0.1.0`) are far below actually-installed versions. Anyone installing via `pip install .` gets a broken installation with incompatible APIs.
**Fix:** Update minimum versions to match `requirements.txt` lower bounds.

---

## Wave 4: Database Evolution, Enhancements & Strategic Improvements

**Goal:** Strategic improvements informed by ecosystem patterns. Each item independently cherry-pickable.
**Effort:** Variable per item. Full wave is 3-4 sessions.

### 4.1 Enable BGE-M3 sparse vectors for 3-way hybrid search

**Files:** `src/embeddings/embedding_service.py`, `src/search/hybrid_search.py`, `src/chunking/parent_child.py` (schema)
**Problem:** CoreRag's hybrid search fuses dense vectors + BM25 keywords via RRF. VA_Assistant gets better recall by adding Splade sparse vectors. BGE-M3 natively supports sparse output via `model.encode(..., return_sparse=True)` — CoreRag isn't using this capability.
**Fix:**
1. Enable sparse output in `EmbeddingService.embed_documents()` — returns both dense and sparse vectors
2. Add `sparse_vector` column to child_chunks LanceDB schema
3. Implement 3-way RRF fusion: dense + sparse + BM25
4. Re-embed all chunks (Phase 2 of backfill script, estimated 2-5 minutes — the 384d→1024d migration of 4,748 chunks took 84.5s; sparse output adds per-chunk compute)

**Schema migration:** LanceDB supports adding columns. Extend `migrate_embeddings.py` to add a nullable `sparse_vector` column, then backfill it. Alternatively, drop and recreate `child_chunks` with the updated schema (as the backfill script already does for Phase 2).

**No new database needed.** LanceDB handles sparse vectors natively.

**Impact:** Improved recall for keyword-heavy queries (specific model names, policy numbers, technical terms) where BM25 alone may miss semantic variants and dense-only may miss exact terms.

### 4.2 Search result caching with TTL

**Files:** `src/search/hybrid_search.py` or `src/analytics/semantic_cache.py`
**Problem:** `SemanticCache` caches embedding vectors but not search results. Repeated queries (common during MCP tool loops in Claude Desktop) re-run the full hybrid search + reranking pipeline every time.
**Fix:** Add an LRU result cache keyed by `(query_hash, k, filters_hash)` with configurable TTL (default 5 minutes). Invalidate on any ingest or delete operation.

### 4.3 Semantic entity discovery in knowledge graph

**Files:** `src/graph/knowledge_graph.py`, new LanceDB table `entity_vectors`
**Problem:** Entity search (`search_by_entity`) uses exact string match. "Find concepts related to workforce planning" won't find "talent management" or "succession planning" without an exact match.
**Fix:** Embed entity names + descriptions into a small LanceDB table (`entity_vectors`). Add `search_entities_semantic(query, k)` that:
1. Finds similar entities by vector similarity
2. Traverses the graph from those starting points
3. Returns the subgraph of related entities and relationships

This transforms the knowledge graph from a lookup tool into a discovery tool.

### 4.4 Decompose CoreRagTools god object

**Files:** `src/mcp_server/tools.py` → split into `search_tools.py`, `memory_tools.py`, `maintenance_tools.py`, `quality_tools.py`, `graph_tools.py`
**Problem:** 1,300+ line class with 30 methods and 13 injected dependencies. Violates single-responsibility.
**Fix:** Split by domain. Each tool group class receives only its required dependencies. `server.py` composes all groups during initialization.

### 4.5 Split dashboard_routes.py

**Files:** `src/api/dashboard_routes.py` → `dashboard_batch.py`, `dashboard_memory.py`, `dashboard_analytics.py`, `dashboard_chat.py`
**Problem:** 930 lines, 38 routes in one file.
**Fix:** Extract domain-specific route groups into sub-modules. Mount as sub-routers in the main dashboard factory.

### 4.6 Staging manifest pruning

**Files:** `src/staging.py`
**Problem:** Completed and error items accumulate in `staging_manifest.json` indefinitely. Every `update_item()` rewrites the full manifest including historical items.
**Fix:** Add `cleanup_manifest(keep_statuses=["pending", "processing"])` called on server startup. Archive old items to `~/.corerag/manifest_archive/YYYY-MM.json`.

### 4.7 Code file chunker (TD-003)

**Files:** New `src/chunking/code_chunker.py`, `src/extractor.py` (wire in)
**Problem:** Python, JavaScript, TypeScript, Go, and Rust files cannot be ingested. The original code chunker was deleted as orphaned scaffold.
**Fix:** Implement AST-aware chunking for Python using the `ast` module (split at function/class boundaries). Fallback to line-based chunking (chunks of 50-100 lines with overlap) for other languages. Wire into `extractor.py` file type routing.

### 4.8 Wire RBAC scaffold (TD-002)

**Files:** `src/auth/access_control.py`, `src/server.py`, `src/api/v1_routes.py`
**Problem:** AccessControl module implements ADMIN/EDITOR/VIEWER roles with PII filtering, but nothing uses it.
**Fix:** Add middleware to `server.py` that resolves role from API key. Wire PII-based result filtering into search endpoints. Only activate when role mappings are configured.
**Trigger:** When multi-user access is needed or non-localhost deployment.

### 4.9 Dependency lock file

**Files:** `requirements.lock` (new), `requirements.txt` (keep as intent)
**Problem:** All deps use `>=` with no lock file. Installs are non-reproducible.
**Fix:** `pip-compile requirements.txt -o requirements.lock`. Commit lock file. CI uses lock file, dev uses requirements.txt.

### 4.10 Fix private method access in API route

**Files:** `src/api/v1_routes.py:606`, `src/graph/knowledge_graph.py`
**Problem:** API route calls `extractor._extract_with_patterns()` directly — bypasses public interface.
**Fix:** Add public `extract_sync()` method on `EntityExtractor`.

### 4.11 Deduplicate VersionManager instantiation

**Files:** `src/executor.py:473,489`
**Problem:** Two `VersionManager()` instances created in the same function call.
**Fix:** Reuse single instance.

### 4.12 Move local imports to top level

**Files:** `src/mcp_server/server.py:251,314`
**Problem:** `import time as _time` inside function bodies is non-idiomatic for stdlib.
**Fix:** Move to top-level imports.

---

## Execution Priority

| Wave | Items | Files | Lines | Sessions | Priority |
|------|-------|-------|-------|----------|----------|
| 1 | 9 | 8 | ~25 | <1 | Do first — safety fixes |
| 2 | 7 | 4 | ~160 | 1 | Do second — biggest user-facing impact |
| 3 | 8 | ~10 | ~575 | 1-2 | Do third — architectural foundation |
| 4 | 12 | ~15 | ~800 | 3-4 | Cherry-pick — strategic enhancements |

**Recommended session plan:**
- **Session 31 (this session):** Wave 1 complete + start Wave 2
- **Session 32:** Complete Wave 2 + Wave 3.1-3.3
- **Session 33:** Wave 3.4-3.8 (tests)
- **Sessions 34+:** Wave 4 items by priority (4.1, 4.3, 4.7 recommended first)

---

## New Tech Debt Items (Not in TECH_DEBT.md)

These were discovered during the audit and should be added to `_DEV/TECH_DEBT.md`:

| ID | Title | Severity | Wave |
|----|-------|----------|------|
| TD-007 | Assert guards in MCP tool handlers stripped with -O flag (verify max ID in TECH_DEBT.md before adding) | High | 1.1 |
| TD-008 | REST API search bypasses HybridSearcher — split-quality results | High | 2.2 |
| TD-009 | Three divergent ingest paths — API-ingested docs are second-class | High | 3.1 |
| TD-010 | EmbeddingService re-initialized per API request | Medium | 2.1 |
| TD-011 | staging_manifest.json and corrections_log.json use CWD-relative paths | Medium | 1.5/1.6 |
| TD-012 | Chat endpoint bypasses LLMProvider abstraction | Medium | 2.3 |
| TD-013 | Module-level singletons in processor.py cause import-time model load | Medium | 3.2 |
| TD-014 | pyproject.toml dependency versions far below installed versions | Medium | 3.8 |
| TD-015 | Staging manifest grows unbounded | Medium | 4.6 |

---

## Database Evolution Decision

**Recommendation: No new database engine needed.**

The ecosystem survey showed:
- **LanceDB** handles CoreRag's needs well — dense vectors, BM25 FTS, and can store sparse vectors
- **Qdrant** excels at native dense+sparse hybrid (VA_Assistant's use case) but adds Docker/server overhead
- **SQLite** is correctly used for the knowledge graph (relational triples with bitemporal tracking)

The highest-value database improvement is **enabling BGE-M3's sparse output** (Wave 4.1) — this adds a third retrieval signal (learned sparse vectors) to the existing dense + BM25 hybrid without any new infrastructure. The second is **semantic entity vectors** (Wave 4.3) — adding a small LanceDB table for knowledge graph discovery.

Both improvements use LanceDB (already a dependency) and maintain the zero-server, local-first architecture.

---

*Spec generated from codebase audit (30+ findings) and ecosystem database survey (9 projects) conducted 2026-03-14.*
