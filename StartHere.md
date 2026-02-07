# StartHere.md — CoreRag Project Guide

> **Purpose**: This is the single entry point for understanding the CoreRag project. Read this document first, then follow links to deeper documentation as needed. Designed for both human developers and LLM agents.

---

## What Is CoreRag?

CoreRag is a local-first, privacy-preserving knowledge engine optimized for Apple Silicon (M4 Max, 48GB RAM). It ingests documents from an inbox folder, processes them through an AI pipeline (text extraction, three-layer PII detection, LLM-based classification), stages them for human review via a web dashboard, archives originals, and exports redacted markdown to an Obsidian vault. Search is exposed via MCP (stdio) for Claude Desktop and a REST API (v1) for programmatic access.

**CoreRag is the knowledge backend.** A separate external AI assistant project handles the user-facing layer (chat, voice, personality, user memory, skills, intent routing). CoreRag owns: document ingestion, RAG indexing, PII detection, chunking, knowledge graph, quality checks, the HITL dashboard, and Obsidian export. External consumers connect via MCP (stdio) and REST API (`localhost:8000/api/v1/*`).

---

## Document Map

### Primary References

| Document | Path | Purpose |
|----------|------|---------|
| **CLAUDE.md** | [CLAUDE.md](./CLAUDE.md) | AI agent instructions, architecture overview, CLI commands, conventions, wiring status. **Read this for development work.** |
| **README.md** | [README.md](./README.md) | Project overview, quick start, feature list, tech stack |
| **CONVENTIONS.md** | [CONVENTIONS.md](./CONVENTIONS.md) | Coding standards, design patterns, project structure, testing patterns, git commit format |
| **User Guide** | [docs/USER_GUIDE.md](./docs/USER_GUIDE.md) | End-user documentation: installation, CLI usage, search, Claude Desktop setup, troubleshooting |

### Security

| Document | Path | Purpose |
|----------|------|---------|
| **SECURITY.md** | [Security/SECURITY.md](./Security/SECURITY.md) | Secrets management, PII handling, secure coding, pre-commit checklist, incident response |
| Security Terms Template | [Security/.security_terms.example](./Security/.security_terms.example) | Template for custom private terms (employer names, project names) scanned by security_scan.sh |
| PII Terms Template | [Security/pii_terms.example.yaml](./Security/pii_terms.example.yaml) | Template for custom PII dictionary (`~/.corerag/pii_terms.yaml`) |

### Pre-Commit Hooks

| File | Path | Purpose |
|------|------|---------|
| Pre-commit Config | [.pre-commit-config.yaml](./.pre-commit-config.yaml) | Defines pre-commit hooks: security scan, black, ruff, mypy. Install with `pre-commit install` |

### Architecture (16 design documents)

