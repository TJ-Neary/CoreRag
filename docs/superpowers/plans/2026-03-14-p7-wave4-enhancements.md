# P7 Wave 4: Database Evolution, Enhancements & Strategic Improvements

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strategic improvements: 3-way hybrid search with sparse vectors, semantic entity discovery, search result caching, code file chunker, CoreRagTools decomposition, dashboard route splitting, manifest pruning, dependency lock file, and minor fixes.

**Architecture:** Each task is independent and cherry-pickable. No task depends on another except 4.1 (sparse vectors) which requires re-embedding. Items are ordered by impact: search quality first, then code quality, then ops/maintenance.

**Tech Stack:** Python 3.12+, LanceDB, FlagEmbedding (new dep for 4.1), sentence-transformers, FastMCP, FastAPI

**Spec:** `docs/superpowers/specs/2026-03-14-p7-codebase-evolution-design.md` (Wave 4)

**Note:** Any new tech debt discovered during implementation that isn't fixed immediately must be documented in `_DEV/DevPlan.md` and `_DEV/TECH_DEBT.md`.

---

## MANDATORY: Review Corrections (Read Before Implementing)

### Important (3 issues)

1. **Task 1 (Sparse vectors):** LanceDB does NOT have native sparse vector search. `BGEM3FlagModel` returns `lexical_weights` as `list[dict[int, float]]` (token IDs, not terms). The implementer must research LanceDB's current sparse capabilities before starting. On Apple Silicon (MPS), use `use_fp16=False` — `use_fp16=True` requires CUDA. Consider storing sparse vectors for future use and implementing a custom dot-product scoring layer, OR defer this task until LanceDB adds sparse support.

2. **Task 4 (Decomposition):** Missing 2 methods from the map — `detect_conflicts` → QualityTools, `trigger_reindex` → MaintenanceTools. Also, 10+ tool handlers are implemented directly in `server.py` (not via CoreRagTools): `check_stale_content`, `check_links`, `find_duplicates`, `get_database_health`, `optimize_database`, `create_backup`, `list_backups`, `list_tags`, `manage_tags`, `answer_question`. These stay in `server.py` — they are NOT part of this decomposition.

3. **Task 3 (Semantic entity discovery):** `get_all_entities()` does NOT exist on KnowledgeGraph — must be created (simple SQL: `SELECT DISTINCT name, type, confidence_score, mention_count FROM entities`). Also: use `get_neighbors(entity_name)` not `get_entity_relationships(entity_name)`. The LanceDB path should come from `config.DB_PATH`, not string-replacing `knowledge_graph.db`.

### Minor (5 issues)

4. **Task 7 (Code chunker):** `chunk_python()` drops trailing module-level code after the last definition (e.g., `if __name__ == "__main__":` blocks). Add a capture for lines after the last node's `end_lineno`.
5. **Task 9 (Lock file):** `pip-compile` requires `pip-tools` — run `pip install pip-tools` first. Already installed this session.
6. **Task 4:** Plan says "13 injected dependencies" — actual count is 11 (9 constructor + 2 post-init).
7. **Task 4:** 3 methods in Search group (`get_document`, `get_related_documents`, `get_context_for_topic`) have no `@mcp.tool()` registration — they're dead code candidates.
8. **Task 1:** `answer_question` handler stays in `server.py` — it calls `SearchTools.search_knowledge()` after refactor.

---

## File Map

