# P9: Codebase Hardening — Design Specification

**Date:** 2026-03-17
**Phase:** P9
**Author:** Claude Opus 4.6 (Session 33)
**Status:** Reviewed — Approved (spec reviewer agent)

---

## 1. Context

A comprehensive 5-agent parallel audit of the CoreRag codebase identified **58 findings** across security, code quality, performance, test coverage, and documentation. These findings were consolidated into **28 new tech debt items** (TD-024 through TD-051) added to `_DEV/TECH_DEBT.md`.

### Audit Agents

| Agent | Focus | Findings | Duration |
|-------|-------|----------|----------|
| Security and Secrets | SQLi, XSS, injection, auth bypass, PII leakage | 11 | 3m 17s |
| Code Quality and Bugs | Logic errors, async correctness, dead code, error handling | 14 | 2m 47s |
| Performance | DB queries, memory, I/O, startup, search pipeline | 13 | 2m 37s |
| Orphaned Files and Gaps | Unwired modules, stale docs, plans, architecture vs reality | 15 | 2m 57s |
| Tech Debt and Coverage | TODOs, test gaps, config drift, dependency health | 15 | 4m 28s |

### Finding Distribution

| Severity | Security | Quality | Performance | Coverage | Docs/Config | Total |
|----------|----------|---------|-------------|----------|-------------|-------|
| Critical | 2 | 4 | 5 | 0 | 0 | **11** |
| High | 4 | 5 | 8 | 3 | 0 | **20** |
| Medium | 5 | 5 | 0 | 0 | 8 | **18** |
| Low | 0 | 0 | 0 | 0 | 9 | **9** |

---

## 2. Scope

P9 addresses all 59 audit findings organized into 4 execution waves, ordered by risk:

1. **Wave 1: Security + Data Protection** — Fix vulnerabilities that could expose PII or allow injection
2. **Wave 2: Async Correctness + Performance** — Fix event loop blocking and I/O inefficiencies
3. **Wave 3: Test Coverage** — Add tests for security-critical and untested production modules
4. **Wave 4: Documentation + Config + Cleanup** — Align docs with reality, fix config drift

### Out of Scope

- New features (no SP6 standalone app work)
- Enrichment backfill (TD-001 — separate operational task)
- Sparse vector support (TD-014 — blocked on external dependency)
- Inbox processing (TD-023 — separate operational task)
- SP6-deferred items (TD-019, TD-020)
- Pre-existing low items: TD-016 (dashboard_routes.py size), TD-018 (3 failed re-classifications)
- Pre-existing medium items: TD-022 (72 legacy vault files — requires LLM re-classification, operational task)
- TD-021 (verify dual RAG e2e) — folded into Wave 2 as verification step after touching hybrid_search.py and executor.py
- TD-017 (SQLite connection leak in read methods) — folded into Wave 2 Task 2.6 alongside TD-035

---

## 3. Wave 1: Security + Data Protection

**Goal:** Eliminate all critical and high security vulnerabilities. Protect PII data paths.

**Tech Debt Items:** TD-025, TD-026, TD-027, TD-028, TD-029, TD-030, TD-041, TD-042, TD-043

### Task 1.1: PII Redaction Fail-Safe (TD-025)

**File:** `src/executor.py:88-92`

Change `_redact_pii()` to raise `ProcessingError` on exception instead of returning unredacted text. The calling code already handles `ProcessingError` by setting item status to `error`.

**Tests:** Add test that verifies `_redact_pii` raises on Presidio failure (mock `AnalyzerEngine.analyze` to raise).

### Task 1.2: Gemini CLI Stdin (TD-026)

**File:** `src/llm/provider.py:403-416`

Refactor `GeminiCliProvider.generate()` to pass prompt via stdin (matching `ClaudeCliProvider` pattern) instead of `-p` argument. Use `process.communicate(input=combined_prompt.encode())`.

**Note:** Verify Gemini CLI accepts stdin input. If not, write to temp file with `tempfile.NamedTemporaryFile` and pass path.

**Tests:** Update existing Gemini CLI tests to verify stdin usage.

### Task 1.3: Cold Storage Path Validation (TD-027)

**Files:** `src/api/dashboard_routes.py:341-354`, `src/catalog/catalog_manager.py:629`