| Document | Path | Covers |
|----------|------|--------|
| System Architecture | [architecture/CoreRag_Design_System_Architecture.md](./architecture/CoreRag_Design_System_Architecture.md) | High-level data flow, component design, implementation phases |
| Data Schema | [architecture/data_schema.md](./architecture/data_schema.md) | LanceDB schemas for Document and Chunk, embedding specs, topic taxonomy |
| MCP Server Design | [architecture/CoreRag_Design_MCP_Server.md](./architecture/CoreRag_Design_MCP_Server.md) | MCP tool endpoints, privacy handling, server config |
| Metadata Schema | [architecture/CoreRag_Design_Metadata_Schema.md](./architecture/CoreRag_Design_Metadata_Schema.md) | Complete metadata spec: identity, temporal, classification, privacy, quality |
| Chunking Strategy | [architecture/CHUNKING_STRATEGY.md](./architecture/CHUNKING_STRATEGY.md) | Parent-child hierarchical chunking, LanceDB schema, retrieval pipeline |
| Search UX | [architecture/SEARCH_UX.md](./architecture/SEARCH_UX.md) | Result presentation, ranking formula, search modes, MCP response format |
| Performance Guide | [architecture/PERFORMANCE_GUIDE.md](./architecture/PERFORMANCE_GUIDE.md) | Apple Silicon M4 Max optimization: MLX, batch sizes, parallelism, benchmarks |
| Hardware Safety | [architecture/HARDWARE_SAFETY.md](./architecture/HARDWARE_SAFETY.md) | Memory thresholds, temperature limits, SafeProcessor, automatic throttling |
| Deployment Options | [architecture/CoreRag_Design_Deployment_Options.md](./architecture/CoreRag_Design_Deployment_Options.md) | Three tiers: fully local, hybrid with APIs, Mac Studio |
| Multimodal Search | [architecture/MULTIMODAL_SEARCH.md](./architecture/MULTIMODAL_SEARCH.md) | Cross-modal search for text, images, audio, video |
| Obsidian Sync | [architecture/OBSIDIAN_SYNC.md](./architecture/OBSIDIAN_SYNC.md) | Bidirectional sync modes, conflict resolution, note templates |
| Resilience | [architecture/RESILIENCE.md](./architecture/RESILIENCE.md) | Checkpoints, deduplication, incremental updates, backup/restore, retry logic |
| Migration Strategy | [architecture/MIGRATION_STRATEGY.md](./architecture/MIGRATION_STRATEGY.md) | Embedding model migration: parallel indexing, validation, cutover |
| Testing Framework | [architecture/TESTING_FRAMEWORK.md](./architecture/TESTING_FRAMEWORK.md) | A/B testing for local vs API models, quality metrics, decision matrix |
| Access Control | [architecture/ACCESS_CONTROL.md](./architecture/ACCESS_CONTROL.md) | Privacy tiers, role-based access, API key management |
| Personal Context | [architecture/CoreRag_Design_Personal_Context.md](./architecture/CoreRag_Design_Personal_Context.md) | "About Me" system for persistent user context (gitignored — contains personal data) |

### Project Planning

| Document | Path | Purpose |
|----------|------|---------|
| **DevPlan.md** | [_project/DevPlan.md](./_project/DevPlan.md) | **Single source of truth**: development history (20 sessions), decisions, wiring plan status, integration protocol, future roadmap (P0-P3) |

The `_project/Archive/` folder contains 13 previously separate planning files consolidated into DevPlan.md on 2026-02-02:
- Session tracking: progress.md, project_memory.md, task_plan.md, findings.md
- Feature designs: KENDRA_INTEGRATION.md, ROADMAP_FUTURE_ENHANCEMENTS.md, PHASE_6_EPISODIC_MEMORY.md, README.md
- Scaffold-phase files (Jan 31): AGENT_INSTRUCTIONS.md, Master_Prompt.md, PRD.md, MIGRATION_LOG.md, SETUP_TASKS.md

### CI/CD

| File | Path | Purpose |
|------|------|---------|
| CI Workflow | [.github/workflows/ci.yml](./.github/workflows/ci.yml) | Lint (ruff, black, isort, mypy), test (Ubuntu + macOS-14, Python 3.11/3.12), security scan (bandit, safety, pip-audit), docs build (mkdocs), package build |
| Release Workflow | [.github/workflows/release.yml](./.github/workflows/release.yml) | Triggered on `v*.*.*` tags. Version validation, full test suite on macOS-14, build artifacts, GitHub Release creation. PyPI publish step present but commented out. |

CI runs on push to `main`/`develop` and on pull requests to `main`. Integration tests run only on `main` pushes (macOS-14 runner for MLX).

### Configuration & Build