| File | Action | Task | Responsibility |
|------|--------|------|---------------|
| `src/embeddings/embedding_service.py` | Modify | 4.1 | Add sparse vector support via FlagEmbedding |
| `src/search/hybrid_search.py` | Modify | 4.1, 4.2 | 3-way RRF fusion, result caching |
| `src/chunking/parent_child.py` | Modify | 4.1 | Add `sparse_vector` to child schema |
| `scripts/migrate_embeddings.py` | Modify | 4.1 | Support sparse vector migration |
| `requirements.txt` | Modify | 4.1 | Add FlagEmbedding |
| `src/analytics/semantic_cache.py` | Modify | 4.2 | Add result-level TTL cache |
| `src/graph/knowledge_graph.py` | Modify | 4.3 | Add `search_entities_semantic()` |
| `src/mcp_server/tools.py` | Split | 4.4 | → search_tools.py, memory_tools.py, maintenance_tools.py, quality_tools.py, graph_tools.py |
| `src/mcp_server/search_tools.py` | Create | 4.4 | SearchTools class |
| `src/mcp_server/memory_tools.py` | Create | 4.4 | MemoryTools class |
| `src/mcp_server/maintenance_tools.py` | Create | 4.4 | MaintenanceTools class |
| `src/mcp_server/quality_tools.py` | Create | 4.4 | QualityTools class |
| `src/mcp_server/graph_tools.py` | Create | 4.4 | GraphTools class |
| `src/api/dashboard_batch.py` | Create | 4.5 | Batch processing routes |
| `src/api/dashboard_memory.py` | Create | 4.5 | Memory/analytics routes |
| `src/api/dashboard_chat.py` | Create | 4.5 | Chat route |
| `src/staging.py` | Modify | 4.6 | Add `cleanup_manifest()` |
| `src/chunking/code_chunker.py` | Create | 4.7 | AST-aware Python chunking + line-based fallback |
| `src/extractor.py` | Modify | 4.7 | Wire code file types |
| `src/auth/access_control.py` | Modify | 4.8 | Wire into server routes |
| `src/server.py` | Modify | 4.8 | Add RBAC middleware |
| `requirements.lock` | Create | 4.9 | Reproducible installs |
| `src/api/v1_routes.py` | Modify | 4.10 | Fix private method access |
| `src/graph/knowledge_graph.py` | Modify | 4.10 | Add public `extract_sync()` |
| `src/executor.py` | Modify | 4.11 | Deduplicate VersionManager |
| `src/mcp_server/server.py` | Modify | 4.12 | Move local `time` import to top |

---

## Chunk 1: Search Quality (Tasks 1-3)

### Task 1: BGE-M3 Sparse Vectors for 3-Way Hybrid Search (Spec 4.1)

**Prerequisite:** Install FlagEmbedding: `pip install FlagEmbedding` and add to `requirements.txt`.

**Note:** `sentence-transformers` SentenceTransformer does NOT expose BGE-M3 sparse output. Must use `FlagEmbedding.BGEM3FlagModel` which provides `model.encode(texts, return_sparse=True)` returning both dense and sparse vectors.

**Files:**
- Modify: `requirements.txt` (add `FlagEmbedding>=1.2.0`)
- Modify: `src/embeddings/embedding_service.py`
- Modify: `src/search/hybrid_search.py`
- Modify: `scripts/migrate_embeddings.py`

- [ ] **Step 1: Add FlagEmbedding dependency**

```bash
pip install FlagEmbedding
echo "FlagEmbedding>=1.2.0" >> requirements.txt
```

- [ ] **Step 2: Extend EmbeddingService to support sparse output**

Add a method `embed_documents_with_sparse(texts) -> tuple[list[list[float]], list[dict]]` that returns both dense vectors and sparse weight dicts. Use `BGEM3FlagModel` when the model is `BAAI/bge-m3`, fallback to dense-only for other models.

Key implementation:
```python
def embed_documents_with_sparse(self, texts: list[str]) -> tuple[list, list]:
    """Return (dense_vectors, sparse_vectors) for BGE-M3."""
    if "bge-m3" not in self.model_name.lower():
        return self.embed_documents(texts), [{}] * len(texts)

    from FlagEmbedding import BGEM3FlagModel
    # Use cached model or create new
    if not hasattr(self, "_flag_model"):
        self._flag_model = BGEM3FlagModel(self.model_name, use_fp16=True)

    output = self._flag_model.encode(texts, return_dense=True, return_sparse=True)
    return output["dense_vecs"].tolist(), output["lexical_weights"]
```

- [ ] **Step 3: Add sparse_vector column to child_chunks schema**

In `src/chunking/parent_child.py`, add `sparse_vector` as an optional dict field to the child chunk schema. This is used during table creation — existing tables get the column added via migration.

- [ ] **Step 4: Implement 3-way RRF fusion in HybridSearcher**

Add `_sparse_search()` method alongside `_vector_search()` and `_fts_search()`. Modify `_reciprocal_rank_fusion` to accept 3 result lists. The search method becomes:

```python
vector_results = await self._vector_search(query_vector, k*3, filters)
fts_results = await self._fts_search(query, k*3, filters)
sparse_results = await self._sparse_search(query_sparse, k*3, filters)
return self._reciprocal_rank_fusion_3way(
    vector_results, fts_results, sparse_results,
    weights=(0.5, 0.2, 0.3),  # dense, BM25, sparse
)
```

- [ ] **Step 5: Extend migrate_embeddings.py for sparse vectors**

Add `--include-sparse` flag. When set, uses `embed_documents_with_sparse()` and writes both `vector` and `sparse_vector` columns.

- [ ] **Step 6: Run migration**

```bash
python scripts/migrate_embeddings.py --include-sparse --dry-run
python scripts/migrate_embeddings.py --include-sparse
```

- [ ] **Step 7: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass. New sparse features don't affect existing tests (sparse is additive).

- [ ] **Step 8: Commit**

```bash
git add requirements.txt src/embeddings/embedding_service.py src/search/hybrid_search.py src/chunking/parent_child.py scripts/migrate_embeddings.py
git commit -m "feat: 3-way hybrid search with BGE-M3 sparse vectors (dense + sparse + BM25)"
```

---

### Task 2: Search Result Caching with TTL (Spec 4.2)

**Files:**
- Modify: `src/search/hybrid_search.py` or `src/analytics/semantic_cache.py`

- [ ] **Step 1: Add result cache to HybridSearcher**

Add an LRU cache with TTL keyed by `(query_hash, k, filters_hash)`:

```python
from functools import lru_cache
import hashlib
import time

class _ResultCache:
    """TTL-based search result cache."""
    def __init__(self, max_size: int = 128, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[float, list]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def _key(self, query: str, k: int, filters: dict | None) -> str:
        raw = f"{query}|{k}|{sorted(filters.items()) if filters else ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, query: str, k: int, filters: dict | None) -> list | None:
        key = self._key(query, k, filters)
        if key in self._cache:
            ts, results = self._cache[key]
            if time.time() - ts < self._ttl:
                return results
            del self._cache[key]
        return None

    def put(self, query: str, k: int, filters: dict | None, results: list):
        key = self._key(query, k, filters)
        if len(self._cache) >= self._max_size:
            # Evict oldest
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (time.time(), results)

    def invalidate(self):
        self._cache.clear()
```

- [ ] **Step 2: Wire cache into `search()` method**

At the top of `search()`: check cache. At the bottom: store in cache. Add `invalidate()` call in `post_ingestion_index_update()`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_hybrid_search.py -v --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/search/hybrid_search.py
git commit -m "feat: add TTL-based search result caching (5-min TTL, 128 entries)"
```

---

### Task 3: Semantic Entity Discovery in Knowledge Graph (Spec 4.3)

**Files:**
- Modify: `src/graph/knowledge_graph.py`
- New LanceDB table: `entity_vectors`

- [ ] **Step 1: Add entity embedding method to KnowledgeGraph**

```python
def build_entity_index(self, embedding_service) -> int:
    """Embed all entity names+descriptions into a LanceDB table for semantic search."""
    entities = self.get_all_entities()  # Existing method
    if not entities:
        return 0

    texts = [f"{e['name']}: {e.get('type', '')}" for e in entities]
    vectors = embedding_service.embed_documents(texts)

    data = [
        {"id": e["name"], "type": e.get("type", ""), "vector": v, "mention_count": e.get("mention_count", 1)}
        for e, v in zip(entities, vectors)
    ]

    import lancedb
    db = lancedb.connect(str(self.db_path).replace("knowledge_graph.db", "lancedb"))
    try:
        db.drop_table("entity_vectors")
    except Exception:
        pass
    db.create_table("entity_vectors", data)
    return len(data)
```

- [ ] **Step 2: Add semantic entity search method**

```python
def search_entities_semantic(self, query: str, embedding_service, k: int = 10) -> list[dict]:
    """Find entities semantically related to query, then traverse graph from those starting points."""
    query_vector = embedding_service.embed_query(query)

    import lancedb
    db = lancedb.connect(str(self.db_path).replace("knowledge_graph.db", "lancedb"))

    if "entity_vectors" not in db.table_names():
        return []

    table = db.open_table("entity_vectors")
    results = table.search(query_vector).limit(k).to_list()

    # For each found entity, get its graph neighbors
    enriched = []
    for r in results:
        entity_name = r["id"]
        neighbors = self.get_entity_relationships(entity_name)
        enriched.append({
            "entity": entity_name,
            "type": r.get("type", ""),
            "similarity": 1.0 - r.get("_distance", 0),
            "relationships": neighbors,
        })

    return enriched