Add path validation before `migrate_to_cold()`: resolve path, verify under `/Volumes/` or `~/Documents`, reject `..` components, require existing directory.

**Tests:** Test path traversal payloads: `../../../etc`, `/tmp`, symlink chains.

### Task 1.4: Dashboard XSS Fix (TD-028)

**File:** `src/ui/templates/dashboard.html`

Add shared `escapeHtml()` function using `document.createElement('div').textContent` pattern. Apply to all `innerHTML` injection sites: RAG browser (`source_path`, `preview`), memory panel (`content`, `source`), corrections panel (`field`, `diff.ai`, `diff.human`), tag pills (`tag` value).

**Sites:** Lines ~1447, 1837-1848, 1889-1903, 1911-1918.

### Task 1.5: Auth on /api/v1/vaults (TD-029)

**File:** `src/api/v1_routes.py:978`

Add `permissions: dict[str, bool] = Depends(check_permissions)` to `list_vaults()`.

### Task 1.6: KG Schema Migration SQL Safety (TD-030)

**File:** `src/graph/knowledge_graph.py:296-317`

Replace f-string column interpolation with `safe_identifier()` validation before interpolation.

### Task 1.7: Permission Defaults Hardening (TD-042)

**Files:** `src/settings/settings_manager.py:304-319`, `src/server.py:162-171`

1. Change `_migrate_legacy_key()` to set `search_restricted: False`
2. Change open-mode permissions to exclude `search_restricted`
3. Log WARNING when legacy migration runs

### Task 1.8: CSRF Origin Check (TD-041)

**File:** `src/server.py` (new middleware)

Add lightweight CSRF middleware that validates `Origin` header on POST/DELETE requests — reject non-localhost origins.

### Task 1.9: Error Message Sanitization (TD-043)

**Files:** `src/api/v1_routes.py`, `src/api/settings_routes.py`

Replace `str(e)` in generic exception handlers with `"Internal server error"`. Keep detailed messages only for `CoreRagError` subclasses.

**Estimated Effort:** ~15 files, ~200 lines changed, ~20 new test assertions.

---

## 4. Wave 2: Async Correctness + Performance

**Goal:** Make the server genuinely concurrent. Eliminate unnecessary I/O.

**Tech Debt Items:** TD-017, TD-021, TD-024, TD-031, TD-032, TD-033, TD-034, TD-035, TD-038, TD-039, TD-040, TD-044, TD-045, TD-046, TD-049

### Task 2.1: asyncio.to_thread for Blocking I/O (TD-024)

**Files:** `src/mcp_server/server.py:136`, `src/search/hybrid_search.py:358-395`, `src/api/dashboard_routes.py:458`

1. `_embed_query()` — wrap `embed_query()` in `asyncio.to_thread()`
2. `_vector_search_on()`, `_fts_search_on()`, `_sparse_search_on()` — wrap `.to_list()` in `asyncio.to_thread()`
3. Single-item `execute_approved_item` — use `threading.Thread` (matching bulk path)

### Task 2.2: Shared LanceDB Connection + Table Cache (TD-031)

**Files:** `src/api/v1_routes.py`, `src/search/hybrid_search.py`

1. Route all API endpoints through `app.state.db` (fallback only when state unavailable)
2. Use `self.table` property in `_search_single()` for main DB
3. Add `_restricted_table` cached property for restricted DB

### Task 2.3: Tag Update via tbl.update() (TD-032)

**File:** `src/api/dashboard_routes.py:804-810`

Replace read-delete-reinsert with: `tbl.update(where=doc_filter, values={"tags": tags_str})`

### Task 2.4: Embedding Service Singleton (TD-033)

**File:** `src/executor.py:109,272`

Change `create_embedding_service()` to `get_embedding_service()` (two call sites).

### Task 2.5: Column Projections + count_rows (TD-034)

**File:** `src/api/v1_routes.py`

1. Stats/manifest: add `.select(["source_path"])` before `.to_arrow()`
2. Get document: use `ct.count_rows(doc_filter)` instead of loading all children

### Task 2.6: SQLite Connection Management (TD-035 + TD-017)

**Files:** `src/graph/knowledge_graph.py`, `src/catalog/catalog_manager.py`