| File | Path | Purpose |
|------|------|---------|
| pyproject.toml | [pyproject.toml](./pyproject.toml) | Project metadata, deps, tool config (black, ruff, mypy, pytest) |
| requirements.txt | [requirements.txt](./requirements.txt) | Runtime dependencies (pinned) |
| requirements-dev.txt | [requirements-dev.txt](./requirements-dev.txt) | Dev dependencies (pytest, black, ruff, mypy, profiling, docs) |
| requirements.lock | [requirements.lock](./requirements.lock) | Full dependency lock file (337 packages, generated for Python 3.13.7 arm64) |
| .env.example | [.env.example](./.env.example) | Environment variable template (real `.env` is gitignored) |
| .coreragignore | [.coreragignore](./.coreragignore) | Files excluded from indexing (gitignore syntax) |
| sorting_rules.example.yaml | [sorting_rules.example.yaml](./sorting_rules.example.yaml) | Template for folder categorization rules |
| .gitignore | [.gitignore](./.gitignore) | Git exclusions (secrets, runtime data, caches, IDE files) |

---

## System Architecture

### Two Subsystems

CoreRag has two distinct subsystems that share the same LanceDB database:

```
Subsystem 1: Ingestion + HITL Dashboard
=========================================
  Files arrive in INBOX_PATH
      |
      v
  watchdog.py / batch_processor.py
      |
      v
  processor.py
      |---> extractor.py ............ Text extraction (PDF, DOCX, TXT, MD, images, audio, video)
      |---> intelligence.py ......... LLM analysis (Ollama qwen2.5:32b or Gemini)
      |---> utils/privacy_audit.py .. PII detection (Presidio + custom dictionary)
      |---> classification/auto_tagger.py
      |
      v
  staging.py ........................ Writes to staging_manifest.json
      |
      v
  server.py (localhost:8000) ........ Dashboard for human review
      |
      v
  executor.py (on approval)
      |---> archiver.py ............. Move original to ARCHIVE_PATH/{folder}
      |---> exporter.py ............. Redacted markdown to VAULT_PATH/Ingested/
      |---> _index_in_rag() ......... Chunk + embed + store in LanceDB
      |         |---> chunking/parent_child.py
      |         |---> embeddings/embedding_service.py
      |---> graph/knowledge_graph.py  Entity extraction into knowledge graph


Subsystem 2: MCP Server + Search Stack
========================================
  Claude Desktop (or REST client)
      |
      v
  mcp_server/server.py ............. FastMCP stdio transport
      |
      v
  mcp_server/tools.py .............. CoreRagTools (search, graph, memory, quality, maintenance)
      |
      v
  search/hybrid_search.py .......... Vector (all-MiniLM-L6-v2, 384d) + BM25 + RRF fusion
      |---> [optional] search/reranker.py ........ Cross-encoder reranking
      |---> [optional] search/hyde.py ............ HyDE query expansion
      |---> [optional] search/multi_query.py ..... Query decomposition + RRF
      |---> [optional] search/decay_scoring.py ... Time-weighted + seasonal scoring
      |
      v
  graph/knowledge_graph.py ......... Entity relationship context
  memory/episodic_memory.py ........ User context (facts, preferences)
  analytics/query_analytics.py ..... Query tracking + semantic cache
```

### Intelligence Provider

`src/intelligence.py` auto-selects (all methods are async, using httpx):
- **Ollama** (default): `qwen2.5:32b` locally at `localhost:11434`. Set `OLLAMA_MODEL` to change.
- **Gemini**: Used if `GOOGLE_API_KEY` is set. Faster but sends text to Google.

### PII Detection (Three Layers)

1. **Presidio + spaCy** (`en_core_web_lg`): NER for names, orgs, locations; regex for SSNs, phones, emails, credit cards, API keys.
2. **Custom PII Dictionary** (`~/.corerag/pii_terms.yaml`): User-defined terms matched at confidence=1.0.
3. **LLM Advisory** (`pii_observations`): Free-text field from LLM. Informational only — not used for the `is_sensitive` boolean.

The `is_sensitive` flag is set by layers 1+2 (threshold 0.70). Dashboard "Mark as Sensitive" checkbox allows manual override.

### Memory Safety

- **Batch processor**: Pauses at 92% RAM, resumes at 88%.
- **SafeProcessor**: Pauses at 75% RAM, resumes at 65%.
- `gc.collect()` between files. Embedding batch size 32 for M4 Max.