```

- [ ] **Step 3: Add MCP tool for semantic entity search**

Add `search_entities_semantic` tool to MCP server that calls the new method.

- [ ] **Step 4: Run tests**

Run: `pytest --tb=short -q`

- [ ] **Step 5: Commit**

```bash
git add src/graph/knowledge_graph.py src/mcp_server/server.py
git commit -m "feat: semantic entity discovery — vector search over knowledge graph entities"
```

---

## Chunk 2: Code Quality (Tasks 4-5)

### Task 4: Decompose CoreRagTools God Object (Spec 4.4)

**Files:**
- Modify: `src/mcp_server/tools.py` (extract from)
- Create: `src/mcp_server/search_tools.py`
- Create: `src/mcp_server/memory_tools.py`
- Create: `src/mcp_server/maintenance_tools.py`
- Create: `src/mcp_server/quality_tools.py`
- Create: `src/mcp_server/graph_tools.py`
- Modify: `src/mcp_server/server.py` (compose tool groups)

**Decomposition map** (from the 19 methods in CoreRagTools):

| Group | Class | Methods | Dependencies |
|-------|-------|---------|--------------|
| Search | `SearchTools` | `search_knowledge`, `get_document`, `list_recent_files`, `get_folder_structure`, `get_related_documents`, `get_context_for_topic` | retriever, embedder, reranker, db, hyde_expander, semantic_cache, conversation_manager, query_analytics |
| Memory | `MemoryTools` | `get_user_context`, `add_user_fact` | memory_manager, user_profile |
| Graph | `GraphTools` | `search_by_entity` | knowledge_graph, embedder |
| Quality | `QualityTools` | `analyze_knowledge_gaps`, `get_golden_suggestions`, `approve_golden_suggestion`, `list_golden_entries`, `get_ingestion_queue` | db, query_analytics |
| Maintenance | `MaintenanceTools` | `get_document_history`, `get_document_diff`, `restore_document_version`, `list_vaults`, `list_integrations`, `sync_integration` | db, vault_root |

- [ ] **Step 1: Create each tool group file**

For each group, create a new file in `src/mcp_server/` with a class that receives only its needed dependencies. Move the method bodies unchanged. Example for `search_tools.py`:

```python
class SearchTools:
    def __init__(self, retriever, embedder, reranker, db, hyde_expander=None,
                 semantic_cache=None, conversation_manager=None, query_analytics=None):
        self.retriever = retriever
        # ... store deps

    async def search_knowledge(self, query, k=5, ...):
        # ... exact same body as current CoreRagTools.search_knowledge
```

- [ ] **Step 2: Update server.py to compose tool groups**

Replace single `CoreRagTools(...)` initialization with individual group constructors. Each MCP tool handler calls the appropriate group:

```python
_search_tools: SearchTools | None = None
_memory_tools: MemoryTools | None = None
# etc.

@mcp.tool()
async def search_knowledge(...):
    if not _search_tools:
        return {"error": "Search tools not initialized"}
    return await _search_tools.search_knowledge(...)
```

- [ ] **Step 3: Keep CoreRagTools as a thin facade (optional)**

For backward compatibility, `CoreRagTools` can become a composition class that delegates to the individual groups. This prevents breaking any code that instantiates `CoreRagTools` directly.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mcp_tools.py -v --tb=short`
Expected: All pass (behavior unchanged, only organization changed).

- [ ] **Step 5: Commit**

```bash
git add src/mcp_server/
git commit -m "refactor: decompose CoreRagTools into 5 domain-specific tool groups"
```

---

### Task 5: Split dashboard_routes.py (Spec 4.5)

**Files:**
- Modify: `src/api/dashboard_routes.py` (extract from)
- Create: `src/api/dashboard_batch.py`
- Create: `src/api/dashboard_memory.py`
- Create: `src/api/dashboard_chat.py`

**Route distribution:**

