# Ecosystem Integration — CoreRag

> This project participates in TJ's multi-project ecosystem, coordinated via MCP (Model Context Protocol) servers and a shared coordination layer.

---

## Architecture Overview

The ecosystem is a network of independent Python projects that communicate through MCP tools over stdio transport. Each project maintains its own App Track (standalone product) and optionally an Integration Track (MCP server that exposes project capabilities to other projects).

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Project A   │     │  Project B   │     │  Project C   │
│  (App Track) │     │  (App Track) │     │  (App Track) │
│  ┌─────────┐ │     │  ┌─────────┐ │     │  ┌─────────┐ │
│  │MCP Srvr │◄├─────├─►│MCP Srvr │◄├─────├─►│MCP Srvr │ │
│  └─────────┘ │     │  └─────────┘ │     │  └─────────┘ │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                   ┌────────▼────────┐
                   │    hq-coord     │
                   │  (coordination) │
                   └─────────────────┘
```

### Key Principles

1. **Leaf Module Rule** — The Integration Track (`src/mcp_server/server.py`) imports FROM core project code. Nothing in core imports from it. Delete the MCP server → project still works.
2. **stdio Transport** — All MCP servers use stdio (not HTTP). No ports consumed, no network exposure.
3. **Graceful Degradation** — If a dependent service is offline, degrade gracefully. Never hard-fail because an ecosystem service is unavailable.

---

## This Project's Integration Track

**MCP Server:** `src/mcp_server/server.py`
**Tests:** `tests/test_mcp_tools.py`

### Registered MCP Tools (30)

CoreRag exposes 30 tools via FastMCP over stdio transport:

| Category | Tools | Description |
|----------|-------|-------------|
| Search | `search_knowledge`, `search_by_entity`, `answer_question` | Hybrid vector+BM25 search, knowledge graph entity search, citation-backed answers |
| Ingestion | `ingest_content`, `get_document`, `delete_document` | Document lifecycle management |
| Quality | `check_links`, `find_duplicates`, `check_freshness`, `detect_conflicts` | Content quality tools |
| Memory | `get_user_context`, `add_user_fact` | Episodic memory for user context |
| Analytics | `get_query_analytics`, `get_search_patterns` | Search usage insights |
| Maintenance | `health_check`, `optimize_db`, `create_backup` | System operations |
| Tags | `list_tags`, `search_by_tag` | Collection tag management |
| Graph | `graph_stats`, `graph_query`, `graph_path` | Knowledge graph exploration |
| Integrations | `list_plugins`, `sync_plugin` | External data source integration |

### Tool Naming Convention

```
corerag_<verb>_<noun>
```

### Required Tools

| Tool | Purpose | Status |
|------|---------|--------|
| `get_manifest` | Returns version, available tools, capabilities (JSON) | Exposed via REST `/api/v1/manifest` |
| `search_knowledge` | Primary query tool — hybrid search with CRAG filtering | Active |
| `health_check` | Health and readiness check | Active |

---

## App Track — REST API

CoreRag also exposes an HTTP API on **port 8000** (registered in HQ Port Registry):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/manifest` | Capability discovery (no auth required) |
| `POST /api/v1/search` | Semantic search with tag/category filtering |
| `POST /api/v1/ingest` | Content ingestion |
| `GET /api/v1/stats` | Database statistics |
| `POST /api/v1/answer` | Citation-backed answer synthesis |
| `GET /api/v1/documents/{id}` | Document metadata |
| `DELETE /api/v1/documents/{id}` | Document deletion |
| `POST /api/v1/documents/bulk-delete` | Bulk document deletion |

Authentication: `X-API-Key` header (set `CORERAG_API_KEY` in `.env`). Manifest endpoint is always public.

---

## Cross-Project Communication

### Inbound Connections (Other Projects → CoreRag)

| Consumer | Interface | Purpose |
|----------|-----------|---------|
| Kendra | MCP (stdio) + REST API | Knowledge base queries, document ingestion |
| Claude Desktop | MCP (stdio) | 30 tools for knowledge management |

### Outbound Connections (CoreRag → Other Projects)

CoreRag does not initiate connections to other projects. It is a service provider only.

### HQ Coordination Server (hq-coord)

A shared MCP server at `~/Tech_Projects/_HQ/scripts/hq_mcp_server.py` provides coordination tools:

| Tool | Purpose |
|------|---------|
| `read_scratchpad` / `write_scratchpad` | Inter-agent working notes |
| `read_board` / `post_message` / `respond_message` | Cross-project message board |
| `read_session_memory` / `append_session_memory` | Session continuity |
| `create_task` / `claim_task` / `update_task` / `list_tasks` | Work Bus task lifecycle |
| `acquire_lock` / `release_lock` | Advisory file locking |
| `check_agents` | See which agents are active |

---

## Key References

| Document | Location | Purpose |
|----------|----------|---------|
| Dual-Track Standard | `~/Tech_Projects/_HQ/standards/DUAL_TRACK.md` | App Track vs Integration Track architecture |
| Port Registry | `~/Tech_Projects/_HQ/standards/PORT_REGISTRY.md` | Port assignments (MCP uses stdio, but REST APIs need ports) |
| MCP Integration Guide | `~/Tech_Projects/_HQ/guides/universal/MCP_INTEGRATION.md` | FastMCP patterns, error handling, testing |
| Composer Protocol | `~/Tech_Projects/_HQ/guides/universal/COMPOSER_PROTOCOL.md` | Inter-agent dispatch and routing |
| HQ Coordination PRD | `~/Tech_Projects/_HQ/projects/prd_hq_mcp_server.md` | Full hq-coord tool specifications |

---

*Generated by HQ ecosystem template on 2026-03-14*