---

## Source Code Map

### Root-Level Pipeline Modules (`src/`)

| File | Purpose | Status |
|------|---------|--------|
| `config.py` | Centralized config via python-dotenv and `CORERAG_*` env vars | **Wired** |
| `server.py` | FastAPI dashboard server (localhost:8000), REST API v1 | **Wired** |
| `watchdog.py` | File system monitor for INBOX_PATH | **Wired** |
| `batch_processor.py` | Memory-aware batch ingestion | **Wired** |
| `processor.py` | Document processing orchestrator (extract + LLM + PII + staging) | **Wired** |
| `extractor.py` | Multi-format text extraction (routes to OCR, Whisper, VLM, etc.) | **Wired** |
| `intelligence.py` | LLM analysis via Ollama or Gemini (async httpx) | **Wired** |
| `staging.py` | Staging manifest with file locking | **Wired** |
| `executor.py` | Post-approval: redact, archive, export, index, extract entities | **Wired** |
| `archiver.py` | Move originals to archive with sorting rules | **Wired** |
| `exporter.py` | Obsidian vault markdown export | **Wired** |
| `correction_log.py` | Tracks user corrections to AI proposals | **Wired** |
| `folder_manager.py` | Folder structure management | **Wired** |
| `exceptions.py` | Custom exception hierarchy (CoreRagError, ProcessingError, EmbeddingError, DatabaseError, SearchError, ConfigurationError) | **Wired** |
| `rag_verify.py` | RAG index verification utility | **Utility** |

### Subdirectory Modules (`src/`)

| Directory | Purpose | Key File(s) | Status |
|-----------|---------|-------------|--------|
| `mcp_server/` | FastMCP server + tool definitions for Claude Desktop | `server.py`, `tools.py` | **Wired** |
| `search/` | Hybrid search, HyDE, reranker, multi-query, decay scoring | `hybrid_search.py`, `reranker.py`, `hyde.py`, `multi_query.py`, `decay_scoring.py` | **Wired** |
| `embeddings/` | all-MiniLM-L6-v2 with LRU cache, MPS-optimized | `embedding_service.py` | **Wired** |
| `chunking/` | Parent-child hierarchical chunking | `parent_child.py` | **Wired** |
| `chunking/` | ~~AST-based code chunking~~ | ~~`code_chunker.py`~~ | **Deleted** (was orphaned) |
| `classification/` | Keyword + embedding-based auto-tagging | `auto_tagger.py` | **Wired** |
| `quality/` | Duplicate detection, link checker, freshness, conflict detection | `duplicate_detector.py`, `link_checker.py`, `freshness.py`, `conflict_detector.py` | **Wired** (via MCP + CLI) |
| `graph/` | Entity-based knowledge graph (SQLite) | `knowledge_graph.py` | **Wired** (executor + MCP) |
| `memory/` | User facts/preferences for MCP context | `episodic_memory.py` | **Wired** (MCP tools) |
| `analytics/` | Query tracking + semantic cache | `query_analytics.py` | **Wired** (MCP server init) |
| ~~`obsidian/`~~ | ~~Markdown export~~ | — | **Deleted** (logic consolidated in `exporter.py`) |
| `ocr/` | macOS Vision.framework text extraction | `vision_ocr.py` | **Wired** (via extractor) |
| `multimodal/` | LLaVA VLM image captioning | `vlm_captioner.py` | **Wired** (via extractor) |
| `audio/` | mlx-whisper transcription + topic segmentation | `topic_segmentation.py` | **Wired** (via extractor) |
| `video/` | OpenCV keyframe + scene detection | `scene_detector.py` | **Wired** (via extractor) |
| `maintenance/` | LanceDB optimizer, health reports | `db_optimizer.py` | **Wired** (MCP + CLI) |
| `menubar/` | macOS menu bar app (rumps) | `app.py` | **Wired** (standalone) |
| `cli/` | 13 CLI commands | `main.py` | **Wired** |
| `api/` | REST API v1 routes + dashboard routes | `v1_routes.py`, `dashboard_routes.py`, `models.py` | **Wired** (via server.py) |
| `models/` | Dataclasses: Document, Chunk, SearchResult, PersonalContext | `document.py`, `search.py`, `context.py` | **Wired** |
| `ui/` | Dashboard templates and static assets | `templates/`, `static/` | **Wired** (via server.py) |
| ~~`ingestion/`~~ | ~~Pipeline orchestrator scaffold~~ | — | **Deleted** (empty package) |
| ~~`storage/`~~ | ~~LanceDB wrapper scaffold~~ | — | **Deleted** (empty package) |
| ~~`processors/`~~ | ~~File type processors scaffold~~ | — | **Deleted** (empty package) |
| ~~`sync/`~~ | ~~Reconciliation scaffold~~ | — | **Deleted** (empty package) |
| ~~`dashboard/`~~ | ~~Dashboard routes scaffold~~ | — | **Deleted** (empty package) |

