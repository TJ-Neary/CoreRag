# P8 Sub-project 3: Dual RAG Database + Export Routing — Full Spec

**Date:** 2026-03-15
**Author:** Claude Opus 4.6 (Session 32)
**Status:** Approved (all sections reviewed by TJ)
**North Star:** A second brain with perfect memory and recall — privacy-controlled, only released when needed and approved.

---

## 1. Restricted RAG Database

**What:** A second LanceDB instance at `~/.corerag/lancedb-restricted/` for unredacted copies of sensitive documents.

**Schema:** Identical to main RAG — same `child_chunks` and `parent_chunks` tables, same BGE-M3 1024d embeddings, same parent-child chunking strategy. The only difference is the text content (unredacted vs redacted).

**Config:** Add `RESTRICTED_DB_PATH = STATE_DIR / "lancedb-restricted"` to `src/config.py`. Created on first use (lazy initialization, same pattern as main LanceDB).

**Content:** Original unredacted text with all PII intact. CUI_ prefix on filenames stored in this database. Documents in restricted RAG always have corresponding redacted versions in main RAG (unless the user explicitly unchecked main RAG).

**Initialization:** `IngestService` gets an optional `restricted_db` parameter. When provided and the document is sensitive, it runs the full enrichment pipeline (chunking, embedding, context prefixes, parent summaries) on the unredacted text.

---

## 2. Export Routing + Dashboard Checkboxes

### Default Export Logic

| Sensitivity | Main RAG | Restricted RAG | Obsidian | Archive |
|-------------|----------|---------------|----------|---------|
| Sensitive (auto or manual) | Checked (redacted) | Checked (unredacted) | Checked (redacted) | Always |
| Non-sensitive | Checked (original) | Unchecked | Checked | Always |

### Dashboard Checkbox Changes

Split the existing single "Send to RAG" checkbox into two:
- ☑ Main RAG (redacted if sensitive)
- ☑ Restricted RAG (unredacted, CUI_)

**Both checkboxes always visible** (even for non-sensitive docs). Non-sensitive docs default to Restricted unchecked, but the user can manually check it for any reason.

**When the "Mark as Sensitive" toggle changes:**
- Toggled ON → Restricted RAG auto-checks, CUI_ prefix applied
- Toggled OFF → Restricted RAG auto-unchecks (user can re-check manually)

### Executor Changes

**Critical sequencing:** Extract text BEFORE redaction. The restricted RAG must be indexed using unredacted text. The current executor already extracts text first (line ~215) then redacts (line ~235). Insert restricted indexing between extraction and main RAG indexing.

In `execute_approved_item()`:

```python
# 1. Extract text (already exists, line ~215)
original_text = extract_text(current_path)

# 2. Index in RESTRICTED RAG (unredacted) — BEFORE redaction
if not item.get("skip_restricted_rag", False) and is_sensitive:
    restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
    restricted_service = IngestService(embedding_service=embedder, db=restricted_db)
    restricted_service.ingest(original_text, metadata, source_path=..., skip_graph=True)
    catalog.record_export(doc_id, "restricted_rag", doc_id, redacted=False)
    catalog.update(doc_id, restricted_rag_doc_id=doc_id)

# 3. Redact text (already exists, line ~235)
if is_sensitive:
    export_text = _redact_pii(original_text, current_path.name)

# 4. Index in MAIN RAG (redacted) — existing behavior
```

**`skip_restricted_rag` transport:** The dashboard frontend sends `skip_restricted_rag: bool` in the `/api/update/{item_id}` request body (alongside existing `skip_rag` and `skip_obsidian`). Stored in the staging manifest item. Executor reads as `item.get("skip_restricted_rag", False)` — defaults to False (include in restricted) since sensitive docs should go to both by default.

**Cross-database document identity:** The `document_id` in LanceDB chunks is a SHA256 hash of the first 5000 chars of TEXT content. Since main RAG has redacted text and restricted RAG has unredacted text, the same document will have DIFFERENT `document_id` values. To enable cross-database deduplication during fan-out search, store the **catalog document ID** in each chunk's metadata as `catalog_id`. This is a new field on the `child_chunks` and `parent_chunks` schemas. The fan-out merge uses `catalog_id` (not `document_id`) to deduplicate across databases.

