# PKM System - Task Plan

---

## Status: INTEGRATION PHASE — 12 of 12 Complete ✅

The initial scaffold (44 modules) was created by Antigravity agents on Jan 31. Most modules were NOT wired into the running system. This plan tracks the integration work to connect everything.

---

## Completed Work

### Phase 1: Fix MCP Server ✅
- [x] Rewrite `src/mcp_server/server.py` with stdio transport + FastMCP lifespan
- [x] Fix `PKMTools` class and `search_knowledge` in `tools.py`
- [x] Wire: HybridSearcher, EmbeddingService, CrossEncoderReranker, QueryAnalytics
- [x] Create CLAUDE.md with architecture documentation
- [x] Configure Claude Desktop MCP connection

### Intelligence Rewrite ✅
- [x] Rewrite `src/intelligence.py` with split-brain Ollama workflow
- [x] Call 1: structured JSON (category, year, type, summary, filename)
- [x] Call 2: full redacted text generation
- [x] Result: 41/41 summaries (was 0/41 before)

### PII Redesign ✅
- [x] Three-layer PII detection: Presidio scan + custom dictionary + LLM advisory
- [x] Custom PII dictionary at `~/.pkm/pii_terms.yaml`
- [x] Manual override on dashboard ("Mark as Sensitive")
- [x] Dashboard label alignment (SENSITIVE/CLEAR)
- [x] Correction log tracks `pii_source` overrides
- [x] Result: 0 false positives (was 6/41)

### Test Suite Rewrite ✅
- [x] `test_integration.py` — 5 tests for process_document() staging
- [x] `test_hitl.py` — 4 tests for staging API + execution flow
- [x] `test_rules.py` — 3 tests for sorting rules override
- [x] All 27 tests passing

### Phase 2: Wire Search Stack ✅
- [x] Wire HyDE expander via `create_hyde_expander()` with Ollama backend
- [x] Fix HyDE bug (was passing HyDEResult object, now uses `.hypothetical_document`)
- [x] Add time-decay scoring after reranking
- [x] Add multi-query search with RRF fusion
- [x] Export decay_scoring from `src/search/__init__.py`

---

## Remaining Phases

### Phase 3: Wire OCR into Ingestion ✅
- [x] Integrated `src/ocr/vision_ocr.py` into `src/extractor.py`
- [x] Added image file support (PNG, JPG, JPEG, TIFF, WebP, BMP, HEIC)
- [x] Added OCR fallback for scanned PDFs (auto-detects <50 chars from pypdf → triggers Vision OCR)
- [x] Installed dependencies: PyMuPDF, Pillow, pyobjc-framework-Vision, pyobjc-framework-Quartz
- [x] Updated requirements.txt with OCR dependencies
- [x] Verified: text PDFs still use fast pypdf path, image OCR uses Vision.framework (vision_pyobjc backend)

### Phase 4: Wire Auto-Tagging ✅
- [x] Integrated `AutoTagger` into `src/processor.py` (singleton, keyword-based, runs after PII scan)
- [x] Tags stored in `metadata.tags` and `proposed.tags` in staging manifest
- [x] Suggested tags stored in `metadata.suggested_tags`
- [x] Dashboard shows tags as blue badges, suggested tags as gray badges with `?` suffix
- [x] Default taxonomy: 15 tags across document-type, technology, status, priority, content-type categories
- Note: Keyword thresholds could be tuned (some false positives on low-specificity words). Embedding tagger available but not wired (needs embedder function passed to AutoTagger)

### Phase 5: Wire Knowledge Graph ✅
- [x] Added `_extract_entities()` in `executor.py` — runs regex-based `EntityExtractor` after RAG indexing
- [x] Replaced `search_by_entity` stub in `tools.py` with real `KnowledgeGraph.get_neighbors()` queries
- [x] KnowledgeGraph initialized in `server.py` `_startup()` at `~/.pkm/knowledge_graph.db`
- [x] Graph passed to PKMTools via `knowledge_graph` constructor param
- [ ] Backfill: existing 43 documents not yet in graph (would need re-ingestion or batch extraction script)
- Note: Regex extractor captures single-word relationship subjects/objects. LLM-based extraction (pass Ollama to EntityExtractor) would produce better multi-word entity relationships

### Phase 6: Wire Episodic Memory ✅
- [x] **6a: Correction Learning** — Already wired: `correction_log.py` captures diffs at commit time, `get_recent_examples()` injects few-shot examples into `intelligence.py` prompt (line 123-124)
- [x] **6c: User Context** — `get_user_context` wired to `EpisodicMemoryManager` (loads profile from `~/.pkm/profiles/default.json`) + correction patterns from `corrections_log.json`
- [x] **6c: add_user_fact** — Wired to `EpisodicMemoryManager.add_fact()` with category mapping (personal, preference, technical, work, etc.)
- [ ] **6b: Session Events** — Not yet wired (session tracking, tool call logging, LLM summarization). Deferred — adds complexity without immediate user value.
- [ ] **6d: Polish** — Dashboard panel for facts/corrections. Deferred.
- See `_project/Phase_6_Episodic_Memory.md` for full design

### Phase 7: Wire Quality Modules ✅
- [x] `duplicate_detector.py` — already wired in processor.py (singleton `_dedup`, pre-ingest check)
- [x] `freshness.py` — freshness indicators added to search results in `_format_results()`, `check_stale_content` MCP tool registered
- [x] `link_checker.py` — `check_links` MCP tool registered (async, cached, rate-limited)
- [ ] `conflict_detector.py` — deferred (lower priority, needs embedder for semantic detection)