| File | Routes | Count |
|------|--------|-------|
| `dashboard_routes.py` (keep) | Batch control, commit, progress, RAG browser, tags, folders, corrections, status | ~20 |
| `dashboard_batch.py` | Start analysis, batch processing, file upload | ~5 |
| `dashboard_memory.py` | Memory CRUD, analytics, feedback, golden set | ~8 |
| `dashboard_chat.py` | Chat endpoint | ~1 |

- [ ] **Step 1: Extract each group into its own router factory**

Each new file exports a `create_<group>_router(db_path, ...)` function returning a FastAPI `APIRouter`.

- [ ] **Step 2: Mount sub-routers in dashboard_routes.py**

```python
def create_dashboard_router(...):
    router = APIRouter()
    router.include_router(create_batch_router(...))
    router.include_router(create_memory_router(...))
    router.include_router(create_chat_router(...))
    # ... remaining routes stay in this file
    return router
```

- [ ] **Step 3: Run tests**

Run: `pytest --tb=short -q`

- [ ] **Step 4: Commit**

```bash
git add src/api/
git commit -m "refactor: split dashboard_routes.py into batch, memory, and chat sub-routers"
```

---

## Chunk 3: Features & Ops (Tasks 6-8)

### Task 6: Staging Manifest Pruning (Spec 4.6)

**Files:**
- Modify: `src/staging.py`
- Modify: `src/server.py` (call on startup)

- [ ] **Step 1: Add `cleanup_manifest()` to staging.py**

```python
def cleanup_manifest(keep_statuses: list[str] | None = None, archive_dir: Path | None = None) -> int:
    """Remove completed/error items from manifest. Optionally archive to a file."""
    if keep_statuses is None:
        keep_statuses = ["pending", "processing", "approved"]

    archive_path = archive_dir or (config.STATE_DIR / "manifest_archive")
    archive_path.mkdir(parents=True, exist_ok=True)

    def _cleanup(manifest):
        to_archive = {k: v for k, v in manifest.items() if v.get("status") not in keep_statuses}
        if to_archive:
            # Archive to monthly file
            month = datetime.now().strftime("%Y-%m")
            archive_file = archive_path / f"manifest_{month}.json"
            existing = {}
            if archive_file.exists():
                existing = json.loads(archive_file.read_text())
            existing.update(to_archive)
            archive_file.write_text(json.dumps(existing, indent=2))

            # Remove from manifest
            for k in to_archive:
                del manifest[k]
        return len(to_archive)

    return _load_modify_save(_cleanup)
```

- [ ] **Step 2: Call on server startup**

In `src/server.py` lifespan, add:
```python
from src.staging import cleanup_manifest
pruned = cleanup_manifest()
if pruned:
    logger.info(f"Staging manifest: pruned {pruned} completed items")
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_staging.py -v --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/staging.py src/server.py
git commit -m "feat: auto-prune completed items from staging manifest on startup"
```

---

### Task 7: Code File Chunker (Spec 4.7)

**Files:**
- Create: `src/chunking/code_chunker.py`
- Modify: `src/extractor.py`

- [ ] **Step 1: Create code_chunker.py**

```python
"""AST-aware chunking for Python files, line-based fallback for other languages."""
import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb"}
AST_EXTENSIONS = {".py"}  # Only Python gets AST parsing

@dataclass
class CodeChunk:
    content: str
    start_line: int
    end_line: int
    kind: str  # "function", "class", "module", "block"
    name: str  # function/class name or ""

def chunk_python(source: str) -> list[CodeChunk]:
    """Split Python source at function/class boundaries."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_by_lines(source)

    chunks = []
    lines = source.splitlines(keepends=True)

    # Get top-level definitions
    nodes = [n for n in ast.iter_child_nodes(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    if not nodes:
        return chunk_by_lines(source)

    # Add module-level code before first definition
    if nodes[0].lineno > 1:
        content = "".join(lines[:nodes[0].lineno - 1]).strip()
        if content:
            chunks.append(CodeChunk(content, 1, nodes[0].lineno - 1, "module", ""))

    for node in nodes:
        end = getattr(node, "end_lineno", node.lineno + 10)
        content = "".join(lines[node.lineno - 1:end]).strip()
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        chunks.append(CodeChunk(content, node.lineno, end, kind, node.name))

    return chunks if chunks else chunk_by_lines(source)

def chunk_by_lines(source: str, chunk_size: int = 60, overlap: int = 10) -> list[CodeChunk]:
    """Line-based chunking with overlap for non-Python files."""
    lines = source.splitlines(keepends=True)
    chunks = []
    for i in range(0, len(lines), chunk_size - overlap):
        chunk_lines = lines[i:i + chunk_size]
        content = "".join(chunk_lines).strip()
        if content:
            chunks.append(CodeChunk(content, i + 1, i + len(chunk_lines), "block", ""))
    return chunks

def chunk_code(source: str, extension: str) -> list[CodeChunk]:
    """Route to appropriate chunker based on file extension."""
    if extension in AST_EXTENSIONS:
        return chunk_python(source)
    return chunk_by_lines(source)
```

