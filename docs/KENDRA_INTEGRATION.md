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

## How Kendra Should Use RAG

This is the most important section. It explains **when** and **how** Kendra should pull context from Core Memory during conversations.

### The Problem with the Current Router

Kendra's router (`core/router.py`) currently has a binary decision:
- User says "search for X" → **SEARCH** route → calls `rag_memory.search()` → returns raw results
- Everything else → **CHAT** route → sends to LLM with **no RAG context**

This means when the user asks "what are the key concepts in FMLA?" it goes to chat mode and the LLM answers from its training data, completely ignoring the FMLA documents sitting in Core Memory. PKM's chat endpoint (`/api/chat`) always checks RAG. Kendra should too.

### The Fix: Always-On RAG for Chat

Every chat message should attempt a RAG lookup. The results determine how the LLM responds.

```
User Input
    ↓
[Router] → SEARCH | SKILL | CHAT
    ↓
If SEARCH or CHAT:
    ↓
[Query Core Memory] → POST /api/v1/search
    ↓
Results found?
    ├─ YES → Inject context + sources into LLM prompt
    └─ NO  → LLM answers from its own knowledge (no hallucination about your docs)
    ↓
[LLM generates response]
    ↓
[Log interaction + extract facts]
```

The difference between SEARCH and CHAT with RAG:
- **SEARCH**: User explicitly asked to find something. Show sources prominently. Return multiple results.
- **CHAT with RAG**: User asked a question. Silently augment the LLM's answer with your documents. Cite sources naturally.

### Implementation: RAG-Augmented Chat

This replaces the current flow where `OllamaClient.generate()` is called without context.

```python
# In Kendra's chat handler (controller.py or wherever chat is orchestrated)

async def handle_chat(user_message: str, history: list) -> str:
    """Process a chat message with automatic RAG augmentation."""

    # 1. Always search Core Memory for relevant context
    rag_context = ""
    sources = []

    try:
        results = await search_core_memory(user_message, k=5)

        if results:
            # Build context string from top results
            context_parts = []
            for r in results:
                content = r.get("content", "")
                source = r.get("source", "unknown")
                score = r.get("score", 0)

                # Only include results above a relevance threshold
                if score >= 0.3:
                    context_parts.append(content)
                    if source not in sources:
                        sources.append(source)

            if context_parts:
                rag_context = "\n\n---\n\n".join(context_parts)

    except Exception as e:
        logger.warning(f"RAG lookup failed, proceeding without context: {e}")

    # 2. Generate LLM response with context injected
    response = await llm_client.generate(
        prompt=user_message,
        context=rag_context if rag_context else None,
        # system_prompt loaded from soul.md automatically
    )

    # 3. Log the interaction (with what context was used)
    memory_manager.log_interaction(
        user_query=user_message,
        response=response,
        context=rag_context[:500] if rag_context else None,
        metadata={"sources": sources, "rag_used": bool(rag_context)}
    )

    # 4. Extract facts in background
    memory_manager.extract_facts_from_interaction(user_message, response)

    return response
```

### Calling Core Memory: Preferred Method

Use the REST API instead of direct imports. This decouples the projects.

```python
import httpx

# Core Memory base URL — should come from config.yaml
CORE_MEMORY_URL = "http://localhost:8000"

async def search_core_memory(query: str, k: int = 5, use_hyde: bool = False) -> list:
    """Search Core Memory's knowledge base."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{CORE_MEMORY_URL}/api/v1/search",
                json={"query": query, "k": k, "use_hyde": use_hyde}
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])
    except httpx.ConnectError:
        logger.debug("Core Memory server not running, skipping RAG")
    except Exception as e:
        logger.warning(f"Core Memory search failed: {e}")
    return []
```

**Fallback chain**: If the REST API is unavailable (server not running), fall back to MCP client. If MCP is also unavailable, proceed without RAG context.

```python
async def search_with_fallback(query: str, k: int = 5) -> list:
    """Try REST API first, fall back to MCP, then proceed without."""
    # Try REST API
    results = await search_core_memory(query, k)
    if results:
        return results

    # Fall back to MCP
    try:
        mcp = get_mcp_client()
        mcp_result = await mcp.search_knowledge(query=query, k=k)
        if mcp_result and "content" in str(mcp_result):
            return parse_mcp_search_results(mcp_result)
    except Exception:
        pass

    return []  # No RAG context available
```

### When to Use Each Search Mode

Core Memory supports several search strategies. Kendra should pick the right one based on the query:

| Query Type | Search Strategy | Example |
|------------|----------------|---------|
| Simple factual | Standard search (`k=5`) | "What is FMLA?" |
| Complex / multi-part | HyDE expansion (`use_hyde=true`) | "How do compensation strategies relate to retention?" |
| Entity-specific | Knowledge graph (`search_by_entity` MCP tool) | "What documents mention OSHA?" |
| Broad topic | Multi-query (via MCP `use_multi_query=true`) | "Tell me everything about employee benefits" |
| Recent files | `list_recent_files` MCP tool | "What did I add recently?" |

**Heuristic for choosing automatically:**

```python
def choose_search_strategy(query: str) -> dict:
    """Pick search params based on query characteristics."""
    words = query.split()

    # Short, direct queries — standard search
    if len(words) <= 5:
        return {"k": 5, "use_hyde": False}

    # Questions with "how" or "why" or "relate" — HyDE helps
    if any(w in query.lower() for w in ["how", "why", "relate", "compare", "explain"]):
        return {"k": 5, "use_hyde": True}

    # "Everything about X" — more results
    if any(w in query.lower() for w in ["everything", "all about", "comprehensive"]):
        return {"k": 10, "use_hyde": True}

    # Default
    return {"k": 5, "use_hyde": False}
```

### Formatting RAG Context for the LLM

How Kendra injects retrieved documents into the prompt matters. The current `OllamaClient.generate()` already accepts a `context` parameter that prepends to the prompt. The format should be:

```python
def format_rag_context(results: list) -> str:
    """Format search results for LLM context injection."""
    if not results:
        return ""

    parts = []
    for i, r in enumerate(results, 1):
        source = r.get("source", "unknown")
        # Extract just the filename from the full path
        source_name = source.split("/")[-1] if "/" in source else source
        content = r.get("content", "")
        parts.append(f"[Source {i}: {source_name}]\n{content}")

    return (
        "The following excerpts were retrieved from the user's personal knowledge base. "
        "Use them to inform your answer. Cite sources by name when relevant. "
        "If the excerpts don't contain the answer, say so — don't make things up.\n\n"
        + "\n\n---\n\n".join(parts)
    )
```

### Citing Sources in Responses

Kendra should cite sources naturally in voice and text:

- **Voice mode**: "According to your FMLA document, eligible employees get up to 12 weeks..."
- **Text mode**: "Based on *Benefits and Non-Monetary Rewards.pdf*, the key categories are..."

The `sources` list from search results provides filenames. Pass these to the LLM in the context so it can reference them.

### Handling No Results

When RAG returns nothing relevant, the LLM should be honest:

```python
# In the system prompt or context injection:
if not rag_context:
    # No context injection — LLM uses its own knowledge
    # Kendra's soul.md already says "if unsure, say so"
    pass
else:
    # Context found — LLM should prefer it over training data
    context = format_rag_context(results)
```

The soul.md instruction "Never make up information — if unsure, say so" handles this, but you can reinforce it:

```
If the retrieved documents don't answer the question, tell the user:
"I don't have anything on that in your knowledge base, but here's what I know..."
```

This lets Kendra still be helpful with general knowledge while being transparent about what came from the user's documents vs the LLM's training.

---

## Write-Back: Saving Kendra's Knowledge to Core Memory

Kendra can push content into Core Memory via the ingest API. Use cases:
- Save conversation summaries as searchable documents
- Store skill outputs (research results, generated content)
- Archive voice session transcripts

```python
async def save_to_core_memory(content: str, source: str, metadata: dict = None):
    """Push content from Kendra into the knowledge base."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{CORE_MEMORY_URL}/api/v1/ingest",
                json={
                    "content": content,
                    "source": source,  # e.g., "kendra-chat-summary", "kendra-skill-output"
                    "metadata": metadata or {}
                }
            )
            return resp.json()
    except Exception as e:
        logger.warning(f"Failed to save to Core Memory: {e}")
        return None
```

### What to Write Back

| Content | Source Tag | When |
|---------|-----------|------|
| Conversation summary | `kendra-chat-summary` | End of long conversation or daily summary |
| Skill output | `kendra-skill-{name}` | After skill execution (e.g., web search results) |
| Voice transcript | `kendra-voice-session` | End of voice session |
| Learned facts | `kendra-fact` | When high-confidence facts are extracted |
| User corrections | `kendra-correction` | When user corrects Kendra's understanding |

### Don't Write Back

- Every individual chat message (too noisy, fills the index)
- The user's raw queries (privacy — keep in Kendra's local memory only)
- Duplicate content already in Core Memory

---

## User Memory — Kendra Should Be the Single Source of Truth

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
