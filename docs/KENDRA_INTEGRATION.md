# Kendra ↔ Core Memory Integration Guide

This document tells Kendra (or any AI building Kendra) exactly what to take from the PKM system, how to connect, and what responsibilities belong where.

---

## Architecture: Who Owns What

```
┌──────────────────────────────────────────────────────────┐
│                      KENDRA (Hub)                        │
│                                                          │
│  Owns: Chat, Voice, Personality, User Memory,            │
│        Skills, Routing, Session History, Mood             │
│                                                          │
│  Calls PKM for: Search, Ingest, Stats, Schema Info       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                  CORE MEMORY (PKM_v1)                    │
│                                                          │
│  Owns: Document Ingestion, RAG Index, PII Detection,     │
│        Chunking, Knowledge Graph, Quality Checks,        │
│        HITL Dashboard, Obsidian Export                    │
│                                                          │
│  Exposes: MCP Tools, REST API v1, Manifest Protocol      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Kendra is the user-facing brain. Core Memory is the knowledge engine.**

Kendra should never do its own document chunking, embedding, PII scanning, or vector indexing. All of that stays in Core Memory. Kendra talks to it through two interfaces.

---

## Two Connection Methods

Kendra currently has **two** ways to talk to Core Memory. Here's when to use each:

### 1. MCP Client (stdio) — `core/mcp_client.py`

**Use for:** Claude Desktop compatibility, tool composition, structured tool calls.

Already implemented. Launches PKM's MCP server as a subprocess and speaks JSON-RPC 2.0.

Available MCP tools:
| Tool | Purpose |
|------|---------|
| `search_knowledge` | Hybrid search (vector + BM25), reranking, HyDE, multi-query |
| `search_by_entity` | Knowledge graph traversal |
| `list_recent_files` | Recently modified vault files |
| `get_folder_structure` | Vault navigation |
| `get_system_status` | System health |
| `get_user_context` | User profile + facts *(Kendra should replace this — see below)* |
| `add_user_fact` | Store a fact about the user *(Kendra should own this)* |
| `check_stale_content` | Find outdated documents |
| `check_links` | Validate URLs in documents |
| `create_backup` | Trigger backup |
| `trigger_reindex` | Rebuild RAG index |
| `detect_conflicts` | Find contradictory information |

### 2. REST API v1 (HTTP) — `localhost:8000/api/v1/*`

**Use for:** Programmatic access, write operations, capability discovery.

Requires PKM's dashboard server to be running (`python -m src.server`).

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/manifest` | GET | **Call on startup** — returns database schema, capabilities, accepted formats, processing rules, live stats |
| `/api/v1/stats` | GET | Document count, chunk count, entity count, relationship count |
| `/api/v1/search` | POST | Semantic search with optional HyDE (`{"query": "...", "k": 5, "use_hyde": false}`) |
| `/api/v1/ingest` | POST | Push text content into the knowledge base (`{"content": "...", "source": "kendra", "metadata": {...}}`) |
| `/api/v1/documents/{id}` | DELETE | Remove a document and all its chunks |

---

## Manifest Protocol — Call This on Startup

When Kendra connects to Core Memory, it should call the manifest endpoint to learn the database schema and capabilities. This replaces hardcoding assumptions about the database.

```python
# In Kendra's startup sequence
async def discover_core_memory():
    """Call manifest to learn Core Memory's capabilities."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/api/v1/manifest")
        manifest = resp.json()

    # Now Kendra knows:
    # - manifest["schema"]["embedding_model"]          → "all-MiniLM-L6-v2"
    # - manifest["schema"]["embedding_dimensions"]     → 384
    # - manifest["schema"]["chunking_strategy"]        → "parent-child (512/2048)"
    # - manifest["capabilities"]["search_features"]    → ["hybrid", "hyde", "reranking", ...]
    # - manifest["accepted_formats"]["file_types"]     → ["pdf", "docx", "md", ...]
    # - manifest["processing"]["pii_detection"]        → True
    # - manifest["stats"]                              → {"documents": 43, "chunks": 4704, ...}

    return manifest
```

If the manifest call fails (server not running), fall back to MCP client for search-only operations.

---

## What Kendra Should Take From PKM

### 1. RAG-Augmented Chat Pattern

PKM's `/api/chat` endpoint (server.py:507-584) shows the pattern Kendra should use. Key pieces:

**Query → Embed → Search → Build Context → LLM Call**

```python
# Simplified version of what PKM does (server.py lines 522-553)
# Kendra should replicate this logic in its own chat handler

# 1. Embed the user's query
query_vector = embedder.embed_query(user_message)

# 2. Search Core Memory's child_chunks table
results = table.search(query_vector).limit(5).to_list()

# 3. Build context from results
context_chunks = [r["content"] for r in results]
sources = [r["source_path"] for r in results]

# 4. Inject into system prompt
system_prompt = (
    soul_md_content +  # Kendra's personality (PKM doesn't have this)
    "\n\nRetrieved from your knowledge base:\n" +
    "\n---\n".join(context_chunks)
)
```

**What Kendra adds that PKM doesn't:**
- `soul.md` personality injection
- Mood system modifying tone
- Conversation history from `kendra_memory.db` (not just the current session)
- Fact extraction after each interaction
- Skill routing (search vs chat vs action)

**Recommendation:** Kendra should use the **REST API** (`POST /api/v1/search`) for RAG retrieval instead of the direct import in `rag_memory.py`. This decouples the projects and lets Core Memory handle embedding/search internally. The direct import approach works but creates a tight coupling to PKM's internal module structure.

```python
# Instead of importing HybridSearcher directly, use the API:
async def search_knowledge_base(query: str, k: int = 5) -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "http://localhost:8000/api/v1/search",
            json={"query": query, "k": k}
        )
        return resp.json().get("results", [])
```

### 2. Write-Back: Saving Kendra's Knowledge to Core Memory

Kendra can push content into Core Memory via the ingest API. Use cases:
- Save conversation summaries as searchable documents
- Store skill outputs (research results, generated content)
- Archive voice session transcripts

```python
async def save_to_core_memory(content: str, source: str, metadata: dict = None):
    """Push content from Kendra into the knowledge base."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "http://localhost:8000/api/v1/ingest",
            json={
                "content": content,
                "source": source,  # e.g., "kendra-chat-summary", "kendra-skill-output"
                "metadata": metadata or {}
            }
        )
        return resp.json()
```

### 3. User Memory — Kendra Should Be the Single Source of Truth

**Current state:** Both systems store user facts separately.
- PKM: `~/.pkm/profiles/default.json` (EpisodicMemoryManager)
- Kendra: `data/kendra_memory.db` SQLite (facts table)

**Recommendation:** Kendra owns user memory. PKM's user-facts endpoints (`/api/user-facts`) become read-only consumers of whatever Kendra knows. Eventually, Kendra should expose its own facts API that PKM (and other tools) can call.

For now, Kendra's `MemoryManager` is the right place for this. It already has:
- Episodic memory (interaction log)
- Semantic memory (fact extraction with entity/relation/value triples)
- Conversation context retrieval

PKM's `EpisodicMemoryManager` and `get_user_context` MCP tool can be deprecated once Kendra is the primary interface.

---

## Database Schema Reference

Kendra doesn't need to know the internal schema for normal operations (the API abstracts it). But for context when building features:

### LanceDB Tables (`~/.pkm/lancedb/`)

**`child_chunks`** — the main search table
| Column | Type | Description |
|--------|------|-------------|
| `content` | string | Chunk text (~512 tokens) |
| `vector` | float32[384] | all-MiniLM-L6-v2 embedding |
| `document_id` | string | Parent document hash |
| `source_path` | string | Original file path |
| `chunk_index` | int | Position within parent |
| `parent_id` | string | Links to parent_chunks |
| `section_title` | string | Section heading if available |

**`parent_chunks`** — larger context chunks
| Column | Type | Description |
|--------|------|-------------|
| `content` | string | Parent text (~2048 tokens) |
| `document_id` | string | Document hash |
| `source_path` | string | Original file path |
| `metadata` | JSON string | Category, year, tags, etc. |

### Knowledge Graph (`~/.pkm/knowledge_graph.db` — SQLite)

| Table | Columns | Description |
|-------|---------|-------------|
| `entities` | id, name, type, document_id, confidence | 979 entities |
| `relationships` | id, source_id, target_id, relation_type, document_id | 165 relationships |

Accessible via MCP tool `search_by_entity` or direct SQLite read.

### Kendra's Memory (`data/kendra_memory.db` — SQLite)

| Table | Columns | Description |
|-------|---------|-------------|
| `interactions` | id, timestamp, user_query, kendra_response, mood, context_used, metadata | Episodic log |
| `facts` | id, entity, relation, value, confidence, timestamp, source_interaction_id | Semantic facts |

---

## Port Conflict Note

Both projects default to port 8000:
- PKM dashboard: `localhost:8000`
- Kendra API server: `0.0.0.0:8000`

**Resolution options:**
1. Change Kendra's API port in `config.yaml` → `port: 8001`
2. Change PKM's dashboard port via environment variable
3. Don't run both servers simultaneously (use MCP for PKM access when Kendra's server is active)

Option 1 is simplest. Kendra's `config.yaml` already has the port setting.

---

## Migration Path

### Phase 1: Now (No Code Changes Needed)

Kendra already works with Core Memory via MCP. Keep both chat systems running. Use:
- PKM dashboard for document review (approve/edit/skip ingested files)
- Kendra for conversational access to the knowledge base

### Phase 2: Kendra Uses REST API

Replace `modules/rag_memory.py` direct imports with HTTP calls to `/api/v1/search`. This removes the `sys.path.insert` hack and the tight coupling to PKM's internal modules.

Add manifest call to Kendra's startup sequence.

Add write-back calls for conversation summaries and skill outputs.

### Phase 3: Kendra Owns User Memory

Deprecate PKM's `/api/user-facts` and `get_user_context` MCP tool. Kendra's `MemoryManager` becomes the single source of truth for user facts, preferences, and interaction history.

If PKM needs user context (e.g., for PII detection customization), it calls Kendra's API instead.

### Phase 4: Unified Memory Layer (Future)

Long-term: Kendra exposes its own MCP server that other tools can connect to. Core Memory becomes one of several knowledge sources Kendra orchestrates.

---

## Summary: What Goes Where

| Feature | Owner | Notes |
|---------|-------|-------|
| Document ingestion pipeline | Core Memory | Watchdog, processing, PII, staging |
| HITL review dashboard | Core Memory | Approve/edit/skip UI |
| RAG index (LanceDB) | Core Memory | Chunking, embedding, indexing |
| Knowledge graph | Core Memory | Entity extraction, relationships |
| Obsidian export | Core Memory | Markdown generation, backlinks |
| Quality tools (dupes, stale, links) | Core Memory | Exposed via MCP |
| **Chat / conversation** | **Kendra** | Personality, mood, history |
| **Voice interaction** | **Kendra** | STT, TTS, wake word |
| **User memory / facts** | **Kendra** | Episodic + semantic |
| **Skill execution** | **Kendra** | Resume builder, notes, etc. |
| **Intent routing** | **Kendra** | Search vs chat vs skill |
| **Session tracking** | **Kendra** | Interaction log |
| Search API | Core Memory | Kendra calls it |
| Ingest API | Core Memory | Kendra writes to it |
| Manifest protocol | Core Memory | Kendra reads on startup |

---

*This document lives in PKM_v1 at `docs/KENDRA_INTEGRATION.md`. Copy to Kendra's project or reference directly.*