**Write path (TD-035):** Refactor `add_from_extraction()` to use single `with sqlite3.connect() as conn:` for all entities and relationships. Apply same pattern to `CatalogManager` commit sequence.

**Read path (TD-017):** Convert all read methods (`get()`, `search()`, `get_exports()`, `get_stats()` in both `catalog_manager.py` and `knowledge_graph.py`) from manual `conn.close()` to `with sqlite3.connect(...) as conn:` context managers. This guarantees connection close on exception (~20 methods across both files).

### Task 2.7: file_size Before Archive (TD-038)

**File:** `src/executor.py:379-383`

Move `stat()` call before `archive_to_target()`.

### Task 2.8: Thread-Safe ResultCache (TD-039)

**File:** `src/search/hybrid_search.py:20-58`

Add `threading.Lock` to `_ResultCache.get()` and `put()`.

### Task 2.9: Fix catalog_search Tag Filter (TD-040)

**File:** `src/mcp_server/server.py:1092-1098`

Fix filter logic so `tags` param is not overwritten by `query`. Support multiple tags.

### Task 2.10: OrderedDict LRU Cache (TD-044)

**File:** `src/embeddings/embedding_service.py:112`

Replace `list` with `collections.OrderedDict` for O(1) LRU access ordering.

### Task 2.11: threading.Event for Commit Control (TD-045)

**File:** `src/api/dashboard_routes.py:60-61,138`

Replace module-level bool globals with `threading.Event` objects.

### Task 2.12: Exception Logging in Executor (TD-046)

**File:** `src/executor.py:316-322,366-371`

Add `logger.warning()` to both bare exception handlers with exception details.

### Task 2.13: SettingsManager Stat Debounce (TD-049)

**File:** `src/settings/settings_manager.py:294-302`

Add `time.monotonic()` check — re-stat file only every 5 seconds.

### Task 2.14: Verify Dual RAG End-to-End (TD-021)

**Verification step after Wave 2 code changes.** Since Wave 2 modifies `hybrid_search.py` (search fan-out, table caching) and Wave 1 modifies `executor.py` (PII redaction), verify the full dual RAG pipeline works:

1. Start server (`python -m src.server`)
2. Process a sensitive test document through the dashboard
3. Verify main RAG has redacted text, restricted RAG has unredacted text
4. Verify `search_scope="all"` fan-out returns results from both DBs with `source_db` field
5. Verify catalog tracks both `rag_doc_id` and `restricted_rag_doc_id`

Full verification steps are documented in `_DEV/TECH_DEBT.md` TD-021 (11-step checklist). This task marks TD-021 as resolved if verification passes.

**Estimated Effort:** ~14 files, ~400 lines changed (Wave 2 total, excluding verification).

---

## 5. Wave 3: Test Coverage

**Goal:** Add tests for security-critical and untested production modules.

**Tech Debt Items:** TD-036, TD-037

### Task 3.1: Security Module Tests (TD-036)

Create 3 new test files:

**`tests/test_path_validation.py`** (~20 tests):
- Path traversal attacks (`../../../etc/passwd`, `..%2f..%2f`)
- Symlink resolution, null bytes, Unicode normalization attacks
- Valid paths pass through

**`tests/test_query_sanitize.py`** (~15 tests):
- SQL injection payloads in filter strings
- `build_eq_clause()` with special characters
- `safe_identifier()` with reserved words
- Empty/None inputs

**`tests/test_secure_file.py`** (~10 tests):
- File creation with correct permissions (0o600/0o700)
- Permission verification on read, umask handling

### Task 3.2: API + Pipeline Tests (TD-037)

**`tests/test_settings_routes.py`** (~50 tests):
- Agent CRUD (create, read, update, delete)
- Permission updates (valid/invalid combinations)
- API key generation and validation
- Error handling (duplicate keys, missing agents, invalid permissions)
- Auth enforcement (require dashboard-only access)

**`tests/test_ingest_service.py`** (~30 tests):
- Dedup detection (unchanged vs changed content)
- Chunking pipeline (parent-child hierarchy)
- Embedding generation, table creation in new database
- Error handling (missing table, corrupt data)

### Task 3.3: Additional High-Value Tests