### Utilities (`src/utils/`)

| File | Purpose | Status |
|------|---------|--------|
| `safe_processor.py` | Memory throttling and ingestion controller | **Wired** |
| `tagging.py` | TagManager with hierarchy and suggestions | **Wired** |
| `privacy_audit.py` | Presidio + regex PII detection (3-layer) | **Wired** |
| `hardware_monitor.py` | CPU/GPU/memory monitoring | **Wired** |
| `health.py` | System health checks | **Wired** (CLI) |
| `queue_manager.py` | Job queue with rate limiting | **Wired** |
| `throttle_controller.py` | Resource throttling | **Wired** |
| `backup.py` | Backup creation/restore | **Wired** (CLI) |
| `backup_triggers.py` | Auto-backup cooldowns + LanceDB integrity checker | **Wired** (server startup + pre-commit) |
| `checkpoint.py` | Checkpoint management for resumable jobs | Partially wired |
| `versioning.py` | Document version tracking | Partially wired |
| `ollama_llm.py` | Ollama API wrapper | **Wired** |
| ~~`citations.py`~~ | ~~Citation formatting~~ | **Deleted** (orphaned) |
| ~~`collections.py`~~ | ~~Collection management~~ | **Deleted** (orphaned) |
| ~~`coreragignore.py`~~ | ~~gitignore-style file exclusion~~ | **Deleted** (orphaned) |
| `logging_config.py` | Structured JSON logging, rotation, colored console | **Wired** (all entry points) |
| `path_validation.py` | Path traversal attack prevention, security sandbox | **Wired** (NEW) |
| `query_sanitize.py` | LanceDB SQL injection prevention | **Wired** (NEW) |
| `secure_file.py` | Secure file operations with proper permissions | **Wired** (NEW) |

### Tests (`tests/`)