- [ ] **Step 2: Wire into extractor.py**

Add code file extensions to the extractor's file type routing. When a `.py`, `.js`, `.ts`, `.go`, `.rs` file is detected, use `chunk_code()` to split it, then return the combined text for the standard chunking pipeline.

Find the file type detection in `extractor.py` and add:
```python
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb"}

if suffix in CODE_EXTENSIONS:
    return content  # Return raw text — code_chunker handles structure
```

- [ ] **Step 3: Run tests**

Run: `pytest --tb=short -q`

- [ ] **Step 4: Commit**

```bash
git add src/chunking/code_chunker.py src/extractor.py
git commit -m "feat: code file chunker — AST-aware Python + line-based fallback for JS/TS/Go/Rust"
```

---

### Task 8: Wire RBAC Scaffold (Spec 4.8)

**Files:**
- Modify: `src/auth/access_control.py`
- Modify: `src/server.py`
- Modify: `src/api/v1_routes.py`

**Note:** Only activate when role mappings are configured. No-op for current single-user deployment.

- [ ] **Step 1: Read current AccessControl scaffold**

Read `src/auth/access_control.py` to understand the existing Role/User model and PII filtering logic.

- [ ] **Step 2: Add role resolution from API key**

Add a method to AccessControl that maps API keys to roles:
```python
def get_role_for_key(self, api_key: str) -> Role:
    """Look up role for API key. Returns ADMIN if no mappings configured."""
    if not self._role_mappings:
        return Role.ADMIN  # Single-user default
    return self._role_mappings.get(api_key, Role.VIEWER)
```

Role mappings loaded from `~/.corerag/role_mappings.yaml` (gitignored).

- [ ] **Step 3: Wire into verify_api_key**

Modify `src/server.py:verify_api_key` to resolve role and store on request state:
```python
request.state.user_role = access_control.get_role_for_key(api_key)
```

- [ ] **Step 4: Add PII filtering to search results**

In search endpoints, check `request.state.user_role`. If VIEWER, filter results that have `is_sensitive=True`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_v1_routes.py -v --tb=short`

- [ ] **Step 6: Commit**

```bash
git add src/auth/access_control.py src/server.py src/api/v1_routes.py
git commit -m "feat: wire RBAC scaffold — role-based PII filtering on search results"
```

---

## Chunk 4: Quick Wins (Tasks 9-12)

### Task 9: Dependency Lock File (Spec 4.9)

**Files:**
- Create: `requirements.lock`

- [ ] **Step 1: Generate lock file**

```bash
pip-compile requirements.txt -o requirements.lock --no-header
```

- [ ] **Step 2: Commit**

```bash
git add requirements.lock
git commit -m "chore: add requirements.lock for reproducible installs"
```

---

### Task 10: Fix Private Method Access in API Route (Spec 4.10)

**Files:**
- Modify: `src/graph/knowledge_graph.py`
- Modify: `src/api/v1_routes.py`

- [ ] **Step 1: Add public `extract_sync()` method**

In `src/graph/knowledge_graph.py`, add to `EntityExtractor`:
```python
def extract_sync(self, text: str, document_id: str) -> tuple[list, list]:
    """Synchronous wrapper for entity extraction using regex patterns."""
    return self._extract_with_patterns(text, document_id)
```

- [ ] **Step 2: Update API route**

In `src/api/v1_routes.py`, find `extractor._extract_with_patterns(...)` and replace with `extractor.extract_sync(...)`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_v1_routes.py -v --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/graph/knowledge_graph.py src/api/v1_routes.py
git commit -m "fix: replace private _extract_with_patterns call with public extract_sync()"
```