**IngestService usage:** Create a second `IngestService` instance with `db=restricted_db` (same constructor, different DB connection). Do NOT add `restricted_db` as a field on `IngestService` — keep instances single-purpose.

---

## 3. Search Fan-out

### `search_scope` Parameter

Added to: MCP `search_knowledge`, REST `/api/v1/search`, `HybridSearcher.search()`

Values: `"main"` | `"restricted"` | `"all"`

### Security Model — Main Only by Default

**Critical rule:** The restricted database must NEVER be automatically fed to any cloud LLM. All default search paths go through main RAG only.

| Consumer | Default scope | Reason |
|----------|--------------|--------|
| MCP tools (all agents) | `"main"` | Agents route through cloud LLMs |
| REST API `/api/v1/search` | `"main"` | Local agents may use cloud LLMs |
| Dashboard chat | `"main"` | Uses cloud LLM (claude-cli/Gemini/Anthropic) |
| Dashboard search widget | `"main"` | Results may be sent to chat LLM |
| CLI `search` command | `"main"` | Answer synthesis may use cloud LLM |
| Archive manager UI | Direct catalog access | No LLM in this path — shows document details directly |

**When restricted access is allowed:**
- Explicit `search_scope="restricted"` or `"all"` parameter in the request
- Only after RBAC is wired (SP5): ADMIN role + local-only provider verification
- Archive manager view (renders in browser, no LLM involved)

### Fan-out Implementation (when scope="all")

1. Query main RAG → scored results
2. Query restricted RAG → scored results
3. Merge by `document_id` — if same doc in both, prefer restricted version (has full text)
4. Re-sort by score, return top K
5. Each result includes `source_db: "main" | "restricted"` field

### HybridSearcher Changes

**Pre-existing bug:** `server.py` line 104 passes `embedder=embedding_service` to `HybridSearcher.__init__`, but the constructor only accepts `(db, table_name)`. The `embedder` kwarg is silently ignored. SP3 must fix this alongside adding `restricted_db`.

**Constructor change:**
```python
class HybridSearcher:
    def __init__(self, db, table_name: str = "child_chunks", restricted_db=None):
        self.db = db
        self.restricted_db = restricted_db
        # ... existing init ...
```

**New `_search_single()` method:** Extract the core search logic (vector search, BM25, RRF fusion, reranking) from the current `search()` method into a private method that operates on a single DB:

```python
async def _search_single(
    self, db, query: str, query_vector: list[float], k: int = 10,
    filters: dict | None = None, source_db: str = "main"
) -> list[SearchResult]:
    """Run hybrid search against a single LanceDB instance."""
    # ... moved from search(): vector search, BM25 FTS, RRF fusion, reranking ...
    # Set source_db on each SearchResult
```

**`SearchResult` dataclass change:** Add `source_db: str = "main"` field (optional, defaults to "main" for backward compatibility).

**`search_scope` in `search()` method:**
```python
async def search(self, query, query_vector, k=10, filters=None, search_scope="main", ...):
```

**Cache key must include `search_scope`:** The existing `_ResultCache._key()` hashes `query|k|filters`. Add `search_scope` to the key to prevent scope="main" results being returned for scope="restricted" queries. This is a security-critical fix.

**Fan-out merge (`_merge_results`):** Deduplicates by `catalog_id` (NOT by `document_id`, which differs between DBs). When the same document appears in both result sets, prefer the restricted version (has full text). Re-sort merged results by score, return top K.

### Server Lifespan Changes

**FastAPI (`src/server.py`):** Initialize restricted DB connection in lifespan:
```python
restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
searcher = HybridSearcher(db=main_db, restricted_db=restricted_db)
# Fix: remove the invalid embedder= kwarg from HybridSearcher construction
```

