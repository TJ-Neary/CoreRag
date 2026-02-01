# PKM System - Project Memory

---

## Project Overview

**Project**: Personal Knowledge Management System with RAG
**Owner**: TJ
**Started**: 2026-01-31
**Status**: Integration Complete — 12 of 12 wiring phases complete ✅
**Hardware**: M4 Max 48GB RAM, Apple Silicon

---

## Key Decisions Log

| Date | Decision | Rationale | Impact |
|------|----------|-----------|--------|
| Jan 31 | Use LanceDB for vector storage | Embedded, handles TB scale, no server | Core infrastructure |
| Jan 31 | Use FastMCP (Python) for MCP server | Python-native, stdio transport for Claude Desktop | MCP integration |
| Jan 31 | Local-first with hybrid option | Privacy priority, allow API fallback | Architecture |
| Jan 31 | SafeProcessor for memory management | Prevent OOM on M4 Max | Reliability |
| Feb 1 | Ollama (qwen2.5:32b) as default LLM | 100% metadata quality achieved locally, no need for paid API | Cost/privacy |
| Feb 1 | Split-brain intelligence workflow | Single Ollama call couldn't reliably produce both JSON + full text | Quality (0→100%) |
| Feb 1 | Three-layer PII detection | LLM false positives on HR content; Presidio is source of truth | Accuracy (6→0 FP) |
| Feb 1 | Custom PII dictionary (YAML) | User needs to define personal PII terms Presidio can't detect | Coverage |
| Feb 1 | all-MiniLM-L6-v2 for embeddings | Working now; nomic-embed-text was in original plan but MiniLM is wired | Pragmatic |

---

## What's Working

### Working End-to-End
- **Ingestion pipeline**: watchdog → processor → extractor → intelligence → staging → dashboard → executor → archiver + exporter + RAG indexing
- **Dashboard** at localhost:8000: review AI proposals, edit metadata, mark sensitive, commit/skip, **LLM chat** (Ollama + RAG), **memory panel** (user facts + correction patterns)
- **MCP server**: search_knowledge (HyDE, reranking, decay, multi-query, semantic cache), search_by_entity (knowledge graph), list_recent_files, get_folder_structure, get_system_status, get_user_context, add_user_fact, check_stale_content, check_links, create_backup, list_backups, trigger_reindex
- **PII detection**: Presidio + custom dictionary at analysis time, redaction at commit time
- **RAG**: 4702 child chunks + 52 parent chunks from 43 documents, hybrid search with FTS
- **Knowledge graph**: 979 entities, 165 relationships (regex-extracted from indexed docs)
- **Episodic memory**: User profile persistence, fact extraction, session tracking
- **Quality**: Duplicate detection, freshness indicators, link checking (MCP tools)
- **Utilities**: Versioning (content hash + diffs), backup (tar.gz + checksum), checkpoints (resumable batch jobs)
- **OCR**: Vision.framework in extractor (auto-fallback for scanned PDFs)
- **Auto-tagging**: Keyword + embedding hybrid mode (lazy-loaded), runs in processor after PII scan
- **Audio/Video**: mlx-whisper transcription, OpenCV scene detection (graceful fallback)
- **CLI**: All subcommands verified (search, ingest, status, check-links, duplicates, stale, tag)

### Wired But Needs Runtime Setup
- VLM image captioning (`vlm_captioner.py`) — code wired, needs moondream2 model download
- Embedding auto-tagger — code wired, activates when embedding service available

### Scaffold Utils (Future Features)
- ~2500 lines of scaffold utilities remain for future features

---

## Session History

### Sessions 0-1 (Jan 31): Scaffold Phase
- Antigravity agents created 44 modules across 23 directories
- Architecture docs, PRD, conventions established
- **Key gap**: Modules created but not integrated with each other

### Session 2 (Feb 1): Phase 1 — MCP Server Fix
- Rewrote `server.py` for stdio transport + FastMCP lifespan
- Wired: HybridSearcher, EmbeddingService, CrossEncoderReranker, QueryAnalytics
- Created CLAUDE.md

### Session 3 (Feb 1): Intelligence Rewrite
- Split-brain Ollama workflow: Call 1 (JSON metadata) + Call 2 (redacted text)
- First 41-file batch: 41/41 summaries, categories, years
- Found 6 PII false positives → led to PII redesign

### Session 4 (Feb 1): Test Suite Rewrite
- 12 tests across 3 files (integration, HITL, rules)
- All 27 tests passing

### Session 5 (Feb 1): Second Batch + RAG Verification
- 41/41 completed, 0 errors, 0 PII false positives
- RAG: 4702 child chunks, 52 parent chunks
- Avg char ratio 0.9533, word coverage 0.9535

### Session 6 (Feb 1): PII Redesign
- Three-layer detection: Presidio + custom dictionary + LLM advisory
- Manual override on dashboard
- Custom PII dictionary at ~/.pkm/pii_terms.yaml
- 0 false positives (was 6/41)

### Session 7 (Feb 1): Phase 2 — Search Stack Wiring
- Wired HyDE expander (Ollama backend, qwen2.5:32b)
- Fixed HyDE bug (was passing HyDEResult object as string)
- Added time-decay scoring after reranking
- Added multi-query search with RRF fusion

### Session 8 (Feb 1): MCP Desktop Connection + Claude Desktop Review
- Fixed Claude Desktop MCP connection (cwd → permissions → bash inline)
- Removed old va-claims-assistant MCP entry
- Audited RAG: 43 docs, 4,704 chunks, all from Inbox (no project code leaked)
- Claude Desktop reviewed codebase, generated Phase 6 design doc + roadmap
- Planning docs added: `_project/Phase_6_Episodic_Memory.md`, `_project/Roadmap_Future_Enhancements.md`

