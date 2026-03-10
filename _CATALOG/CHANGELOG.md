# Changelog

All notable changes to CoreRag are documented here.

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