**MCP server (`src/mcp_server/server.py`):** Also initializes its own `HybridSearcher` at startup (line ~82). Must be updated to pass `restricted_db` as well.

**FTS index for restricted DB:** Call `ensure_fts_index()` lazily — only when the restricted DB is first queried and the table exists. At startup, the restricted DB may not have any tables yet (created on first sensitive commit). Do NOT call `ensure_fts_index()` at lifespan startup for restricted DB.

---

## 4. Catalog Integration

The `documents` table already has `restricted_rag_doc_id` (from SP1 schema). SP3 populates it.

**Export tracking:** When a document is committed to the restricted DB:
```python
catalog.record_export(ExportRecord(
    document_id=doc_id,
    destination="restricted_rag",
    path=doc_id,
    redacted=False,  # Restricted is always unredacted
))
catalog.update(doc_id, restricted_rag_doc_id=doc_id)
```

---

## 5. File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/config.py` | Modify | Add `RESTRICTED_DB_PATH` constant (env var overridable: `CORERAG_RESTRICTED_DB_PATH`) |
| `src/executor.py` | Modify | Dual-track commit: restricted (unredacted) before redaction, then main (redacted) |
| `src/search/hybrid_search.py` | Modify | `search_scope` param, `_search_single()` refactor, fan-out merge by `catalog_id`, `source_db` on SearchResult, cache key includes scope |
| `src/server.py` | Modify | Initialize restricted DB, pass to HybridSearcher, fix embedder= kwarg bug |
| `src/mcp_server/server.py` | Modify | `search_scope` param on `search_knowledge`, initialize restricted DB in MCP startup |
| `src/api/v1_routes.py` | Modify | `search_scope` parameter on REST search endpoint |
| `src/ingest_service.py` | Modify | Accept `catalog_id` param to store in chunk metadata |
| `src/chunking/parent_child.py` | Modify | Add `catalog_id` field to child_chunks and parent_chunks schemas |
| `src/ui/templates/dashboard.html` | Modify | Split RAG checkbox into Main RAG + Restricted RAG, add `skip_restricted_rag` to update payload |
| `src/cli/main.py` | No change | `search_scope` defaults to "main" via HybridSearcher default param — no CLI changes needed |
| `tests/test_hybrid_search.py` | Modify | Tests for fan-out search, scope parameter, cache key with scope |
| `tests/test_executor.py` | Modify | Tests for dual-track commit |

---

## 6. Success Criteria

1. Sensitive documents committed to both main (redacted) and restricted (unredacted) RAG databases
2. Non-sensitive documents committed to main RAG only (default)
3. Dashboard shows separate Main RAG / Restricted RAG checkboxes, both always visible
4. Sensitivity toggle auto-checks/unchecks Restricted RAG
5. User can override any checkbox regardless of sensitivity setting
6. `search_scope` parameter works on MCP, REST, and HybridSearcher
7. All default search paths use `"main"` scope only — no cloud LLM ever sees restricted content
8. Fan-out search (`scope="all"`) merges and deduplicates results correctly
9. Catalog tracks `restricted_rag_doc_id` and records restricted exports
10. Existing tests pass unchanged (dual DB is additive)

---

## 7. Forward Design Notes — For SP5 (Search Fan-out + Privacy Controls)

> **This section captures design decisions and requirements that SP5 must implement. It is NOT part of SP3 scope. It exists so that SP5 has full context without needing to re-discover these requirements.**

### 7a. Settings Tab in Dashboard UI

**What:** A new "Settings" tab in the dashboard (alongside Ingestion and Archive) for managing agent access controls, API keys, and role assignments.

**Why:** The dual RAG database (SP3) creates a real security boundary — restricted documents contain PII (SSNs, bank accounts, medical records). Without per-agent access controls, the only protection is the `search_scope` parameter defaulting to `"main"`. A Settings UI lets TJ explicitly configure which agents can access what, without editing YAML files.