### Phase 8: Wire Utility Modules ✅
- [x] Wire `src/utils/versioning.py` — `VersionManager.create_version()` called in `executor.py` after commit (tracks document content hash, diffs, version history at `~/.pkm/versions/`)
- [x] Wire `src/utils/backup.py` — `create_backup` and `list_backups` MCP tools registered in `server.py` (tar.gz with checksum, auto-rotation)
- [x] Wire `src/utils/checkpoint.py` — `CheckpointManager` used by `trigger_reindex` for resumable batch reindex jobs
- [ ] Evaluate and remove dead utility code (deferred to Phase 11)

### Phase 9: Wire Analytics & Queue ✅
- [x] Wire `SemanticCache` (in `query_analytics.py`) into `search_knowledge()` — cache check before search, cache store after (cosine similarity 0.92, 24h TTL, 1000 entries)
- [x] Wire `trigger_reindex` — real implementation: scans vault for files, filters already-indexed, creates CheckpointManager job
- [x] `get_ingestion_queue` — already reads staging manifest (wired in Phase 7)
- [ ] Wire `src/utils/queue_manager.py` into watchdog/batch_processor (deferred — QueueManager is more useful for high-volume parallel processing; current single-file watchdog flow doesn't need it)

### Phase 10: Wire Multimodal ✅
- [x] Wire audio extraction — `WhisperWithSegmentation` for MP3/WAV/M4A/FLAC/OGG/AAC; outputs chaptered document if topic segmentation succeeds, raw transcript otherwise
- [x] Wire video extraction — `VideoProcessor` for MP4/MOV/AVI/MKV/WebM; scene detection + `as_searchable_document()` for indexable text
- [x] Add file type routing in `extractor.py` — new `_AUDIO_EXTENSIONS`, `_VIDEO_EXTENSIONS` sets with graceful `ImportError` fallback
- [ ] Wire `src/multimodal/vlm_captioner.py` for image captioning (deferred — requires VLM model download; OCR handles text extraction already; VLM captioning is additive for diagram understanding)

### Phase 11: Config Cleanup & Dead Code Removal ✅
- [x] Audited all modules for dead/unreachable code
- [x] Removed dead `register_tools()` function from `tools.py` (40 lines — superseded by direct `@mcp.tool()` decorators in `server.py`)
- [x] Identified 7 unwired scaffold utils: `collections.py`, `tagging.py`, `search_history.py`, `feedback.py`, `health.py`, `export.py`, `citations.py` — ~2500 lines, left in place as future features
- [x] Identified empty `src/storage/` directory (shell only, `__init__.py` with empty `__all__`)
- [x] `src/ingestion/pipeline.py` and `src/obsidian/` used only by CLI (Phase 12)
- Note: Config values all used — `.env` vars read by `config.py` and `server.py`

### Phase 12: CLI Integration ✅
- [x] Verified all CLI subcommands use correct module APIs
- [x] Fixed `cmd_duplicates` — updated field names to match `DuplicateReport` (`total_files`, `exact_duplicates`/`near_duplicates`/`semantic_duplicates`, `space_reclaimable_bytes`, `matches`)
- [x] Fixed `check_stale_content` MCP tool — corrected param name `stale_threshold_days` → `stale_days`
- [x] Tested `search` and `status` commands end-to-end (working)
- [x] CLI commands verified: search, ingest, status, check-links, duplicates, stale, tag
- [ ] Add CLI for custom PII dictionary management (deferred — low priority, can edit `~/.pkm/pii_terms.yaml` directly)

---

## Module Wiring Status

| Module | Created | Wired | Notes |
|--------|---------|-------|-------|
| `mcp_server/server.py` | Jan 31 | **Feb 1** | Rewritten for stdio + FastMCP |
| `mcp_server/tools.py` | Jan 31 | **Feb 1** | HyDE, decay, multi-query wired |
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
| `ocr/vision_ocr.py` | Jan 31 | **Feb 1** | Wired into extractor.py with auto-fallback |
| `classification/auto_tagger.py` | Jan 31 | **Feb 1** | Wired into processor.py + dashboard |
| `graph/knowledge_graph.py` | Jan 31 | **Feb 1** | Wired into executor + MCP tools |
| `memory/episodic_memory.py` | Jan 31 | **Feb 1** | Wired: get_user_context + add_user_fact in MCP tools |
| `quality/duplicate_detector.py` | Jan 31 | **Feb 1** | Pre-ingest check in processor.py |
| `quality/link_checker.py` | Jan 31 | **Feb 1** | MCP tool: check_links |
| `quality/freshness.py` | Jan 31 | **Feb 1** | Search result enrichment + MCP tool: check_stale_content |
| `analytics/query_analytics.py` (SemanticCache) | Jan 31 | **Feb 1** | Wired into search_knowledge() for cache hit/store |
| `utils/versioning.py` | Jan 31 | **Feb 1** | Version tracking in executor.py at commit time |
| `utils/backup.py` | Jan 31 | **Feb 1** | MCP tools: create_backup, list_backups |
| `utils/checkpoint.py` | Jan 31 | **Feb 1** | Used by trigger_reindex for resumable batch jobs |
| `audio/topic_segmenter.py` | Jan 31 | **Feb 1** | Wired in extractor.py (graceful fallback) |
| `video/scene_detector.py` | Jan 31 | **Feb 1** | Wired in extractor.py (graceful fallback) |
| `multimodal/vlm_captioner.py` | Jan 31 | — | Deferred (requires VLM model download) |
| `memory/episodic_memory.py` (SessionTracker) | Feb 1 | **Feb 1** | MCP server event logging + persistence |
| `server.py` (Dashboard) | Jan 31 | **Feb 1** | Chat window + memory panel added |
| `cli/main.py` | Jan 31 | **Feb 1** | API mismatches fixed, all commands verified |

---

*Last Updated: 2026-02-01*