| File | Covers |
|------|--------|
| `conftest.py` | Pytest fixtures and configuration |
| `test_processor.py` | Document processing and PII detection |
| `test_executor.py` | Archive/export/index pipeline execution |
| `test_extractor.py` | Multi-format text extraction (PDF, DOCX, audio, video, images) |
| `test_batch_processor.py` | Batch processing pipeline |
| `test_mcp_tools.py` | MCP tool integration |
| `test_auto_tagger.py` | Auto-tagging classification |
| `test_chat.py` | Chat interface |
| `test_conflict_detector.py` | Contradiction detection |
| `test_decay_scoring.py` | Time-weighted scoring |
| `test_exporter.py` | Obsidian markdown export |
| `test_golden_set.py` | Search quality regression |
| `test_hitl.py` | Human-in-the-loop staging workflow |
| `test_hyde.py` | HyDE query expansion |
| `test_integration.py` | End-to-end pipeline |
| `test_knowledge_graph.py` | Knowledge graph operations |
| `test_rules.py` | Classification rules |
| `test_session_tracker.py` | Session tracking |
| `test_backup_triggers.py` | Auto-backup cooldowns, integrity checks |
| `test_utils.py` | Utility modules, health, logging, versioning |
| `fixtures/sample_documents.py` | Synthetic test data (corpus, PII samples, similarity pairs) |
| `golden_set.yaml` | Golden dataset for regression testing |

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `run_system.sh` | Start server + watchdog + open dashboard (main entry point) |
| `security_scan.sh` | Pre-commit security scanner (secrets, PII, paths, dangerous patterns) |
| `install_menubar.sh` | Install/uninstall menu bar app as login item |
| `run_menubar.sh` | Launch menu bar app |
| `mcp_server.sh` | Launch MCP server for Claude Desktop |
| `install_automation.sh` | Setup automation (watchdog trigger) |
| `setup_folders.py` | Create CoreRag folder structure (inbox, processed, vault) |
| `backfill_knowledge_graph.py` | Backfill knowledge graph (regex or LLM extraction) |
| `test_search_pipeline.py` | End-to-end search quality testing |
| `generate_icons.py` | Generate menu bar app icons |
| `com.user.corerag.example.plist` | launchd template for file watcher automation |
| `com.user.corerag.plist` | Runtime launchd config for watchdog (gitignored) |
| `com.user.corerag-menubar.plist` | launchd config for menu bar auto-launch on login |

### Dashboard UI (`src/ui/`)

| Path | Purpose |
|------|---------|
| `src/ui/templates/dashboard.html` | Full HITL dashboard template (Tailwind CSS, dark theme, chat panel, tag management, PII controls) |
| `src/ui/static/` | Static assets directory (currently empty — Tailwind loaded via CDN) |

### Assets (`assets/`)

| File | Purpose |
|------|---------|
| `assets/menubar_icon.png` | Menu bar app icon (normal state) |
| `assets/menubar_icon_active.png` | Menu bar app icon (active/processing state) |

### Runtime Files (gitignored)

These files are generated at runtime and excluded from version control:

| File | Purpose |
|------|---------|
| `staging_manifest.json` | Documents currently in the ingestion pipeline |
| `automation.log` | Watchdog/launchd automation log |
| `ingestion.log` | Detailed processing log |
| `server.log` | Dashboard server log |
| `.coverage` | pytest coverage data |

---

## Known Discrepancies

These are differences between what documentation claims and what the code actually does:

| Item | Documentation Claim | Actual State |
|------|-------------------|--------------|
| AST Code Chunking | CLAUDE.md: "code_chunker.py exists but not imported" | **Resolved** — `chunking/code_chunker.py` deleted |
| Spreadsheet Processing | README: listed as supported | **Resolved** — `processors/spreadsheet_processor.py` deleted |
| Ingestion pipeline | Listed as "Unwired" | **Resolved** — both `src/ingestion.py` and `src/ingestion/pipeline.py` deleted |
| Zombie Reconciliation | Existed but never called | **Resolved** — `sync/reconciliation.py` deleted |
| Orphaned utility modules | 6+ utils completely orphaned | **Resolved** — deduplication, export, feedback, incremental, search_history, citations, collections, coreragignore all deleted. retry.py re-added and wired. |
| Health Dashboard | Existed but minimal use | **Resolved** — `dashboard/health_dashboard.py` deleted |
| Embedding model | CONVENTIONS.md says `nomic-embed-text-v1.5` (768d) | **Resolved** — CONVENTIONS.md corrected to `all-MiniLM-L6-v2` (384d) |
| Empty __init__.py exports | Several `__init__.py` files export from deleted modules | **Resolved** — broken packages fixed or deleted |

---

## Development Status

