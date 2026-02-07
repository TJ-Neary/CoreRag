# DevPlan.md — CoreRag Development Plan

> **Purpose**: Single source of truth for CoreRag's development history, current status, architectural decisions, integration protocols, and future roadmap.
> Consolidates content from 8 previously separate planning files (now archived in `_project/Archive/`).
>
> **Last Updated**: 2026-02-06

---

## Table of Contents

1. [Project Timeline](#project-timeline)
2. [Key Decisions & Findings](#key-decisions--findings)
3. [Wiring Plan Status](#wiring-plan-status)
4. [External Integration Protocol](#external-integration-protocol)
5. [Episodic Memory Design Reference](#episodic-memory-design-reference)
6. [Future Roadmap](#future-roadmap)
7. [Known Issues & Discrepancies](#known-issues--discrepancies)
8. [Project Audit & Improvement Plan](#project-audit--improvement-plan)
9. [Open Questions](#open-questions)
10. [Archived Files Index](#archived-files-index)

---

## Project Timeline

**Started**: 2026-01-31 | **Status**: Post-Integration — Wiring Complete | **Sessions**: 15

| Session | Date | Focus | Key Outcomes |
|---------|------|-------|-------------|
| 0-1 | Jan 31 | Scaffold | 44 modules created across 23 dirs by Antigravity agents. None wired. |
| 2 | Feb 1 | Phase 1: MCP Server | Rewrote server.py for stdio + FastMCP. Wired HybridSearcher, EmbeddingService, Reranker. Created CLAUDE.md. |
| 3 | Feb 1 | Intelligence Rewrite | Split-brain Ollama workflow (JSON + text in separate calls). 41/41 summaries. Found 6 PII false positives. |
| 4 | Feb 1 | Test Suite Rewrite | 12 tests across integration, HITL, rules. All 27 passing. |
| 5 | Feb 1 | Second Batch + RAG Verify | 41/41 completed, 0 errors, 0 PII FP. 4702 child chunks, 52 parent chunks. RAG char ratio 0.9533. |
| 6 | Feb 1 | PII Redesign | Three-layer detection: Presidio + custom dictionary + LLM advisory. Manual override on dashboard. 0 false positives. |
| 7 | Feb 1 | Phase 2: Search Stack | Wired HyDE, time-decay scoring, multi-query with RRF fusion. Fixed HyDE bug. |
| 8 | Feb 1 | MCP Desktop + Claude Review | Fixed Claude Desktop connection. Audited RAG (43 docs, 4704 chunks). Claude generated Phase 6 + Roadmap docs. |
| 9 | Feb 1 | Phases 3-12 Completion | Knowledge graph backfill (979 entities, 165 relationships). Chat window + memory panel on dashboard. Audio/video wired. All 12 phases complete. |
| 10 | Feb 1 | End-to-End Verification | All module imports verified. 29 dashboard routes confirmed. All 27 tests passing. |
| 11 | Feb 1 | Post-Integration Enhancements | 42 new tests (69 total). PII CLI, embedding auto-tagger, LLM entity extraction, conflict detector MCP, Obsidian backlinks, QueueManager, VLM captioner. |
| 12 | Feb 1 | Tests, RAG API, Manifest | 52 new tests (121 total). Core Memory API v1 (5 endpoints). Auto-tagger tuning. VLM model downloaded. |
| 13 | Feb 1 | Tags, Menu Bar, Config, CLI | Collection tags system. macOS menu bar app. SPHR data migration. MCP wiring batch. Config centralization. CLI expansion to 13 commands. |
| 14 | Feb 2-4 | Security Hardening & Dead Code Cleanup | Query sanitization, path validation, secure file ops, API authentication, Pydantic models. Deleted 12 orphaned files. Pre-commit hooks. 182 tests. StartHere.md created. |
| 15 | Feb 6 | Wiring Completion & Cleanup | Wired exceptions.py (15 files), logging_config.py (4 entry points), retry.py (API call sites). Async migration (intelligence.py → httpx). Config consolidation (EMBEDDING_MODEL centralized). Fixed broken __init__.py imports. Deleted remaining orphaned files (code_chunker, citations, collections, coreragignore). Cleaned empty packages. 177 tests passing. |

### Metrics at Session 15

- **Tests**: 177 passing, 26 skipped (golden set)
- **CLI commands**: 13
- **MCP tools**: 19
- **RAG**: 4,702 child chunks + 52 parent chunks from 43 documents
- **Knowledge graph**: 979 entities, 165 relationships
- **Security**: API auth, path validation, query sanitization, secure file permissions
- **Custom exceptions**: CoreRagError hierarchy wired into 15 files
- **Async**: intelligence.py uses httpx async for all LLM calls
- **Config**: All model names and paths centralized in config.py

---

## Key Decisions & Findings

### Architectural Decisions

| Date | Decision | Rationale | Outcome |
|------|----------|-----------|---------|
| Jan 31 | LanceDB for vector storage | Embedded, handles TB scale, no server process | Running — 4702 child chunks |
| Jan 31 | FastMCP for MCP server | Python-native, stdio transport for Claude Desktop | Running — 20+ tools |
| Jan 31 | Local-first with hybrid option | Privacy priority, allow API fallback for speed | Architecture pattern |
| Jan 31 | SafeProcessor for memory mgmt | Prevent OOM on M4 Max 48GB | Reliable batch processing |
| Feb 1 | Ollama qwen2.5:32b as default LLM | 100% metadata quality locally, no need for paid API | Cost/privacy win |
| Feb 1 | Split-brain intelligence workflow | Single call couldn't reliably produce JSON + full text | Quality: 0% → 100% |
| Feb 1 | Three-layer PII detection | LLM false positives on HR topic words; Presidio is source of truth | Accuracy: 6 FP → 0 FP |
| Feb 1 | Custom PII dictionary (YAML) | User-specific terms Presidio can't detect | Full coverage |
| Feb 1 | all-MiniLM-L6-v2 for embeddings | Already wired; nomic-embed was in original plan but MiniLM works | Pragmatic — can migrate later |
| Feb 1 | Tag naming: `study-` prefix | Groups by activity across topics (`study-sphr`, `study-pmp`) | Convention established |
| Feb 1 | Comma-delimited tags in LanceDB | `LIKE '%,tag,%'` filtering; simple and compatible | Working across all interfaces |

### Technology Decisions (Validated)

| Component | Planned | Actual | Status |
|-----------|---------|--------|--------|
| Vector DB | LanceDB | LanceDB | Running — 4702 child chunks, 52 parent chunks |
| Embeddings | nomic-embed-text-v1.5 (768d) | all-MiniLM-L6-v2 (384d) | Running — migration possible later |
| LLM | Gemini or local | Ollama qwen2.5:32b | Running — 100% metadata quality |
| MCP | FastMCP | FastMCP (stdio) | Running — Claude Desktop connected |
| PII | Presidio | Presidio + custom dictionary + LLM advisory | Running — 0 false positives |
| Reranker | cross-encoder | ms-marco-MiniLM-L-6-v2 | Running |
| HyDE | Ollama-backed | Ollama qwen2.5:32b | Wired (fixed bug) |
| Audio | mlx-whisper | mlx-whisper | Wired in extractor.py |
| OCR | Vision.framework | Vision.framework | Wired in extractor.py |
| Collection Tags | — | Comma-delimited in LanceDB | Working — MCP, REST, CLI, dashboard |
| Menu Bar | — | rumps macOS app | Working — status polling, dashboard launch |
| Config | Scattered env vars | Centralized config.py | Working — all model names and paths centralized |

### Integration Findings

These findings emerged during actual integration work, not theoretical planning.

#### 1. LLM Can't Reliably Produce Both JSON + Full Text in One Call
**Problem**: Single Ollama call asked to return JSON metadata AND full redacted document text. The model would truncate text, omit JSON fields, or produce malformed output.
**Solution**: Split-brain workflow in `intelligence.py` — Call 1: structured JSON only; Call 2: full redacted text with `===START===`/`===END===` delimiters.
**Result**: 0/41 → 41/41 summaries (100% metadata quality).

#### 2. LLM PII Detection Produces False Positives on Topic Words
**Problem**: LLM flagged 6/41 files as containing PII because they were HR guides mentioning "salary", "medical leave" — topic words, not actual PII.
**Solution**: Three-layer PII detection — Presidio (pattern-based) is source of truth, LLM provides advisory only, custom dictionary for user-specific terms.
**Result**: 0 false positives on re-run.

#### 3. No Need for Paid API — Local Ollama Sufficient
Evaluated Gemini API free tier (2 RPM, 32K TPM). Ollama with qwen2.5:32b achieved 100% metadata quality. No quality benefit from external API, plus privacy concern sending documents to Google.

#### 4. Embedding Model Mismatch
Original plan: nomic-embed-text-v1.5 (768d). Actual: all-MiniLM-L6-v2 (384d) was already wired. Kept it — migration can happen later if needed.

#### 5. HyDE Expander Bug
`tools.py` passed the `HyDEResult` dataclass object as the search query string instead of extracting `.hypothetical_document`. Silently broken — embedding a string representation of a Python object. Fixed.

#### 6. RAG Verification Shows 95%+ Coverage
After ingesting 41 documents: avg char ratio 0.9533, word coverage 0.9535. Two "bad" entries are test artifacts, not real failures.

#### 7. Batch Processing Memory Safety
Batch processor pauses at 92% RAM, resumes at 88%. SafeProcessor pauses at 75%, resumes at 65%. `gc.collect()` between files. 41-file batch ran ~19 min with no memory issues.

#### 8. LanceDB FTS Index Breaks on Delete+Re-Add
After migrating data by deleting all rows and re-adding, the full-text search index was silently broken. Solution: rebuild with `replace=True`.

#### 9. Phases Were Already Complete Without Realizing It
Phases 3 (OCR), 10 (multimodal), and most of Phase 2 were already fully wired in `extractor.py` and `tools.py` before we checked. Always verify current state before planning.

#### 10. Config Centralization — Pragmatic vs Complete
Centralized ~6 most-used constants in `config.py` and updated key entry points. Left ~30 utility files with `Path.home() / ".corerag"` defaults — they use `or` fallback patterns, so they still work. Complete migration can happen incrementally.

#### 11. Tag Convention Matters Early
Initially `sphr-study` (topic-first) but user wants `study-sphr` (action-first prefix). Had to rename in 4,696+ LanceDB rows. Establish naming conventions before populating data.

### Performance Observations

| Operation | Measurement | Notes |
|-----------|-------------|-------|
| 41-file batch analysis | ~19 minutes | Ollama qwen2.5:32b, 2 calls per file |
| RAG indexing (41 files) | ~15 minutes | 4702 child chunks + 52 parent chunks |
| Single file processing | ~25-30 seconds | Extraction + AI analysis + staging |
| Dashboard load | <1 second | FastAPI + Jinja2 |
| Peak RAM during batch | ~85% | Paused once, resumed automatically |

---

## Wiring Plan Status

### 12-Phase Plan

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Fix MCP Server (stdio + FastMCP) | **Complete** |
| — | PII Redesign (3-layer detection) | **Complete** |
| 2 | Wire Search Stack (HyDE, decay, multi-query) | **Complete** |
| 3 | Wire OCR into ingestion | **Complete** (already wired in extractor.py) |
| 4 | Wire auto-tagging | **Complete** |
| 5 | Wire knowledge graph | **Complete** |
| 6 | Wire episodic memory | **Complete** (handed off to external AI) |
| 7 | Wire quality modules | **Complete** |
| 8 | Wire utility modules | **Complete** |
| 9 | Wire analytics & queue | **Complete** |
| 10 | Wire multimodal | **Complete** (already wired in extractor.py) |
| 11 | Config cleanup & dead code removal | **Complete** |
| 12 | CLI integration | **Complete** (13 commands) |

### Remaining Work

All 12 phases are **complete** as of Session 15.

**Phase 8 (utility modules)** — **Complete**:
- [x] ~~Wire `src/utils/health.py` defaults to import from config~~ — **Done** (Session 15)
- [x] ~~Wire `src/utils/checkpoint.py` defaults to import STATE_DIR from config~~ — **Done** (Session 15)
- [x] ~~Wire `src/utils/incremental.py`~~ — **Deleted** (orphaned, never used)
- [x] ~~Wire `src/utils/feedback.py`~~ — **Deleted** (orphaned, never used)
- [x] ~~Evaluate and remove dead utility code~~ — **Complete** (12 files deleted in Session 14, 4 more in Session 15)
- [x] ~~Wire `src/utils/logging_config.py` into entry points~~ — **Done** (Session 15: server.py, mcp_server/server.py, cli/main.py, watchdog.py)
- [x] ~~Wire `src/utils/retry.py` into API call sites~~ — **Done** (Session 15: intelligence.py, search, embeddings)

**Phase 11 (config cleanup)** — **Complete**:
- [x] ~~Config consolidation~~ — **Complete** (Session 15): EMBEDDING_MODEL, RERANKER_MODEL centralized. All model name defaults reference config.py.
- [x] ~~Remove orphaned modules~~ — **Complete**: Deleted `src/ingestion/pipeline.py`, `src/ingestion.py`, `src/storage/__init__.py`, `src/processors/spreadsheet_processor.py`, `src/sync/reconciliation.py`, `src/dashboard/health_dashboard.py`
- [x] ~~Remove orphaned utilities~~ — **Complete**: Deleted `src/utils/deduplication.py`, `src/utils/export.py`, `src/utils/feedback.py`, `src/utils/incremental.py`, `src/utils/search_history.py`, `src/utils/citations.py`, `src/utils/collections.py`, `src/utils/coreragignore.py`. `retry.py` re-added and wired (Session 15).
- [x] ~~Fix CLAUDE.md discrepancies~~ — **Complete** (Session 15)
- [x] ~~Remove empty `src/storage/` directory~~ — **Complete**
- [x] ~~Fix broken `__init__.py` imports~~ — **Done** (Session 15: fixed or deleted `processors/`, `sync/`, `dashboard/`, `ingestion/` packages)
- [x] ~~Remove unused `chunking/code_chunker.py`~~ — **Deleted** (Session 15)

### Module Wiring Status

| Module | Created | Wired | Notes |
|--------|---------|-------|-------|
| `mcp_server/server.py` | Jan 31 | **Feb 1** | Rewritten for stdio + FastMCP |
| `mcp_server/tools.py` | Jan 31 | **Feb 1** | HyDE, decay, multi-query, graph context |
| `search/hybrid_search.py` | Jan 31 | **Feb 1** | Wired in MCP startup |
| `search/reranker.py` | Jan 31 | **Feb 1** | Wired in MCP startup |
| `search/hyde.py` | Jan 31 | **Feb 1** | Wired via create_hyde_expander |
| `search/decay_scoring.py` | Jan 31 | **Feb 1** | Wired in search_knowledge |
| `search/multi_query.py` | Jan 31 | **Feb 1** | Wired via _multi_query_search |
| `embeddings/embedding_service.py` | Jan 31 | **Feb 1** | Wired in MCP startup |
| `analytics/query_analytics.py` | Jan 31 | **Feb 1** | Initialized in MCP startup |
| `utils/privacy_audit.py` | Jan 31 | **Feb 1** | Wired in processor + executor |
| `processor.py` | Jan 31 | **Feb 1** | PII detection at analysis time |
| `intelligence.py` | Jan 31 | **Feb 1** | Split-brain Ollama rewrite |
| `executor.py` | Jan 31 | **Feb 1** | Custom PII dictionary in redaction |
| `chunking/parent_child.py` | Jan 31 | **Feb 1** | Wired via executor |
| `ocr/vision_ocr.py` | Jan 31 | **Feb 1** | Wired into extractor.py |
| `classification/auto_tagger.py` | Jan 31 | **Feb 1** | Wired into processor.py + dashboard |
| `graph/knowledge_graph.py` | Jan 31 | **Feb 1** | Wired into executor + MCP tools |
| `memory/episodic_memory.py` | Jan 31 | **Feb 1** | get_user_context + add_user_fact MCP tools |
| `quality/duplicate_detector.py` | Jan 31 | **Feb 1** | Pre-ingest check in processor.py |
| `quality/link_checker.py` | Jan 31 | **Feb 1** | MCP tool: check_links |
| `quality/freshness.py` | Jan 31 | **Feb 1** | Search enrichment + MCP tool |
| `utils/versioning.py` | Jan 31 | **Feb 1** | Version tracking at commit time |
| `utils/backup.py` | Jan 31 | **Feb 1** | MCP tools + CLI |
| `utils/checkpoint.py` | Jan 31 | **Feb 1** | Used by trigger_reindex |
| `utils/safe_processor.py` | Jan 31 | **Feb 1** | Initialized in MCP server |
| `utils/queue_manager.py` | Jan 31 | **Feb 1** | Persistent job queue in batch_processor |
| `utils/tagging.py` | Jan 31 | **Feb 1** | TagManager MCP tools + executor bridge |
| `audio/topic_segmenter.py` | Jan 31 | **Feb 1** | Wired in extractor.py |
| `video/scene_detector.py` | Jan 31 | **Feb 1** | Wired in extractor.py |
| `multimodal/vlm_captioner.py` | Jan 31 | **Feb 1** | Wired in extractor.py |
| `menubar/` | Feb 1 | **Feb 1** | macOS menu bar app (rumps) |
| `cli/main.py` | Jan 31 | **Feb 1** | 13 commands |
| `config.py` | Jan 31 | **Feb 1** | Centralized constants |
| `exceptions.py` | Feb 2 | **Feb 2** | Custom exception hierarchy (CoreRagError, ProcessingError, etc.) |
| `api/models.py` | Feb 3 | **Feb 3** | Pydantic models for REST API v1 endpoints |
| `utils/path_validation.py` | Feb 3 | **Feb 3** | Path traversal attack prevention |
| `utils/query_sanitize.py` | Feb 3 | **Feb 3** | LanceDB SQL injection prevention |
| `utils/secure_file.py` | Feb 3 | **Feb 3** | Secure file operations (0o600/0o700 permissions) |

### Issues Resolved

| Issue | Resolution | Session |
|-------|------------|---------|
| MCP server used HTTP instead of stdio | Rewrote server.py with FastMCP lifespan | 2 |
| 0/41 summaries from LLM | Split-brain Ollama workflow | 3 |
| 6/41 PII false positives | Three-layer PII detection | 6 |
| HyDE passing HyDEResult object as string | Fixed to use `.hypothetical_document` | 7 |
| Decay scoring not wired | Added `apply_decay_to_results` after reranking | 7 |
| Claude Desktop couldn't connect to MCP | Fixed cwd, macOS permissions, bash inline | 8 |
| `save_profile()` doesn't exist | Correct method is `save()` | 9 |
| `stale_threshold_days` wrong param | Correct param is `stale_days` | 9 |
| numpy >=2.4.2 too strict | Relaxed to >=2.0.0 for mlx-whisper | 9 |
| `cmd_duplicates` API mismatch | Updated field names for `DuplicateReport` | 9 |
| SPHR data in old `.pkm` database | Migrated 4,696 chunks to current db | 13 |
| FTS index broken after migration | Rebuilt with `replace=True` | 13 |
| Tags column missing from LanceDB | Added comma-delimited column during migration | 13 |
| Hardcoded paths across ~60 files | Centralized core constants in config.py | 13 |

---

## External Integration Protocol

> Source: Previously in `_project/KENDRA_INTEGRATION.md`

### Architecture: Who Owns What

```
┌──────────────────────────────────────────────────────────┐
│                      KENDRA (Hub)                        │
│                                                          │
│  Owns: Chat, Voice, Personality, User Memory,            │
│        Skills, Routing, Session History, Mood             │
│                                                          │
│  Calls CoreRag for: Search, Ingest, Stats, Schema Info   │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                  CORE MEMORY (CoreRag)                    │
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

### Connection Methods

#### 1. MCP Client (stdio)

Use for Claude Desktop compatibility, tool composition, structured tool calls.

| Tool | Purpose |
|------|---------|
| `search_knowledge` | Hybrid search (vector + BM25), reranking, HyDE, multi-query |
| `search_by_entity` | Knowledge graph traversal |
| `list_recent_files` | Recently modified vault files |
| `get_folder_structure` | Vault navigation |
| `get_system_status` | System health |
| `get_user_context` | User profile + facts *(Kendra should replace)* |
| `add_user_fact` | Store user fact *(Kendra should own)* |
| `check_stale_content` | Find outdated documents |
| `check_links` | Validate URLs |
| `create_backup` | Trigger backup |
| `trigger_reindex` | Rebuild RAG index |
| `detect_conflicts` | Find contradictory information |
| `find_duplicates` | Near/exact/semantic duplicate detection |
| `get_database_health` | DB size, fragmentation, recommendations |
| `optimize_database` | Run compaction |
| `list_tags` / `manage_tags` | Collection tag CRUD |

#### 2. REST API v1 (HTTP) — `localhost:8000/api/v1/*`

Use for programmatic access, write operations, capability discovery.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/manifest` | GET | **Call on startup** — database schema, capabilities, formats, stats |
| `/api/v1/stats` | GET | Document count, chunk count, entity count |
| `/api/v1/search` | POST | Semantic search with optional HyDE, tags |
| `/api/v1/ingest` | POST | Push text content into the knowledge base |
| `/api/v1/documents/{id}` | DELETE | Remove a document and all its chunks |

### Manifest Protocol

Call on startup to learn CoreRag's capabilities:

```python
async def discover_core_memory():
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/api/v1/manifest")
        manifest = resp.json()
    # manifest["schema"]["embedding_model"] → "all-MiniLM-L6-v2"
    # manifest["schema"]["embedding_dimensions"] → 384
    # manifest["capabilities"]["search_features"] → ["hybrid", "hyde", "reranking", ...]
    # manifest["stats"] → {"documents": 43, "chunks": 4704, ...}
    return manifest
```

### RAG Integration Pattern

Every chat message should attempt a RAG lookup. The results determine how the LLM responds.

```
User Input → [Router] → SEARCH | SKILL | CHAT
                ↓
        [Query Core Memory] → POST /api/v1/search
                ↓
        Results found?
          ├─ YES → Inject context + sources into LLM prompt
          └─ NO  → LLM answers from own knowledge
                ↓
        [LLM generates response]
                ↓
        [Log interaction + extract facts]
```

**Search strategy heuristic**:
| Query Type | Strategy | Example |
|------------|----------|---------|
| Simple factual | Standard (`k=5`) | "What is FMLA?" |
| Complex / multi-part | HyDE (`use_hyde=true`) | "How do compensation strategies relate to retention?" |
| Entity-specific | `search_by_entity` MCP tool | "What documents mention OSHA?" |
| Broad topic | Multi-query (`use_multi_query=true`) | "Everything about employee benefits" |
| Recent files | `list_recent_files` MCP tool | "What did I add recently?" |

### Write-Back

Kendra can push content into Core Memory via ingest API:

| Content | Source Tag | When |
|---------|-----------|------|
| Conversation summary | `kendra-chat-summary` | End of long conversation or daily |
| Skill output | `kendra-skill-{name}` | After skill execution |
| Voice transcript | `kendra-voice-session` | End of voice session |
| Learned facts | `kendra-fact` | High-confidence facts |
| User corrections | `kendra-correction` | When user corrects understanding |

**Don't write back**: every individual chat message (too noisy), raw user queries (privacy), duplicate content.

### User Memory Ownership

**Recommendation**: Kendra owns user memory. CoreRag's user-facts endpoints become read-only consumers. CoreRag's `EpisodicMemoryManager` and `get_user_context` MCP tool can be deprecated once Kendra is the primary interface.

### Database Schema Reference

**LanceDB** (`~/.corerag/lancedb/`):
- `child_chunks`: content (string), vector (float32[384]), document_id, source_path, chunk_index, parent_id, section_title, tags
- `parent_chunks`: content (string), document_id, source_path, metadata (JSON)

**Knowledge Graph** (`~/.corerag/knowledge_graph.db` — SQLite):
- `entities`: id, name, type, document_id, confidence
- `relationships`: id, source_id, target_id, relation_type, document_id

### Port Conflict

Both projects default to port 8000. Resolution: change Kendra to port 8001 in its `config.yaml`.

### Migration Path

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Kendra uses MCP for CoreRag access | **Current** |
| 2 | Kendra uses REST API (replaces sys.path imports) | Pending |
| 3 | Kendra owns user memory (deprecate CoreRag's user-facts) | Pending |
| 4 | Kendra exposes own MCP server; CoreRag becomes one of several sources | Future |

### Responsibility Matrix

| Feature | Owner | Notes |
|---------|-------|-------|
| Document ingestion pipeline | CoreRag | Watchdog, processing, PII, staging |
| HITL review dashboard | CoreRag | Approve/edit/skip UI |
| RAG index (LanceDB) | CoreRag | Chunking, embedding, indexing |
| Knowledge graph | CoreRag | Entity extraction, relationships |
| Obsidian export | CoreRag | Markdown generation, backlinks |
| Quality tools | CoreRag | Dupes, stale, links — exposed via MCP |
| **Chat / conversation** | **Kendra** | Personality, mood, history |
| **Voice interaction** | **Kendra** | STT, TTS, wake word |
| **User memory / facts** | **Kendra** | Episodic + semantic |
| **Skill execution** | **Kendra** | Resume builder, notes, etc. |
| **Intent routing** | **Kendra** | Search vs chat vs skill |
| Search API | CoreRag | Kendra calls it |
| Ingest API | CoreRag | Kendra writes to it |
| Manifest protocol | CoreRag | Kendra reads on startup |

---

## Episodic Memory Design Reference

> **Status**: Handed off to external AI assistant (Kendra)
> Source: Previously in `_project/PHASE_6_EPISODIC_MEMORY.md`

This section preserves the design for reference. CoreRag's `EpisodicMemoryManager` and related MCP tools are deprecated in favor of the external project's memory system.

### Core Objectives

1. **Correction Learning** — Track user overrides of LLM suggestions, feed patterns back into future analysis
2. **Context Continuity** — Maintain session history so MCP conversations pick up where they left off
3. **User Profile** — Aggregate facts, preferences, and current focus from observed behavior

### Priority 1: Correction Learning

At commit time in `executor.py`, capture diffs between proposed and actual values for filename, folder, and sensitivity. Store in SQLite (`~/.corerag/episodic.db`). Inject relevant corrections into `intelligence.py` prompts as few-shot examples.

**Already partially wired**: `correction_log.py` captures diffs, `get_recent_examples()` injects few-shot examples into the LLM prompt.

### Priority 2: Context Continuity

Session events logged in MCP server. Auto-summarize with LLM on 30-minute timeout. Expose via `get_user_context` MCP tool.

**Already partially wired**: `SessionTracker` logs events in MCP server with persistence.

### Priority 3: User Facts

Manual fact storage via `add_user_fact` MCP tool. Inferred preferences from correction patterns (filename style, sensitive categories).

**Already wired**: `EpisodicMemoryManager` with `add_fact()`, categories (personal, preference, technical, work, etc.).

### Recommended Storage Schema

Single SQLite database at `~/.corerag/episodic.db` with 5 tables:

```sql
corrections (id, timestamp, document_summary, document_category, proposed_*, actual_*, *_changed, sample_text)
session_events (id, session_id, timestamp, event_type, tool_name, parameters_summary, result_summary)
session_summaries (session_id, start_time, end_time, duration_minutes, summary, topics, documents_discussed, actions_taken)
user_facts (id, fact, category, source, timestamp, active)
preferences (key, value, last_updated)
```

### Implementation Phases

| Phase | Focus | Status |
|-------|-------|--------|
| 6a | Correction learning | Partially wired (correction_log.py) |
| 6b | Session events | Partially wired (SessionTracker) |
| 6c | User context | Wired (get_user_context + add_user_fact) |
| 6d | Dashboard panel for facts/corrections | Pending |

---

## Future Roadmap

> Source: Previously in `_project/ROADMAP_FUTURE_ENHANCEMENTS.md`

### Priority Summary

| Priority | Item | Status |
|----------|------|--------|
| **P0** | ~~Knowledge Graph MCP Integration~~ | **Complete** (Session 13) |
| **P0** | ~~Database Health MCP Tools~~ | **Complete** (Session 13) |
| **P0** | ~~PII Dictionary Management~~ | **Complete** (Session 11) |
| **P0** | ~~Security Hardening~~ | **Complete** (Session 14) — API auth, path validation, query sanitization, secure file ops |
| **P0** | ~~Dead Code Cleanup~~ | **Complete** (Session 14) — 12 orphaned files deleted |
| **P0** | Query Analytics → Episodic Memory Unification | Handed off to external AI |
| **P1** | Obsidian Backlinks Enhancement | Pending (basic backlinks exist from Session 11) |
| **P1** | Dashboard Bulk Operations & Keyboard Navigation | Pending |
| **P1** | Golden Set Auto-Population from Analytics | Pending |
| **P2** | Knowledge Gaps Analysis | Pending |
| **P2** | Document Versioning Enhancement | Pending (basic versioning in executor) |
| **P2** | Sorting Rules: Pattern Learning | Pending |
| **P3** | Multi-vault support | Backlog |
| **P3** | Collaborative features | Backlog |
| **P3** | External integrations (Readwise, Pocket, Calendar) | Backlog |
| **P3** | Advanced retrieval (query rewriting, conversational search) | Backlog |
| **P3** | Mobile companion app | Backlog |

### Success Metrics

| Category | Metric | Target |
|----------|--------|--------|
| Search Quality | Golden Set pass rate | > 90% |
| Search Quality | Failed query rate | < 10% |
| Search Quality | Average top result score | > 0.7 |
| User Efficiency | Average corrections per batch | < 20% |
| User Efficiency | Bulk operations usage | > 50% of reviews |
| System Health | Database fragmentation | < 20% |
| System Health | Memory usage during ingestion | < 75% |
| Knowledge Coverage | Identified gaps addressed | Within 30 days |

---

### P1: Obsidian Export Enhancement — Auto-Backlinks

**Current State**: `src/obsidian/obsidian_export.py` creates standalone markdown with frontmatter. Session 11 added basic `_generate_backlinks()` using knowledge graph shared entities.

**Goal**: Full backlink support — auto-link matching vault file names in content body, add "Related Documents" section from knowledge graph.

**Implementation**:

```python
# In src/obsidian/obsidian_export.py

class BacklinkGenerator:
    """Generate Obsidian wikilinks for imported content."""

    def __init__(self, vault_path: Path, graph_db_path: Optional[Path] = None):
        self.vault_path = vault_path
        self.graph_db_path = graph_db_path
        self._vault_files: Set[str] = set()
        self._refresh_vault_index()

    def _refresh_vault_index(self):
        """Index all markdown files in vault for linking."""
        self._vault_files = set()
        for md_file in self.vault_path.rglob("*.md"):
            name = md_file.stem
            self._vault_files.add(name.lower())

    def find_linkable_terms(self, content: str) -> Dict[str, str]:
        """Find terms in content that match existing vault files."""
        linkable = {}
        for vault_name in self._vault_files:
            pattern = re.compile(rf'\b({re.escape(vault_name)})\b', re.IGNORECASE)
            matches = pattern.findall(content)
            if matches:
                original = matches[0]
                linkable[original] = f"[[{vault_name}|{original}]]"
        return linkable

    def get_entity_links(self, document_id: str) -> List[str]:
        """Get related entities from knowledge graph for 'Related' section."""
        if not self.graph_db_path or not self.graph_db_path.exists():
            return []
        try:
            conn = sqlite3.connect(self.graph_db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT name FROM entities WHERE document_id = ?",
                (document_id,)
            )
            entities = [row[0] for row in cursor.fetchall()]
            related = []
            for entity in entities:
                if entity.lower() in self._vault_files:
                    related.append(f"[[{entity}]]")
            conn.close()
            return related
        except Exception:
            return []

    def enhance_content(self, content: str, document_id: str,
                        auto_link: bool = True, add_related_section: bool = True) -> str:
        """Enhance content with backlinks."""
        enhanced = content
        if auto_link:
            linkable = self.find_linkable_terms(content)
            for original, wikilink in linkable.items():
                enhanced = enhanced.replace(original, wikilink, 1)
        if add_related_section:
            related = self.get_entity_links(document_id)
            if related:
                enhanced += "\n\n---\n\n## Related\n\n"
                enhanced += "\n".join(f"- {link}" for link in related)
        return enhanced
```

**Files**: `src/obsidian/obsidian_export.py`, `src/executor.py`

---

### P1: Dashboard Bulk Operations & Keyboard Navigation

**Current State**: Dashboard requires individual clicks per item.

**Goal**: Keyboard navigation (j/k, a=approve, s=skip, Space=select), bulk approve (Shift+Enter), quick folder assign (1-5 keys), range selection (Shift+click), "apply to similar" when correcting category.

**Implementation**:

```javascript
// Add to dashboard.html
class DashboardEnhancements {
    constructor() {
        this.selectedItems = new Set();
        this.currentIndex = 0;
        this.recentFolders = this.loadRecentFolders();
        this.initKeyboardNav();
        this.initBulkSelect();
        this.initQuickAssign();
    }

    initKeyboardNav() {
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            switch(e.key) {
                case 'j': case 'ArrowDown': this.navigateNext(); break;
                case 'k': case 'ArrowUp': this.navigatePrev(); break;
                case 'a': this.approveCurrentItem(); break;
                case 's': this.skipCurrentItem(); break;
                case 'e': this.editCurrentItem(); break;
                case 'Space': e.preventDefault(); this.toggleSelectCurrent(); break;
                case 'Enter': if (e.shiftKey) this.bulkApprove(); break;
                case '1': case '2': case '3': case '4': case '5':
                    this.quickAssignFolder(parseInt(e.key) - 1); break;
            }
        });
    }

    bulkApprove() {
        if (this.selectedItems.size === 0) return;
        if (!confirm(`Approve ${this.selectedItems.size} items?`)) return;
        this.selectedItems.forEach(id => {
            fetch(`/api/items/${id}/approve`, { method: 'POST' });
        });
        this.selectedItems.clear();
        this.refreshList();
    }

    applyToSimilar() {
        const currentItem = this.items[this.currentIndex];
        const category = currentItem.metadata.category;
        const folder = currentItem.proposed.target_folder;
        const similar = this.items.filter(item =>
            item.metadata.category === category &&
            item.proposed.target_folder !== folder &&
            item.status === 'pending'
        );
        if (similar.length > 0 && confirm(
            `Apply folder "${folder}" to ${similar.length} other "${category}" items?`
        )) {
            similar.forEach(item => this.assignFolder(item.id, folder));
        }
    }
}
```

**Files**: `src/ui/templates/dashboard.html`

---

### P1: Golden Set Auto-Population from Analytics

**Current State**: `QueryAnalytics.get_golden_set_suggestions()` identifies candidates, but adding to `golden_set.yaml` is manual.

**Goal**: MCP tools to get suggestions, approve/reject, manage golden set entries.

**Implementation**:

```python
# src/quality/golden_set_manager.py (new file)

@dataclass
class GoldenSetEntry:
    query: str
    expected_file: str
    min_score: float = 0.5
    added_date: str = ""
    source: str = "manual"  # 'manual', 'auto-suggested', 'auto-approved'

class GoldenSetManager:
    def __init__(self, golden_set_path=None, analytics=None):
        self.golden_set_path = golden_set_path or Path("tests/golden_set.yaml")
        self.analytics = analytics or QueryAnalytics()

    def get_suggestions(self, limit=10) -> List[Dict]:
        suggestions = self.analytics.get_golden_set_suggestions(limit=limit * 2)
        existing_queries = {e.query.lower() for e in self._entries}
        return [s for s in suggestions if s["query"].lower() not in existing_queries][:limit]

    def add_entry(self, query, expected_file, min_score=0.5, source="manual") -> bool:
        if any(e.query.lower() == query.lower() for e in self._entries):
            return False
        self._entries.append(GoldenSetEntry(query=query, expected_file=expected_file,
            min_score=min_score, added_date=datetime.now().isoformat(), source=source))
        self._save()
        return True

    def approve_suggestion(self, query: str) -> bool:
        suggestions = self.get_suggestions(limit=50)
        for s in suggestions:
            if s["query"].lower() == query.lower():
                return self.add_entry(s["query"], s["expected_file"], source="auto-approved")
        return False
```

**Files**: `src/quality/golden_set_manager.py` (new), `src/mcp_server/tools.py`, `src/mcp_server/server.py`

---

### P2: Knowledge Gaps Analysis

**Current State**: System waits for files to appear in Inbox.

**Goal**: Proactively identify what's missing — failed searches, sparse folders, topic imbalances.

**Implementation**:

```python
# src/analytics/gaps_analyzer.py (new file)

@dataclass
class KnowledgeGap:
    topic: str
    evidence: str
    confidence: float
    suggested_action: str

class GapsAnalyzer:
    def __init__(self, vault_path, archive_path, analytics=None):
        self.vault_path = vault_path
        self.archive_path = archive_path
        self.analytics = analytics or QueryAnalytics()

    def identify_search_gaps(self) -> List[KnowledgeGap]:
        failed_queries = self.analytics.get_failed_queries(limit=20)
        return [KnowledgeGap(
            topic=q.query,
            evidence=f"Searched {q.timestamp}, score: {q.top_result_score:.2f}",
            confidence=1.0 - q.top_result_score,
            suggested_action=f"Add documents about '{q.query}'"
        ) for q in failed_queries]

    def identify_imbalances(self) -> List[KnowledgeGap]:
        distribution = self.analyze_folder_distribution()
        if not distribution:
            return []
        avg_count = sum(distribution.values()) / len(distribution)
        return [KnowledgeGap(
            topic=folder, evidence=f"Only {count} docs vs {avg_count:.0f} average",
            confidence=0.7, suggested_action=f"Add more content to '{folder}'"
        ) for folder, count in distribution.items() if count < avg_count * 0.3]

    def get_comprehensive_analysis(self) -> Dict[str, Any]:
        search_gaps = self.identify_search_gaps()
        imbalance_gaps = self.identify_imbalances()
        all_gaps = sorted(search_gaps + imbalance_gaps, key=lambda g: g.confidence, reverse=True)
        return {
            "search_gaps": [{"topic": g.topic, "evidence": g.evidence, "action": g.suggested_action} for g in search_gaps[:5]],
            "sparse_areas": self.identify_sparse_folders()[:10],
            "top_recommendations": [{"topic": g.topic, "action": g.suggested_action, "confidence": g.confidence} for g in all_gaps[:5]]
        }
```

**Files**: `src/analytics/gaps_analyzer.py` (new), `src/mcp_server/tools.py`, `src/mcp_server/server.py`

---

### P2: Document Versioning Enhancement

**Current State**: Re-ingesting a file overwrites previous content without tracking changes. Basic `VersionManager` exists in `src/utils/versioning.py`.

**Goal**: Full version history with diff summaries for annually-updated materials.

**Implementation**:

```python
# src/versioning/document_versions.py (new file)

class DocumentVersionStore:
    """Track document versions with content hashes and diff summaries."""

    def __init__(self, db_path=None):
        self.db_path = db_path or Path.home() / ".corerag" / "versions.db"
        self._init_db()

    def is_changed(self, document_id: str, content: str) -> bool:
        latest = self.get_latest_version(document_id)
        if not latest:
            return True
        return self.compute_hash(content) != latest.content_hash

    def record_version(self, document_id, content, source_path, file_size,
                       summary=None, old_content=None) -> DocumentVersion:
        latest = self.get_latest_version(document_id)
        version = (latest.version + 1) if latest else 1
        changes = self.compute_diff_summary(old_content, content) if old_content and version > 1 else None
        # Store in SQLite...
        return DocumentVersion(...)

    def get_version_history(self, document_id: str) -> List[DocumentVersion]:
        # Query SQLite ordered by version DESC
        ...
```

**MCP tool**: `get_document_history(document_id)` returns version list with change summaries.

**Files**: `src/versioning/document_versions.py` (new), `src/executor.py`, `src/mcp_server/tools.py`

---

### P2: Sorting Rules — Pattern Learning

**Current State**: `sorting_rules.yaml` is static. LLM suggestions don't adapt.

**Goal**: Learn folder mappings, category defaults, and sensitivity patterns from user corrections.

**Implementation**:

```python
# src/classification/learned_rules.py (new file)

class LearnedRulesManager:
    """Learn organization patterns from user corrections."""

    def __init__(self, rules_path=None, corrections_path=None):
        self.rules_path = rules_path or Path("sorting_rules.yaml")
        self.corrections_path = corrections_path or Path("corrections_log.json")
        self.learned_rules_path = Path.home() / ".corerag" / "learned_rules.yaml"

    def analyze_corrections(self) -> Dict[str, Dict]:
        """Derive patterns: folder_mappings, category_to_folder, sensitivity_categories."""
        ...

    def generate_learned_rules(self, min_frequency=2) -> Dict:
        """Generate rules from patterns appearing >= min_frequency times."""
        patterns = self.analyze_corrections()
        rules = {"folder_redirects": {}, "category_defaults": {}, "sensitive_categories": []}
        # Aggregate folder redirects, category defaults, sensitive categories...
        return rules

    def get_folder_suggestion(self, ai_suggestion: str, category: str) -> Optional[str]:
        """Get better folder based on learned patterns."""
        # Check folder_redirects and category_defaults with confidence >= 0.5
        ...

    def should_mark_sensitive(self, summary: str, category: str) -> bool:
        """Check if document should likely be marked sensitive."""
        # Match against learned sensitive_categories patterns
        ...
```

**Integration**: Call in `intelligence.py` after LLM analysis to apply learned rules.

**Files**: `src/classification/learned_rules.py` (new), `src/intelligence.py`

---

### P3: Backlog Items

| Item | Description |
|------|-------------|
| Multi-vault support | Multiple Obsidian vaults (Work, Personal, Research) |
| Collaborative features | Shared CoreRag, permission levels for sensitive content |
| External integrations | Readwise sync, Pocket/Instapaper, calendar integration |
| Advanced retrieval | Query rewriting with context, conversational search with follow-ups |
| Mobile companion | iOS Shortcut or lightweight app for quick capture to Inbox |

---

## Known Issues & Discrepancies

| Item | Documentation Claim | Actual State | Status |
|------|-------------------|--------------|--------|
| AST Code Chunking | CLAUDE.md: "code_chunker.py exists but not imported" | ~~`chunking/code_chunker.py` exists but is **never imported**~~ | **Resolved** — deleted in Session 15 |
| Spreadsheet Processing | README: listed as supported | ~~`processors/spreadsheet_processor.py` exists but never imported~~ | **Resolved** — deleted |
| `src/ingestion/pipeline.py` | Listed as "Unwired" | ~~Duplicate `src/ingestion.py` also existed at root~~ | **Resolved** — both deleted |
| Zombie Reconciliation | Not mentioned in CLAUDE.md | ~~`sync/reconciliation.py` defines ZombieReconciler, never called~~ | **Resolved** — deleted |
| Orphaned utility modules | CLAUDE.md: "Partially wired" | ~~6 utils orphaned~~ | **Resolved** — all 6 deleted |
| Embedding model | CONVENTIONS.md says `nomic-embed-text-v1.5` (768d) | Code uses `all-MiniLM-L6-v2` (384d). | **Resolved** — CONVENTIONS.md fixed |
| Broken `__init__.py` exports | Several packages export from deleted modules | ~~`processors/`, `sync/`, `dashboard/`, `ingestion/` `__init__.py` files have broken imports~~ | **Resolved** — fixed/deleted in Session 15 |

---

## Project Audit & Improvement Plan

> **Initial Audit**: 2026-02-02 | **Last Updated**: 2026-02-02
> Comprehensive evaluation against industry best practices for security, documentation, organization, and development. Items marked ~~strikethrough~~ have been resolved.

### Critical Priority

#### SQL Injection in LanceDB Query Construction
**Files**: `src/server.py` (lines ~881-882, 648, 652)
**Issue**: User-supplied strings (search queries, tag filters) are interpolated directly into LanceDB filter expressions via f-strings. An attacker with dashboard or API access could inject arbitrary filter logic.
**Mitigating factor**: LanceDB uses an expression parser (not raw SQL), which limits exploitability. Tag values also originate from system (UI/CLI), not directly from REST API request bodies.
**Fix**: Use parameterized queries or sanitize/validate all user inputs before constructing LanceDB `where` clauses. Create a query builder utility that escapes special characters.

#### ~~Custom Exception Hierarchy Not Implemented~~ (Resolved)
**Status**: Fixed on 2026-02-02. Created `src/exceptions.py` with `CoreRagError` base class and 6 subclasses: `ProcessingError`, `EmbeddingError`, `DatabaseError`, `SearchError`, `ConfigurationError`, `CoreRagMemoryError`. Fixed all 8 bare `except:` clauses — replaced with specific exception types or proper control flow (`table_names()` check instead of try/except).

#### ~~Documentation Claims Non-Existent Features~~ (Partially Fixed)
**Files**: `CLAUDE.md`, `CONVENTIONS.md`
**Issue**: CLAUDE.md claimed AST code chunking and spreadsheet processing were "wired" — neither is imported or used anywhere. CONVENTIONS.md references the wrong embedding model (nomic-embed-text-v1.5 vs actual all-MiniLM-L6-v2).
**Status**: CLAUDE.md Key Subsystems table and File Type Support section corrected on 2026-02-02. CONVENTIONS.md embedding model reference still needs fixing.

#### ~~Pre-Commit Hooks Not Activated~~ (Resolved)
**Status**: Fixed on 2026-02-02. Created `.pre-commit-config.yaml` with 4 hooks: (1) `security_scan.sh --staged`, (2) `black --check`, (3) `ruff check`, (4) `mypy`. Hooks installed via `pre-commit install`. Note: 79 files need black formatting, 287 ruff issues exist — these are pre-existing and will be enforced on new commits to those files.

### High Priority

#### No REST API Authentication
**Files**: `src/server.py`
**Issue**: All REST API v1 endpoints (`/api/v1/search`, `/api/v1/ingest`, `/api/v1/documents/{id}` DELETE) are unauthenticated. While localhost-only (bound to `127.0.0.1:8000`), any local process or browser-based attack (CSRF) could read/write/delete data.
**Fix**: Add at minimum a shared secret / API key header check. Add explicit CORS middleware restricting origins to `http://localhost:8000`.

#### No Pydantic Request/Response Models on API
**Files**: `src/server.py`
**Issue**: REST API endpoints use raw `await request.json()` instead of Pydantic models. No automatic validation, type coercion, or OpenAPI documentation generation. Malformed JSON or unexpected fields pass through silently. FastAPI's auto-generated `/docs` endpoint lacks proper schemas.
**Fix**: Create Pydantic models (`SearchRequest`, `IngestRequest`, `SearchResponse`, etc.) for all v1 endpoints. Add FastAPI response_model parameters. Verify `/docs` renders complete API documentation.

#### ~~Duplicate Module Pairs~~ (Resolved)
**Status**: Fixed on 2026-02-03. Removed 3 orphaned files:
- `src/ingestion.py` — duplicate of watchdog.py (identical code)
- `src/utils/export.py` — not imported anywhere
- `src/storage/` directory — empty stub package
Note: `src/utils/deduplication.py` retained because it has tests (provides `DeduplicationManager` class).

#### ~~Config Sprawl — 32 Files with Hardcoded Paths~~ (Resolved)
**Status**: Fixed in Sessions 13-15. Core constants centralized in `config.py` (STATE_DIR, DB_PATH, QUEUE_DIR, CHECKPOINT_DIR, HEALTH_DIR, FEEDBACK_DIR, EXPORT_DIR, LOG_DIR, EMBEDDING_MODEL, RERANKER_MODEL). Key entry points and factory functions import from config. Remaining utility files use `or` fallback patterns that still work correctly.

#### ~~Zero Test Coverage on Core Pipeline~~ (Resolved)
**Status**: Fixed on 2026-02-03. Created 4 test files with 61 tests covering all core pipeline modules:
- `tests/test_extractor.py` (19 tests) — text extraction for all file types, PDF OCR fallback, encoding handling
- `tests/test_processor.py` (10 tests) — PII detection flow, staging, CUI prefix, duplicate detection, auto-tagging
- `tests/test_executor.py` (14 tests) — PII redaction, RAG indexing, archive/export, skip flags
- `tests/test_batch_processor.py` (18 tests) — memory safety, pause/resume, queue processing, error handling

#### ~~No `conftest.py` for Centralized Test Fixtures~~ (Resolved)
**Status**: Fixed on 2026-02-03. Created `tests/conftest.py` with 25+ shared fixtures including:
- Path fixtures (temp_dir, temp_inbox, temp_vault, temp_archive, temp_state_dir, temp_manifest)
- Sample document fixtures (text, sensitive, JSON, markdown files)
- Metadata fixtures (sample_metadata, sample_staging_item, sample_approved_item)
- Mock service fixtures (mock_lancedb, mock_embedder, mock_retriever, mock_pii_scanner, mock_intelligence, mock_dedup, mock_auto_tagger, mock_chunker, mock_queue_manager)
- FastAPI test client fixture
- Environment setup for test isolation

#### ~~No Dependency Lock File~~ (Resolved)
**Status**: Fixed on 2026-02-03. Created `requirements.lock` with pip freeze containing 329 pinned dependencies (all direct + transitive). File includes header with generation timestamp, Python version, and platform. To update: run `pip freeze > requirements.lock` after installing/updating deps.

#### File Permissions Not Enforced in Code
**Files**: `src/utils/privacy_audit.py`, `src/config.py`
**Issue**: `pii_terms.yaml` and other sensitive runtime files rely on documentation telling users to run `chmod 600`. No code enforces permissions. The `~/.corerag/` directory is created with default umask permissions.
**Fix**: Add `os.chmod()` calls in `privacy_audit.py` when loading/creating `pii_terms.yaml` and in `config.py` when creating `~/.corerag/` directory. Use `stat.S_IRUSR | stat.S_IWUSR` (0o600) for sensitive files, `stat.S_IRWXU` (0o700) for the data directory.

#### ~~Incomplete `.env.example`~~ (Resolved)
**Status**: `.env.example` exists at project root with INBOX_PATH, VAULT_PATH, ARCHIVE_PATH, and GOOGLE_API_KEY. Could be expanded to include OLLAMA_HOST, OLLAMA_MODEL, CORERAG_DB_PATH, CORERAG_EMBEDDING_MODEL, CORERAG_RERANKER_MODEL.

### Medium Priority

#### ~~Broken `__init__.py` Exports from Deleted Modules~~ (Resolved)
**Status**: Fixed in Session 15. Broken `__init__.py` files in `processors/`, `sync/`, `dashboard/`, `ingestion/` were fixed or packages deleted entirely.

#### server.py Monolith (1,090 Lines)
**File**: `src/server.py`
**Issue**: Single file contains 29 dashboard routes, 5 API endpoints, batch processing orchestration, and template rendering. Difficult to navigate, test, or modify.
**Fix**: Extract into `src/api/v1_routes.py` (REST API), `src/dashboard/routes.py` (dashboard endpoints), keeping `server.py` as the app factory and startup.

#### ~~Empty Stub Packages~~ (Resolved)
**Status**: Fixed on 2026-02-03. Removed `src/storage/` (empty __init__.py only). Note: `src/ingestion/` is NOT empty — `pipeline.py` is imported by `src/cli/main.py` for the ingest command.

#### Path Traversal Risk in File Operations
**Files**: `src/server.py`, `src/executor.py`
**Issue**: File paths from user input (dashboard, API) may not be validated against directory traversal attacks (`../../etc/passwd`). While localhost-only, defense in depth applies.
**Fix**: Add path canonicalization and validate all file paths are within expected directories (INBOX_PATH, VAULT_PATH, ARCHIVE_PATH) before operations.

#### ~~Bare Except Clauses (5+ Locations)~~ (Resolved)
**Status**: Fixed in Session 15. All bare `except:` blocks eliminated. Custom exception hierarchy (`CoreRagError` and 6 subtypes) wired into 15 files. ~146 `except Exception` blocks remain but are intentional catch-all handlers that log errors.

#### Missing Return Type Hints (~15% of Functions)
**Files**: `src/server.py` (`_get_memory_pct()` missing `-> float`), `src/intelligence.py` (`_ollama_generate()` missing return type)
**Issue**: Type hint coverage is ~85%. Utility functions and API route handlers are the primary gaps. `mypy --strict` is configured in pyproject.toml but gaps remain.
**Fix**: Add return type hints during any file touch. Run `mypy --strict src/` to identify all gaps systematically.

#### Magic Numbers in Processing Code
**Files**: `src/processor.py` (line ~96: `text[:20000]`), `src/executor.py` (line ~56: `confidence < 0.70`), `src/models/document.py` (comment says 768-dim but model is 384-dim)
**Issue**: Processing thresholds and limits are scattered as raw numbers. PII confidence threshold (0.70), text sample size (20000 chars), and embedding dimensions referenced inconsistently.
**Fix**: Create named constants: `PII_MIN_CONFIDENCE = 0.70`, `PII_SAMPLE_MAX_CHARS = 20000`, `EMBEDDING_DIMENSION = 384`. Add to `src/config.py` or a new `src/constants.py`.

#### ~~Mixed Sync/Async I/O~~ (Resolved)
**Status**: Fixed in Session 15. Migrated `intelligence.py` from sync `requests` to async `httpx`. All LLM methods (`_ollama_generate`, `analyze_document`, `suggest_folder_structure`) are now `async def`. `processor.py` uses `await`, `batch_processor.py` uses `asyncio.run()`. `httpx>=0.28.0` added to requirements.

#### Security Scanner Not in CI
**Files**: `.github/workflows/ci.yml`
**Issue**: GitHub Actions runs lint (ruff, black, isort, mypy) and tests (pytest) but does not run `scripts/security_scan.sh`. A PR could introduce hardcoded paths or secrets without CI catching it.
**Fix**: Add a `security` job to `ci.yml` that runs `./scripts/security_scan.sh`.

#### ~~DevPlan.md Not Referenced from CLAUDE.md~~ (Resolved)
**Status**: CLAUDE.md updated on 2026-02-02 with reference to `_project/DevPlan.md` in Project Overview and Wiring Plan sections.

### Low Priority

#### pyproject.toml Entry Point
**Issue**: `pyproject.toml` may define a `[project.scripts]` entry point that doesn't match the actual CLI invocation pattern (`python -m src.cli.main`).
**Fix**: Verify entry point works or remove if unused.

#### Missing Dependencies in requirements.txt
**Issue**: Some imported packages may not be listed in `requirements.txt` (relying on transitive dependencies). This can break on clean installs.
**Fix**: Run `pip freeze` comparison against `requirements.txt` and add any missing direct dependencies.

#### No CHANGELOG.md
**Issue**: Version history is tracked in DevPlan.md's Project Timeline, but there's no standard CHANGELOG.md for release-oriented tracking.
**Fix**: Low priority — the Project Timeline serves this purpose for a single-developer project. Consider adding if the project gains external users.

#### No Troubleshooting Guide
**Issue**: Common issues (Ollama not running, MCP connection failures, LanceDB FTS index corruption) are documented in findings but not in an easy-to-find troubleshooting section.
**Fix**: Add a Troubleshooting section to CLAUDE.md or create a separate doc.

#### No Architecture Diagram Index
**Files**: `architecture/` (18 markdown files with no index or hierarchy)
**Issue**: 18 architecture documents exist with no `architecture/README.md` or table of contents. Difficult to discover what documentation exists or which doc covers a given topic.
**Fix**: Create `architecture/README.md` linking all docs by topic area. Add Mermaid diagrams for ingestion pipeline and module dependency graph.

#### No Rate Limiting on REST API
**Issue**: API endpoints have no rate limiting. While localhost-only, a misbehaving client could overload the system.
**Fix**: Add basic rate limiting middleware (e.g., `slowapi`) if external consumers (Kendra) are expected to make frequent calls.

#### `.env.example` Missing Advanced Variables
**Issue**: `.env.example` exists but only covers 4 variables (INBOX_PATH, VAULT_PATH, ARCHIVE_PATH, GOOGLE_API_KEY). Missing: OLLAMA_HOST, OLLAMA_MODEL, CORERAG_DB_PATH, CORERAG_STATE_DIR, CORERAG_EMBEDDING_MODEL, CORERAG_RERANKER_MODEL.
**Fix**: Expand `.env.example` with all variables documented in CLAUDE.md's Configuration section, with comments explaining defaults.

#### ~~Logging Config Not Uniformly Applied~~ (Resolved)
**Status**: Fixed in Session 15. `logging_config.py` wired as central logging initializer in all entry points: `server.py`, `mcp_server/server.py`, `cli/main.py`, `watchdog.py`.

### Resolved Items

| Item | Resolution | Date |
|------|-----------|------|
| CLAUDE.md accuracy (code chunker, spreadsheet, subsystems table) | Corrected Key Subsystems table, File Type Support, orphaned utils listed | 2026-02-02 |
| DevPlan.md not referenced from CLAUDE.md | Added references in Project Overview and Wiring Plan sections | 2026-02-02 |
| `.env.example` missing | File exists; needs expansion (moved to Low priority) | 2026-02-02 |
| Python baseline upgraded to 3.12+ | Updated pyproject.toml, CI workflows, CLAUDE.md, CONVENTIONS.md. Rationale: better error messages, longer EOL (Oct 2028), f-string improvements, MLX alignment | 2026-02-02 |
| Pre-commit hooks not activated | Created `.pre-commit-config.yaml` with 4 hooks (security-scan, black, ruff, mypy). Installed via `pre-commit install`. | 2026-02-02 |
| Custom exception hierarchy missing | Created `src/exceptions.py` with CoreRagError hierarchy. Fixed all 8 bare `except:` clauses. | 2026-02-02 |
| LanceDB query injection risk | Created `src/utils/query_sanitize.py` with sanitization functions. Updated 6 files (15+ query locations) to use parameterized queries. | 2026-02-03 |
| API authentication missing | Added API key auth via `CORERAG_API_KEY` env var. Protected 4 endpoints (stats, search, ingest, delete). Manifest remains public. Updated CLAUDE.md and .env.example. | 2026-02-03 |
| Path traversal vulnerability | Created `src/utils/path_validation.py` with path canonicalization, blocked system paths, and sensitive filename detection. Updated 5 CLI commands (ingest, check-links, duplicates, stale, tag). | 2026-02-03 |
| File permissions insecure | Created `src/utils/secure_file.py` with secure_mkdir() (0o700) and secure_write() (0o600). Updated config.py to use secure_state_directory(). PII terms CLI now uses secure_write(). | 2026-02-03 |
| API lacks validation | Created `src/api/models.py` with Pydantic models for all v1 endpoints (Search, Ingest, Stats, Delete). OpenAPI docs now at /api/docs. Endpoints use typed request/response models. | 2026-02-03 |
| Core pipeline tests missing | Created 61 tests across 4 files: test_extractor.py (19), test_processor.py (10), test_executor.py (14), test_batch_processor.py (18). Covers text extraction, PII detection, staging, RAG indexing, memory safety. | 2026-02-03 |
| Test fixtures duplicated | Created `tests/conftest.py` with 25+ shared fixtures: temp paths, sample documents, mock services (LanceDB, embedder, PII scanner, intelligence, dedup, tagger, chunker). Test count: 182 passing. | 2026-02-03 |
| No dependency lock file | Created `requirements.lock` with 329 pinned dependencies including transitive. Header documents generation timestamp, Python version, platform. | 2026-02-03 |
| Orphaned duplicate files | Removed `src/ingestion.py` (dup of watchdog.py), `src/utils/export.py` (unused), `src/storage/` (empty stub). Tests still pass (182). | 2026-02-03 |
| CONVENTIONS.md accuracy | Fixed embedding model (nomic→all-MiniLM-L6-v2, 768d→384d). Updated exception hierarchy docs to reference actual `src/exceptions.py`. | 2026-02-03 |
| CI missing security scanner | Added `security_scan.sh` step to `.github/workflows/ci.yml` security job. Runs before bandit/safety/pip-audit. | 2026-02-03 |
| .env.example incomplete | Expanded with CORERAG_STATE_DIR, added explanatory comments for all variables. | 2026-02-03 |
| Orphaned modules cleanup | Deleted 12 orphaned files: `ingestion.py`, `ingestion/pipeline.py`, `storage/__init__.py`, `processors/spreadsheet_processor.py`, `sync/reconciliation.py`, `dashboard/health_dashboard.py`, `utils/deduplication.py`, `utils/export.py`, `utils/feedback.py`, `utils/incremental.py`, `utils/retry.py`, `utils/search_history.py` | 2026-02-04 |
| StartHere.md project guide | Created comprehensive project guide with document map, architecture diagrams, source code map, discrepancies table, project templates integration. | 2026-02-04 |

### Recommended Action Order

**Security (do first)**:
1. ~~**Pre-commit hooks** — Wire `security_scan.sh --staged` + linters~~ ✓
2. ~~**Custom exception hierarchy** — Create `src/exceptions.py`, fix bare excepts~~ ✓
3. ~~**LanceDB query sanitization** — Parameterize tag filters and document_id lookups~~ ✓
4. ~~**API authentication** — Shared secret / API key header~~ ✓
5. ~~**Path traversal validation** — Canonicalize paths, validate within allowed dirs~~ ✓
6. ~~**File permissions enforcement** — `os.chmod()` for pii_terms.yaml, ~/.corerag/~~ ✓

**Quality (do next)**:
7. ~~**Pydantic API models** — Request/response validation + OpenAPI docs~~ ✓
8. ~~**Core pipeline tests** — processor.py, executor.py, extractor.py, batch_processor.py~~ ✓
9. ~~**conftest.py** — Centralized test fixtures~~ ✓
10. ~~**Dependency lock file** — pip-compile or Poetry~~ ✓

**Cleanup (ongoing)**:
11. ~~**Phase 11 completion** — Duplicates, stubs, dead code removed~~ ✓ (config sprawl still pending)
12. **server.py decomposition** — Extract API + dashboard routes (deferred)
13. ~~**CONVENTIONS.md fixes** — Embedding model reference, exception hierarchy docs~~ ✓
14. ~~**CI security job** — Add security_scan.sh to GitHub Actions~~ ✓
15. ~~**Expand .env.example** — All variables with comments~~ ✓

---

## Code Health — Recommendations from /sync (2026-02-06)

> Added by `/sync` command. These address orphaned code, unwired utilities, and template alignment.

| # | Task | Priority | Files | Status |
|---|------|----------|-------|--------|
| 1 | **Update security_scan.sh to v2** — Add `SCANNER_VERSION="2"` tracking + `--version` flag | High | `scripts/security_scan.sh` | **Done** (applied during sync) |
| 2 | **Wire `src/exceptions.py`** — Custom exception hierarchy wired into 15 files. | High | `src/exceptions.py` → `executor.py`, `processor.py`, `server.py`, `intelligence.py`, etc. | **Done** (Session 15) |
| 3 | **Wire `src/utils/logging_config.py`** — Structured logging wired into all 4 entry points. | Medium | `src/utils/logging_config.py` → `server.py`, `mcp_server/server.py`, `cli/main.py`, `watchdog.py` | **Done** (Session 15) |
| 4 | **Wire `src/utils/retry.py`** — Retry/circuit breaker wired into API call sites. | Medium | `src/utils/retry.py` → `intelligence.py`, `search/hybrid_search.py`, `embeddings/embedding_service.py` | **Done** (Session 15) |
| 5 | **Clean up remaining orphaned utils** — Deleted 3 orphaned utilities: `citations.py`, `collections.py`, `coreragignore.py`. | Low | Deleted | **Done** (Session 15) |

---

## Open Questions

- [ ] Topic taxonomy (predefined vs AI-generated)?
- [ ] Obsidian vault structure for new categories?
- [ ] Priority file types for next ingestion batch?
- [x] Paid API needed? **No** — Ollama achieves 100% quality
- [x] PII detection approach? **Three-layer** (Presidio + dictionary + LLM advisory)
- [x] Chunking strategy? **Parent-child** (512 token children, 2048 parents)
- [x] Tag naming convention? **`study-` prefix** for topic grouping

---

## Archived Files Index

The following files were consolidated into this document on 2026-02-02 and moved to `_project/Archive/`:

| File | Original Location | Content Now In |
|------|------------------|----------------|
| `README.md` | `_project/README.md` | Superseded by this document |
| `ROADMAP_FUTURE_ENHANCEMENTS.md` | `_project/ROADMAP_FUTURE_ENHANCEMENTS.md` | [Future Roadmap](#future-roadmap) |
| `PHASE_6_EPISODIC_MEMORY.md` | `_project/PHASE_6_EPISODIC_MEMORY.md` | [Episodic Memory Design](#episodic-memory-design-reference) |
| `progress.md` | `_project/progress.md` | [Project Timeline](#project-timeline), [Issues Resolved](#issues-resolved) |
| `project_memory.md` | `_project/project_memory.md` | [Key Decisions](#key-decisions--findings), [Technology Decisions](#technology-decisions-validated) |
| `task_plan.md` | `_project/task_plan.md` | [Wiring Plan Status](#wiring-plan-status), [Module Wiring Status](#module-wiring-status) |
| `findings.md` | `_project/findings.md` | [Integration Findings](#integration-findings) |
| `KENDRA_INTEGRATION.md` | `_project/KENDRA_INTEGRATION.md` | [External Integration Protocol](#external-integration-protocol) |

Previously archived files (from scaffold phase, Jan 31):
- `_project/Archive/AGENT_INSTRUCTIONS.md` — Superseded by CLAUDE.md
- `_project/Archive/Master_Prompt.md` — Superseded by CLAUDE.md
- `_project/Archive/PRD.md` — Requirements doc (all phases complete)
- `_project/Archive/MIGRATION_LOG.md` — One-time merge log
- `_project/Archive/SETUP_TASKS.md` — User setup checklist

---

*Consolidated from 8 planning files on 2026-02-02. Last updated: 2026-02-06.*