### Session 9 (Feb 1): Phases 3-12 Completion + Dashboard Enhancements
- Completed all remaining integration phases (3-12)
- Knowledge graph backfill: 43 docs → 979 entities, 165 relationships
- Added LLM chat window to dashboard (Ollama + RAG context from LanceDB)
- Added user memory panel to dashboard (facts + correction patterns)
- Wired session tracking into MCP server (event logging, persistence)
- Installed multimodal deps (opencv-python-headless, mlx-whisper)
- Wired audio/video extraction into extractor.py
- Fixed CLI API mismatches, MCP param bugs, numpy version conflict
- Removed dead code (register_tools), audited all modules
- All 27 tests passing throughout

### Session 10 (Feb 1): End-to-End Verification + Documentation
- Verified all module imports, MCP server, dashboard routes
- All integration checks passing
- Updated project documentation

### Session 11 (Feb 1): Post-Integration Enhancements
- 42 new tests (69 total): chat, auto-tagger, knowledge graph, conflict detector, exporter
- PII dictionary CLI (list/add/remove)
- Embedding auto-tagger wiring (lazy-loaded, hybrid keyword+embedding scoring)
- LLM entity extraction via OllamaLLM wrapper (async, with regex fallback)
- Conflict detector wired as MCP tool
- Obsidian backlinks from knowledge graph shared entities
- QueueManager wired into batch processing (persistent, retry, rate-limited)
- VLM captioner wired into image extraction (graceful fallback)

### Session 12 (Feb 1): Tests, RAG API, Manifest Protocol
- 52 new tests (121 total): MCP tools, decay scoring, HyDE, session tracker
- Auto-tagger threshold tuning + 3 new domain tags (HR, compliance, finance)
- Knowledge graph backfill script updated with --llm flag (async OllamaLLM)
- VLM model (moondream2) downloaded via MLX backend
- Core Memory API v1: manifest, stats, search, ingest, delete endpoints
- Manifest protocol for AI system handshake (Kendra integration ready)

---

## Technology Stack (Actual)

| Component | Choice | Status |
|-----------|--------|--------|
| Vector Database | LanceDB | **Running** |
| Embeddings | all-MiniLM-L6-v2 (384d) | **Running** |
| LLM | Ollama qwen2.5:32b | **Running** |
| MCP Framework | FastMCP (stdio) | **Running** |
| Cross-Encoder | ms-marco-MiniLM-L-6-v2 | **Running** |
| PII Detection | Presidio + spaCy en_core_web_lg + custom dictionary | **Running** |
| HyDE | Ollama-backed hypothetical doc generation | **Wired** |
| Time Decay | Exponential decay on modified_at | **Wired** |
| Multi-Query | QueryDecomposer + RRF fusion | **Wired** |
| Semantic Cache | Cosine similarity 0.92, 24h TTL | **Running** |
| OCR | Apple Vision.framework | **Wired** |
| Audio | mlx-whisper | **Wired** |
| Video | OpenCV scene detection | **Wired** |
| Knowledge Graph | SQLite triple store | **Running** (979 entities) |
| Session Tracking | JSON-persisted event log | **Running** |
| VLM Captioner | moondream2 via MLX | **Running** |
| Core Memory API | REST v1 (manifest, search, ingest) | **Running** |
| Versioning | Content hash + diffs | **Wired** |
| Backup | tar.gz + SHA-256 checksum | **Wired** |

---

## Context for Future Sessions

### User
- TJ, learning Python (course started Feb 3, 2026)
- Prefers local-first for privacy
- Uses Obsidian for visual exploration
- M4 Max 48GB RAM

### Key File Locations
- Dashboard: `src/ui/templates/dashboard.html`, server: `src/server.py` (chat: `/api/chat`, memory: `/api/user-facts`)
- Ingestion: `src/processor.py` → `src/intelligence.py` → `src/staging.py`
- MCP: `src/mcp_server/server.py` + `src/mcp_server/tools.py`
- PII: `src/utils/privacy_audit.py`, custom terms: `~/.pkm/pii_terms.yaml`
- Config: `.env`, `src/config.py`
- Tests: `tests/test_integration.py`, `tests/test_hitl.py`, `tests/test_rules.py`, `tests/test_chat.py`, `tests/test_auto_tagger.py`, `tests/test_knowledge_graph.py`, `tests/test_conflict_detector.py`, `tests/test_exporter.py`

### Open Questions
- [ ] Topic taxonomy (predefined vs AI-generated)?
- [ ] Obsidian vault structure for new categories?
- [ ] Priority file types for next ingestion batch?
- [x] Paid API needed? **No** — Ollama achieves 100% quality
- [x] PII detection approach? **Three-layer** (Presidio + dictionary + LLM advisory)
- [x] Chunking strategy? **Parent-child** (512 token children, 2048 parents)

---

### Planning Documents (from Claude Desktop review)
- `_project/Phase_6_Episodic_Memory.md` — Detailed Phase 6 design: correction learning (SQLite), session events, user context. Code samples are pseudocode — verify scaffold APIs before implementing.
- `_project/Roadmap_Future_Enhancements.md` — P0-P3 roadmap: knowledge graph wiring, episodic memory unification, DB health tools, Obsidian backlinks, dashboard bulk ops, PII management, golden set, gaps analysis, document versioning, learned rules. Time estimates are optimistic.

---

*Last Updated: 2026-02-01 | Session Count: 12 | Status: Integration Complete + RAG API + 121 Tests*
