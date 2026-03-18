# Changelog

All notable changes to CoreRag are documented here.

## [0.3.0] - 2026-03-18

### P9 Codebase Hardening (Session 33 — 2026-03-17/18)

4 waves, 29 tech debt items resolved, 36 commits, 924 tests passing.

**Wave 1 — Security Hardening**
- **CSRF Protection**: Token-based CSRF middleware on all state-changing dashboard endpoints
- **XSS Escaping**: HTML-escape all user-controlled values rendered in dashboard templates
- **PII Redaction Fail-Safe**: Executor raises `ProcessingError` if redaction produces no output for sensitive docs (prevents silent data leaks)
- **Input Validation**: Tightened boundary validation on document commit and ingest paths

**Wave 2 — Async & Performance**
- **asyncio.to_thread**: Blocking I/O calls (file read, SQLite, disk writes) wrapped in `asyncio.to_thread` to avoid blocking the FastAPI event loop
- **LanceDB Connection Caching**: `HybridSearcher` caches LanceDB connection per-instance; eliminated repeated re-opens on every search call
- **Embedding Singleton**: `EmbeddingService` uses a module-level singleton so the BGE-M3 model loads once per process
- **SQLite Context Managers**: All SQLite accesses in `knowledge_graph.py` and `catalog_manager.py` use `with` context managers (proper connection cleanup)
- **Thread-Safe Cache**: `SemanticCache` and `QueryAnalytics` caches use `threading.Lock` for safe concurrent access
- **OrderedDict LRU**: Embedding cache uses `OrderedDict` with explicit LRU eviction (replaces unbounded dict)
- **threading.Event for Commit Control**: Batch processor uses `threading.Event` for clean shutdown signal instead of bare flag

**Wave 3 — Test Coverage**
- 229 new tests across 6 new test files: `test_path_validation.py`, `test_query_sanitize.py`, `test_secure_file.py`, `test_settings_routes.py`, `test_ingest_service.py`, `test_hybrid_search_extended.py`
- Total: 924 passing, 2 pre-existing failures (tracked), 26 skipped

**Wave 4 — Docs & Config**
- Updated CLAUDE.md, README.md, DevPlan.md, CHANGELOG.md, StartHere.md
- Verified requirements.txt current
- Tech debt tracker: 10 open (0 critical, 1 high, 3 medium, 6 low) + 1 blocked + 2 deferred

### P8 Second Brain (Sessions 32-33 — 2026-03-15)

- **Dual RAG Databases**: Main (`~/.corerag/lancedb/`) for redacted content + Restricted (`~/.corerag/lancedb-restricted/`) for unredacted sensitive docs. `search_scope` parameter on all search paths.
- **Document Catalog**: SQLite at `~/Documents/PKM/_catalog.db` tracking 102 documents across all destinations (RAG, Obsidian, archive). Cold storage migration with folder replication.
- **Per-Agent Access Control**: `SettingsManager` manages agent CRUD, per-action permission toggles, API key management, LLM config. Replaces single `CORERAG_API_KEY`. `src/auth/access_control.py` deprecated.
- **Dashboard Settings Tab**: Agent CRUD UI, LLM provider/model selector, DB stats and actions.
- **Per-Detection Redaction Editor**: Dashboard shows each PII detection with Keep/Redact toggle; executor honors overrides at commit time.
- **Quality Banner**: Displays chunk count, quality scores, and indexing warnings per document.
- **Skip Button**: Documents can be skipped without approval or error.
- **Archive Manager**: Browse, search, and filter cataloged documents; cold storage migration with folder structure replication.
- **Codex CLI Provider**: 6th LLM provider (`codex-cli`) using OpenAI Codex CLI subprocess.

## [0.2.0] - 2026-02-27

### Retrieval Enhancement (Sessions 22-25)

