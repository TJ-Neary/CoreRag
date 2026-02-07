# Changelog

All notable changes to CoreRag are documented here.

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