### 12-Phase Wiring Plan

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Fix MCP Server (stdio transport, FastMCP) | **Complete** |
| -- | PII Redesign (three-layer detection, custom dictionary, manual override) | **Complete** |
| 2 | Wire Search Stack (HyDE, multi-query, decay scoring) | **Complete** |
| 3 | Wire OCR into ingestion | **Complete** |
| 4 | Wire auto-tagging | **Complete** |
| 5 | Wire knowledge graph | **Complete** |
| 6 | Wire episodic memory | **Complete** (handed off to external AI assistant) |
| 7 | Wire quality modules | **Complete** |
| 8 | Wire utility modules | **Complete** — logging, retry, exceptions, SafeProcessor, QueueManager all wired |
| 9 | Wire analytics and queue | **Complete** |
| 10 | Wire multimodal | **Complete** |
| 11 | Config cleanup and dead code removal | **Complete** — all constants centralized, dead code removed |
| 12 | CLI integration | **Complete** (13 commands) |

### Remaining Work

All 12 phases are **complete**. Future enhancements tracked in the [Roadmap](#roadmap-summary) below.

---

## Roadmap Summary

Full details in [_project/DevPlan.md](./_project/DevPlan.md#future-roadmap).

| Priority | Item | Status |
|----------|------|--------|
| **P0** | Knowledge Graph MCP integration | **Complete** |
| **P0** | Database Health MCP tools | **Complete** |
| **P0** | PII Dictionary management | **Complete** |
| **P0** | Security hardening (path validation, query sanitization, secure file ops) | **Complete** |
| **P1** | Obsidian backlinks enhancement | **Complete** (Session 19) |
| **P1** | Dashboard bulk operations and keyboard navigation | **Complete** (Session 19) |
| **P1** | Golden Set auto-population from analytics | **Complete** (Session 19) |
| **P2** | Knowledge gaps analysis | **Complete** (Session 19) |
| **P2** | Document versioning enhancement | **Complete** (Session 19) |
| **P2** | Learned sorting rules from correction patterns | **Complete** (Session 19) |
| **P3** | Multi-vault, collaborative, integrations, conversational search, mobile | **Complete** (Session 19) |
| — | Auto-backup + LanceDB integrity checking | **Complete** (Session 20) |

---

## Quick Reference

### Running the System

```bash
./scripts/run_system.sh                  # Server + watchdog + dashboard
python -m src.server                     # Dashboard server only (port 8000)
python -m src.watchdog                   # File watcher only
python -m src.mcp_server.server          # MCP server for Claude Desktop (stdio)
python -m src.menubar                    # Menu bar app
```

### CLI Commands

```bash
python -m src.cli.main status            # System health
python -m src.cli.main search "query"    # Semantic search
python -m src.cli.main ingest /path -r -t tag1  # Ingest with tags
python -m src.cli.main check-links /path # Find broken URLs
python -m src.cli.main duplicates /path  # Detect duplicates
python -m src.cli.main stale /path       # Find outdated content
python -m src.cli.main tag /path         # Auto-tag files
python -m src.cli.main pii list          # Manage PII dictionary
python -m src.cli.main health            # System health checks
python -m src.cli.main optimize-db       # Optimize LanceDB
python -m src.cli.main backup create     # Create backup
python -m src.cli.main graph stats       # Knowledge graph stats
python -m src.cli.main memory list       # User facts
```

### REST API (v1)

```bash
curl http://localhost:8000/api/v1/manifest            # Capability discovery
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "...", "k": 5, "tags": ["tag1"]}'    # Search
curl http://localhost:8000/api/v1/stats               # Database stats
```

### Testing and Quality

```bash
pytest                                   # All tests with coverage
pytest -m "not slow"                     # Skip slow tests
pytest -m "not integration"              # Skip integration tests
black src/ tests/ --line-length 100      # Format
ruff check src/ tests/                   # Lint
mypy src/                                # Type check
./scripts/security_scan.sh --staged      # Pre-commit security scan
```

### Key Entry Points

| Entry Point | Module | Transport |
|-------------|--------|-----------|
| Dashboard + REST API | `python -m src.server` | HTTP (localhost:8000) |
| MCP Server | `python -m src.mcp_server.server` | stdio |
| CLI | `python -m src.cli.main` | Terminal |
| File Watcher | `python -m src.watchdog` | Filesystem events |
| Menu Bar | `python -m src.menubar` | macOS native |

### Key Configuration

| File | Location | Gitignored |
|------|----------|------------|
| `.env` | Project root | Yes (use `.env.example`) |
| `sorting_rules.yaml` | Project root | Yes (use `sorting_rules.example.yaml`) |
| `pii_terms.yaml` | `~/.corerag/pii_terms.yaml` | N/A (user home) |
| `.security_terms` | `Security/.security_terms` | Yes (use `.security_terms.example`) |
| `staging_manifest.json` | Project root | Yes (runtime data) |
| LanceDB database | `~/.corerag/lancedb/` | N/A (user home) |
| Knowledge graph | `~/.corerag/knowledge_graph.db` | N/A (user home) |
| Logs | `~/.corerag/logs/` | N/A (user home) |

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `INBOX_PATH` | `~/Desktop/Inbox` | Watched folder for new documents |
| `VAULT_PATH` | `~/Documents/ObsidianVault` | Obsidian vault for markdown exports |
| `ARCHIVE_PATH` | `~/Documents` | Long-term storage for originals |
| `GOOGLE_API_KEY` | (none) | Optional: enables Gemini instead of Ollama |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:32b` | Ollama model for analysis |
| `CORERAG_DB_PATH` | `~/.corerag/lancedb` | LanceDB database path |
| `CORERAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model |
| `CORERAG_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker model |
| `CORERAG_BACKUP_ENABLED` | `true` | Enable auto-backup on startup/pre-commit |
| `CORERAG_BACKUP_STARTUP_COOLDOWN` | `24` | Hours between startup backups |
| `CORERAG_BACKUP_COMMIT_COOLDOWN` | `1` | Hours between pre-commit backups |
| `CORERAG_BACKUP_MAX_COUNT` | `10` | Maximum backups to retain |

---

## File Type Support

| Category | Extensions | Processing Method |
|----------|-----------|-------------------|
| Documents | `.pdf`, `.docx`, `.txt`, `.md` | Text extraction, parent-child chunking |
| Data | `.json`, `.yaml`, `.csv`, `.log` | Structured parsing |
| Images | `.png`, `.jpg`, `.webp`, `.heic` | Vision.framework OCR + VLM captioning |
| Audio | `.mp3`, `.wav`, `.m4a` | mlx-whisper transcription + topic segmentation |
| Video | `.mp4`, `.mov` | Keyframe + scene detection + audio extraction |
| Planned | `.xlsx`, `.xls` | Spreadsheet processor — needs reimplementation |
| Planned | `.py`, `.js`, `.ts`, `.go`, `.rs` | AST code chunker — needs implementation |

---

## Technology Stack

| Component | Technology | Dimension/Detail |
|-----------|------------|-----------------|
| Vector Database | LanceDB | Embedded, Lance format |
| Embeddings | all-MiniLM-L6-v2 | 384d, sentence-transformers |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 | Cross-encoder |
| LLM (local) | Ollama + qwen2.5:32b | Classification, summarization, PII advisory |
| LLM (cloud) | Google Gemini | Optional alternative |
| PII Detection | Presidio + spaCy en_core_web_lg | NER + regex |
| Audio | mlx-whisper | Apple Silicon transcription |
| Video | OpenCV | Keyframe + scene detection |
| OCR | Vision.framework | Native macOS |
| VLM | LLaVA | Image captioning |
| MCP | FastMCP | stdio transport for Claude Desktop |
| Web Framework | FastAPI + Jinja2 | Dashboard + REST API |
| Menu Bar | rumps | macOS native |

---

*Last updated: 2026-02-07 — 305 tests. All P1-P3 roadmap items complete. Auto-backup + integrity checking. Mypy clean (0 errors, 93 files).*