- **Embedding Upgrade**: Migrated from all-MiniLM-L6-v2 (384d) to BAAI/bge-m3 (1024d) for improved retrieval quality
- **LLM Provider Abstraction**: Unified async interface supporting Ollama, Gemini, Anthropic API, and Claude CLI providers
- **Answer Synthesis**: Citation-validated answer generation with two-pass verification
- **Corrective RAG**: 3-tier post-retrieval relevance filtering (correct/ambiguous/incorrect)
- **Contextual Retrieval**: LLM-generated context prefixes for chunks with SHA256 caching
- **Chunk Quality Scoring**: Heuristic 0.0-1.0 scoring (density, completeness, length, coherence)
- **Source Authority Classification**: Tag/category/extension-based authority ranking
- **Content Hash Dedup**: SHA256-based duplicate chunk detection at index time
- **Date Extraction**: Regex-based date extraction (ISO, US, EU formats) with confidence scoring
- **Multi-Resolution Summaries**: Async LLM-generated parent chunk summaries
- **Bitemporal Knowledge Graph**: first_seen/last_seen/mention_count on entities, when_true/when_learned/superseded_by on relationships, confidence decay
- **RAGAS Evaluator**: Context precision, recall, faithfulness, and answer relevancy metrics
- **Embedding Migration Script**: `scripts/migrate_embeddings.py` for re-embedding with dimension changes
- **Search Pagination**: Offset-based pagination with has_more indicator on search results
- **Auto-Port Fallback**: Server finds available port if 8000 is busy, writes port file
- **Test Suite**: 544 tests passing (0 failures, 26 skipped)

### Production Hardening (Sessions 21-24)

- **API Error Codes**: Proper HTTP status codes (4xx/5xx) via JSONResponse
- **API Expansion**: GET document metadata, bulk delete, category search filter (11 v1 endpoints)
- **LLM Provider**: ClaudeCliProvider for Pro Max plan (no API key), AnthropicProvider for direct API
- **Security Scanner v7**: 14-phase scan including ecosystem reference detection
- **Pre-commit Hooks**: black, ruff, mypy (warn-only), security_scan.sh

## [0.1.0] - 2026-02-07

Initial public release of CoreRag — a local-first, privacy-preserving knowledge engine for Apple Silicon.

### Features

- **Document Ingestion Pipeline**: Watchdog + batch processor with three-layer PII detection (Presidio NER, custom dictionary, LLM advisory), AI classification via Ollama/Gemini, and HITL dashboard for review
- **RAG Search**: Hybrid vector + BM25 search via LanceDB, cross-encoder reranking, HyDE query expansion, multi-query fusion, and time-decay scoring
- **MCP Server**: FastMCP stdio transport for Claude Desktop integration with 12 tools (search, ingest, quality checks, knowledge graph, episodic memory)
- **REST API v1**: Five endpoints (manifest, stats, search, ingest, delete) with API key auth and rate limiting via slowapi
- **Knowledge Graph**: Entity extraction and relationship mapping (regex + LLM) with SQLite storage
- **Episodic Memory**: User fact tracking and correction patterns for personalized search context
- **HITL Dashboard**: Web UI at localhost:8000 for reviewing AI proposals, editing metadata, managing tags, browsing RAG index, and chatting with knowledge base
- **CLI**: 13 commands covering search, ingest, status, quality checks, PII management, backups, knowledge graph, and episodic memory
- **Multimodal Support**: PDF (with OCR fallback), DOCX, TXT, Markdown, JSON, YAML, CSV, images (Vision.framework OCR + VLM captioning), audio (mlx-whisper), video (OpenCV keyframe + scene detection)
- **Memory Safety**: Two-tier RAM monitoring — batch/commit pauses at 92%, SafeProcessor pauses at 75% — with gc.collect() between files
- **Collection Tags**: Isolate source material for focused search sessions with tag-based filtering at ingest and query time
- **Obsidian Export**: Redacted markdown export with backlinks to Obsidian vault
- **macOS Menu Bar App**: Status polling, dashboard launcher, auto-start via rumps