---

### Task 11: Deduplicate VersionManager Instantiation (Spec 4.11)

**Files:**
- Modify: `src/executor.py`

- [ ] **Step 1: Find the duplicate**

Search for `VersionManager()` in `src/executor.py`. There should be two instantiations in `execute_approved_item()`.

- [ ] **Step 2: Reuse single instance**

Create the instance once before the first use, reuse for the second.

- [ ] **Step 3: Commit**

```bash
git add src/executor.py
git commit -m "fix: reuse single VersionManager instance in execute_approved_item"
```

---

### Task 12: Move Local Imports to Top Level (Spec 4.12)

**Files:**
- Modify: `src/mcp_server/server.py`

- [ ] **Step 1: Find local `import time` statements**

```bash
grep -n "import time" src/mcp_server/server.py
```

- [ ] **Step 2: Move to top-level imports**

Remove `import time as _time` from inside function bodies. Add `import time` at the top of the file if not already there. Replace `_time.time()` calls with `time.time()`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_mcp_tools.py -v --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/mcp_server/server.py
git commit -m "fix: move local time imports to module level"
```

---

## Chunk 5: Fix IngestService Import Bug + Tech Debt Update

### Task 13: Fix IngestService entity_extractor import path

**Files:**
- Modify: `src/ingest_service.py`

- [ ] **Step 1: Already fixed**

The import was corrected earlier this session from `src.graph.entity_extractor` to `src.graph.knowledge_graph`.

- [ ] **Step 2: Commit the fix**

```bash
git add src/ingest_service.py
git commit -m "fix: correct EntityExtractor import path in IngestService"
```

---

### Task 14: Update Tech Debt + DevPlan

**Files:**
- Modify: `_DEV/TECH_DEBT.md`
- Modify: `_DEV/DevPlan.md`

- [ ] **Step 1: Mark resolved items**

After completing Wave 4 items, mark the corresponding TD entries as resolved:
- TD-007 through TD-013 (whichever were addressed)

- [ ] **Step 2: Update P7 roadmap in DevPlan.md**

Update Wave 4 status from "Pending" to "Complete" with session reference.

- [ ] **Step 3: Commit**

```bash
git add _DEV/TECH_DEBT.md _DEV/DevPlan.md
git commit -m "docs: update tech debt and roadmap for P7 Wave 4 completion"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --tb=short -q`
Expected: 623+ tests pass, no regressions.

- [ ] **Verify search quality improvement**

If Task 1 (sparse vectors) was executed, run a comparison search to verify 3-way fusion returns different results than 2-way.

---

## Summary

| Task | Spec | Category | Effort | Files |
|------|------|----------|--------|-------|
| 1 | 4.1 | Search quality | High | 4 files + new dep |
| 2 | 4.2 | Search quality | Low | 1 file |
| 3 | 4.3 | Search quality | Medium | 2 files |
| 4 | 4.4 | Code quality | Medium | 7 files (split) |
| 5 | 4.5 | Code quality | Medium | 4 files (split) |
| 6 | 4.6 | Operations | Low | 2 files |
| 7 | 4.7 | Feature | Medium | 2 files |
| 8 | 4.8 | Security | Medium | 3 files |
| 9 | 4.9 | Operations | Trivial | 1 file |
| 10 | 4.10 | Code quality | Trivial | 2 files |
| 11 | 4.11 | Code quality | Trivial | 1 file |
| 12 | 4.12 | Code quality | Trivial | 1 file |
| 13 | — | Bug fix | Trivial | 1 file |
| 14 | — | Documentation | Low | 2 files |

**Total: 14 tasks. Cherry-pickable. Estimated 2-3 sessions for all items.**

**Recommended execution order for maximum impact:**
1. Quick wins first: Tasks 9-13 (30 min)
2. Search quality: Tasks 2, 3 (1 hour)
3. Code quality: Tasks 4, 5 (1-2 hours)
4. Features: Tasks 6, 7 (1 hour)
5. Sparse vectors: Task 1 (dedicated session — needs FlagEmbedding research)
6. RBAC: Task 8 (when multi-user is needed)