**Features:**
1. **Agent/API Key Management** — list all configured API keys with their assigned roles
2. **Role Assignment** — per-key role selector (ADMIN, EDITOR, VIEWER)
3. **Per-Agent Search Scope Defaults** — override the default search scope for specific agents
   - e.g., Kendra → ADMIN (when using local Ollama only), Centaur → VIEWER (never sees restricted)
4. **LLM Provider Awareness** — display which provider each agent uses, flag if a restricted-access agent routes through a cloud LLM
5. **API Key Generation** — create new API keys with assigned roles from the UI

**Data source:** `~/.corerag/role_mappings.yaml` (already designed in TD-002). The Settings UI reads/writes this file.

**Backend:** New endpoints:
- `GET /api/settings/agents` — list agents with roles and scopes
- `POST /api/settings/agents` — update agent role/scope
- `POST /api/settings/agents/new` — generate new API key with role

### 7b. RBAC Enforcement (TD-002 Activation)

**What TD-002 provides:** `src/auth/access_control.py` with ADMIN/EDITOR/VIEWER roles, `get_role_for_key()` method. `role_mappings.yaml` config.

**What SP5 must wire:**
1. `verify_api_key()` in `src/server.py` resolves role from mapping, stores on `request.state.user_role`
2. Search endpoints check role before allowing `search_scope="restricted"` or `"all"`:
   - VIEWER → forced to `"main"`, cannot override
   - EDITOR → `"main"` default, can request `"all"` only if provider is local
   - ADMIN → `"all"` default, full access
3. MCP tools inherit role from transport (stdio = ADMIN by default)
4. **Provider check:** Before allowing restricted access, verify the LLM provider is local-only (Ollama). If `CORERAG_LLM_PROVIDER` is any cloud provider (claude-cli, gemini-cli, gemini, anthropic, codex-cli), block restricted scope even for ADMIN. Only Ollama is safe.

### 7c. Local Model Integration for Restricted Search

**What:** When a local LLM (Ollama qwen3:32b) is configured, allow the dashboard chat and CLI to access restricted content. The Settings UI should let TJ enable this per-feature:
- Dashboard chat → "Use local model for restricted search" toggle
- CLI search → `--local-only` flag enables restricted scope

**Why deferred to SP5:** Requires RBAC enforcement to be meaningful. Without role checks, any toggle would be a UI-only safety measure. SP5 wires the full security chain: role → scope → provider check → access.

### 7d. Dashboard System/Database Management Panel

**What:** Database status and management actions accessible from the dashboard UI (not from the menu bar icon — the menu icon stays simple: server status + open dashboard).

**Features:**
- Database status display: main DB (chunk count, size, last optimized) + restricted DB (chunk count, size)
- Actions: "Optimize Main DB" / "Optimize Restricted DB" / "Backup Both" / "Run Health Check"
- Quick stats: total documents, sensitive count, offline count
- Could live in the Settings tab (SP5) or as a "System" section in the existing dashboard

**Why deferred:** SP3 builds the restricted database. The management UI should come after both databases are operational and there's real data to manage. Settings tab (SP5) is the natural home since it will also have agent access controls and role management.

### 7e. Update TD-002 When SP5 Begins

TD-002 currently describes the RBAC scaffold and wiring plan. When SP5 begins, update TD-002 with:
- The `search_scope` parameter (from SP3) and how RBAC should default it per role
- The provider check requirement (cloud providers → forced main-only)
- The Settings UI endpoint specs (from 7a above)
- Agent-specific scope overrides from role_mappings.yaml
- Mark TD-002 as "In Progress" when SP5 starts, "Resolved" when wired

---

## 8. Retroactive Population

The existing 2 sensitive documents in the catalog should be re-processed through the restricted pipeline. This can be done via:
1. CLI: `python -m src.cli.main catalog list --sensitive` to identify them
2. Re-ingest those files (move back to inbox, re-process through pipeline)
3. Or a one-time script similar to `rebuild_catalog.py` that extracts text from main RAG chunks and re-indexes unredacted versions in restricted RAG

This is a small operation (2 files currently). As more sensitive documents are ingested going forward, they'll automatically go through the dual-track pipeline.