**`tests/test_hybrid_search_extended.py`** (~20 tests):
- `search()` end-to-end with mock LanceDB
- `search_scope` fan-out (main, restricted, all)
- Tag filtering, CRAG integration, cache hit/miss behavior

**Estimated Effort:** 6 new test files, ~145 new tests.

---

## 6. Wave 4: Documentation + Config + Cleanup

**Goal:** Align documentation with reality. Fix configuration drift.

**Tech Debt Items:** TD-047, TD-048, TD-050, TD-051

### Task 4.1: pyproject.toml Dependencies (TD-047)

Sync `[project.dependencies]` with packages from `requirements.txt`. Add all ~20 missing runtime packages with appropriate version bounds.

### Task 4.2: .env.example Update (TD-048)

1. Add 6 missing environment variables with defaults and comments
2. Update `CORERAG_API_KEY` comment to explain legacy migration
3. Align `ARCHIVE_PATH` default with `config.py`

### Task 4.3: Documentation Updates (TD-050)

1. **`_CATALOG/StartHere.md`:** Update test count (544 to current), P6 status (3% to 85.5%), `src/auth/` entry
2. **`_CATALOG/ARCHITECTURE.md`:** Add Restricted LanceDB to C4 container diagram
3. **`CLAUDE.md`:** Document Settings API endpoints, fix code_chunker claim
4. **`_DEV/DevPlan.md`:** Update Session 32/33 metrics

### Task 4.4: Misc Cleanup (TD-051)

1. Fix `validate_config()` GOOGLE_API_KEY warning — only warn if no provider is configured
2. Delete `tests/test_access_control.py` (orphaned — tests deprecated module)
3. Remove `hypothesis` from `requirements-dev.txt` (never imported)
4. Evaluate `AutoTagger.record_feedback()` TODO — remove if not planned

**Estimated Effort:** ~10 files, ~200 lines changed.

---

## 7. Success Criteria

### Wave 1 Complete When:
- All 9 security tasks pass manual verification
- No XSS possible from document content in dashboard
- PII redaction failure aborts commit (not silent fallback)
- Cold storage path validated against allowlist
- Gemini CLI uses stdin for prompts
- Security scanner passes on all changes

### Wave 2 Complete When:
- All async code paths have genuine `await` suspension points
- Tag update uses `tbl.update()` (no vector rewrite)
- Embedding model loaded once per server lifecycle
- All API routes use shared `app.state.db`
- Existing 693 tests still pass

### Wave 3 Complete When:
- 6 new test files created
- ~145 new tests passing
- Security modules have dedicated test coverage
- settings_routes.py and ingest_service.py tested

### Wave 4 Complete When:
- `pip install .` produces functional installation
- `.env.example` has all config variables
- All documentation reflects Session 33 state
- No orphaned tests or unused dev dependencies

---

## 8. Execution Order

Waves MUST run in order (1 then 2 then 3 then 4). Within each wave, tasks are independent and can be parallelized via subagent-driven development.

**Recommended parallelization:**
- Wave 1: Tasks 1.1-1.3 touch different files — can run parallel, then 1.4-1.9 parallel
- Wave 2: All 13 tasks independent — full parallel execution
- Wave 3: All 3 task groups independent — full parallel execution
- Wave 4: All 4 tasks independent — full parallel execution

**Estimated total:** ~40 files changed, ~800 lines modified, ~145 new tests, 4 waves.

---

## 9. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Async refactoring breaks MCP transport | Test MCP server after Wave 2 with Claude Desktop |
| XSS escaping breaks legitimate HTML in dashboard | Only escape user-data injection sites, not template HTML |
| CSRF middleware blocks legitimate dashboard calls | Origin check only rejects non-localhost origins |
| tbl.update() API differs between LanceDB versions | Verify against installed LanceDB version before deploying |
| Test count could exceed session token limits | Use subagent-driven development for Wave 3 |

---

*This specification was generated from a 5-agent parallel audit of the CoreRag codebase (Session 33, 2026-03-17). All findings are documented in `_DEV/TECH_DEBT.md` as TD-024 through TD-051.*

*Spec review: APPROVED by spec-document-reviewer agent. Fixes applied: finding count arithmetic (59→58), 5 pre-existing TDs added to out-of-scope, Wave 1 parallelization corrected, Wave 2 effort estimate increased.*
