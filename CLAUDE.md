# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🔒 HQ Access Level: PUBLIC

This is a **PUBLIC repository**. Content restrictions apply.

**Allowed HQ reads:**
- `~/Tech_Projects/_HQ/me/persona_public.md` ✅
- `~/Tech_Projects/_HQ/standards/*` ✅
- `~/Tech_Projects/_HQ/guides/*` ✅
- `~/Tech_Projects/_HQ/templates/*` ✅

**Blocked:**
- `~/Tech_Projects/_HQ/me/persona.md` (CONTEXT-ONLY sections) ❌
- `~/Tech_Projects/_HQ/me/_private/*` ❌
- `~/Tech_Projects/_HQ/sessions/*` ❌

**Rule:** Never output personal context to any file in this repo.

## Commercial IP (mark with `# COMMERCIAL:`)

CoreRag is a public project. All current patterns are standard RAG architecture with no proprietary business logic. **No code in this project should need COMMERCIAL markers.**

If this changes (e.g., novel scoring algorithms, proprietary search techniques), add the categories here and Claude Code will mark them automatically.

**Security rules:** If adding prompt injection detection or custom security patterns, use `# SECURITY-CONFIG:` markers and externalize the actual detection rules to `~/.corerag/security_rules.yaml` (gitignored). Publish the engine, not the rules.

---

## Project Overview

CoreRag is a local-first, privacy-preserving knowledge engine running on Apple Silicon (M4 Max, 48GB RAM). It ingests documents from an inbox folder, processes them through an AI pipeline (text extraction, three-layer PII detection, LLM-based classification), stages them for human review via a web dashboard, then archives originals and exports redacted markdown to an Obsidian vault. Search is exposed via MCP (stdio) and REST API v1.

**CoreRag is the knowledge engine; a separate AI assistant project handles the user-facing layer.** That external project owns chat, voice, personality, user memory, skills, and intent routing. CoreRag owns document ingestion, RAG indexing, PII detection, chunking, knowledge graph, quality checks, the HITL dashboard, and Obsidian export. External consumers connect via MCP client (stdio) and REST API (`localhost:8000/api/v1/*`), using the manifest endpoint for capability discovery.

**Development Planning**: See [`_project/DevPlan.md`](./_project/DevPlan.md) for the full development history, architectural decisions, wiring plan status, external integration protocol, future roadmap (P0-P3), and project audit findings.

## Development Commands

### Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # Runtime deps
pip install -r requirements-dev.txt      # Dev deps (pytest, black, ruff, mypy)
python -m spacy download en_core_web_lg  # PII detection NER model
```

### Running the System
```bash
./scripts/run_system.sh                  # Starts server + watchdog + opens dashboard
python -m src.server                     # Dashboard server only (port 8000)
python -m src.watchdog                   # File watcher only
python -m src.mcp_server.server          # MCP server for Claude Desktop (stdio)
python -m src.menubar                    # Menu bar app (opens dashboard, shows status)
./scripts/install_menubar.sh             # Install menu bar app as login item
./scripts/install_menubar.sh --remove    # Uninstall menu bar login item
```

### CLI
```bash
python -m src.cli.main status
python -m src.cli.main search "query"
python -m src.cli.main ingest /path/to/folder -r -t sphr-study -t cert-prep
python -m src.cli.main check-links /path
python -m src.cli.main duplicates /path
python -m src.cli.main stale /path --days 365
python -m src.cli.main tag /path
python -m src.cli.main pii list              # Manage custom PII dictionary
python -m src.cli.main pii add "John" --type NAME
python -m src.cli.main pii remove "John"
python -m src.cli.main health                # System health checks
python -m src.cli.main optimize-db           # Optimize LanceDB (--report-only for stats)
python -m src.cli.main backup create         # Create backup (also: list, restore, cleanup)
python -m src.cli.main graph stats           # Knowledge graph stats
python -m src.cli.main graph query "entity"  # Find entity connections
python -m src.cli.main graph path "A" "B"    # Find path between entities
python -m src.cli.main memory list           # List user facts (also: add, context, export)
```

### Core Memory API (v1) — For External AI Systems

**Authentication**: Set `CORERAG_API_KEY` in `.env` to enable API key auth. Include `X-API-Key` header in requests. The `/api/v1/manifest` endpoint is always public for capability discovery.

```bash
# Capability manifest (handshake protocol — no auth required)
curl http://localhost:8000/api/v1/manifest

# Semantic search (optionally filter by collection tags)
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"query": "authentication setup", "k": 5, "tags": ["sphr-study"]}'

# Ingest content
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"content": "...", "source": "my-app", "metadata": {"category": "notes"}}'

# Database stats
curl -H "X-API-Key: your_api_key" http://localhost:8000/api/v1/stats

# Delete document
curl -X DELETE -H "X-API-Key: your_api_key" http://localhost:8000/api/v1/documents/{document_id}
```

### Knowledge Graph Backfill
```bash
python scripts/backfill_knowledge_graph.py           # Regex patterns (fast)
python scripts/backfill_knowledge_graph.py --llm      # LLM extraction (better)
python scripts/backfill_knowledge_graph.py --llm --clear  # Clear + re-extract
```

### Testing
```bash
pytest                                    # All tests with coverage (config in pyproject.toml)
pytest tests/test_utils.py               # Single test file
pytest -k "test_name"                    # Single test by name
pytest -m "not slow"                     # Skip slow tests
pytest -m "not integration"             # Skip integration tests
pytest -m "not requires_mlx"            # Skip Apple Silicon tests
```

Pytest is configured with `--cov=src --cov-report=term-missing` and `asyncio_mode = "auto"` by default.

### Data Sanitization

**Read `SECURITY.md` before committing.** Key rules:
- No real names, emails, usernames, or hardcoded `/Users/...` paths in tracked files
- User-specific configs use the `.example` template pattern (real file gitignored)
- Scripts use dynamic path resolution (`SCRIPT_DIR`, env vars), not hardcoded paths
- Test fixtures use only synthetic data
- Session logs and progress files stay gitignored

**Run the security scanner before every commit:**
```bash
./scripts/security_scan.sh              # Scan all tracked files
./scripts/security_scan.sh --staged     # Scan only staged changes
./scripts/security_scan.sh --fix        # Show suggested fixes
```

Scans for: API keys/secrets, hardcoded user paths, PII (SSN, email, phone, credit card), sensitive files that should be gitignored, database/binary files, dangerous code patterns (`shell=True`, `verify=False`, `0.0.0.0` binding, `eval()`). Custom private terms (employer names, project names) can be added to `.security_terms` (gitignored; see `.security_terms.example`).

### Linting & Formatting
```bash
black src/ tests/ --line-length 100
ruff check src/ tests/
mypy src/
```

## Architecture

### Two Subsystems

**1. MCP Server + Search Stack** (`src/mcp_server/`, `src/search/`, `src/embeddings/`)
- FastMCP server exposes tools to Claude Desktop via stdio transport
- Hybrid search: Vector (all-MiniLM-L6-v2, 384d) + BM25 full-text via LanceDB with RRF fusion
- Cross-encoder reranking (cross-encoder/ms-marco-MiniLM-L-6-v2)
- HyDE query expansion, multi-query fusion, time-decay scoring

**2. Ingestion + HITL Dashboard** (root-level modules in `src/`)
- `watchdog.py` monitors `INBOX_PATH` for new files
- `batch_processor.py` processes all inbox files as a batch via the dashboard's "Start Analysis" button
- Two-phase staging: files appear in dashboard as "processing", then update to "pending" when AI finishes
- `server.py` serves dashboard at `localhost:8000` for reviewing/editing AI proposals
- `executor.py` handles: PII redaction (if `is_sensitive`), archive originals to `ARCHIVE_PATH/{target_folder}`, export redacted markdown to `VAULT_PATH/Ingested/`, index into RAG (LanceDB)
- Config loaded via `src/config.py` (uses `python-dotenv`, reads `.env`)

### Intelligence Provider

`src/intelligence.py` auto-selects provider (all methods are async, using httpx):
- **Ollama** (default): uses `qwen2.5:32b` locally at `localhost:11434`. Set `OLLAMA_MODEL` env var to change.
- **Gemini**: used if `GOOGLE_API_KEY` is set. Faster but sends document text to Google (PII concern).

The LLM analyzes each document and returns: category, year, type, summary, suggested filename, `pii_observations` (advisory text, not a flag), and full redacted text. The `is_sensitive` boolean is set by Presidio + custom dictionary scan in `processor.py`, not by the LLM.

### PII Detection — Three-Layer System

PII is detected at **analysis time** in `processor.py` (not deferred to commit time):

1. **Presidio + spaCy** (`en_core_web_lg`): NER-based detection of names, organizations, locations, dates, plus regex patterns for SSNs, phone numbers, emails, credit cards, API keys, IP addresses. Keyword scanner is **disabled** (caused false positives on policy/HR documents).
2. **Custom PII dictionary** (`~/.corerag/pii_terms.yaml`): User-defined terms (SSN, email, employee ID, etc.) matched with confidence=1.0. Template at `pii_terms.example.yaml`. Protected by file permissions + `.gitignore`.
3. **LLM advisory** (`pii_observations`): Free-text field where the LLM notes specific PII it sees. Not used for the `is_sensitive` boolean — purely informational on the dashboard.

**Manual override**: Dashboard "Mark as Sensitive" checkbox lets the user override auto-detection in either direction. Sets `pii_source: "manual"` in metadata.

Key metadata fields on each staged item:
- `is_sensitive` (bool) — driven by Presidio + custom dictionary (confidence >= 0.70)
- `pii_detections` (list) — summary of each detection (type, confidence, context snippet)
- `pii_observations` (str) — LLM's advisory text
- `pii_source` ("auto" | "manual") — who set the sensitivity flag

Redaction: `_redact_pii()` in `executor.py` runs Presidio + custom dictionary at commit time as a safety net. Archived originals are **never** redacted; Obsidian + RAG exports get redacted text. Files with PII get `CUI_` prefix on suggested filename.

### Ingestion Pipeline Flow

```
watchdog.py / batch_processor.py
  → processor.py
    → extractor.py (text extraction: PDF, DOCX, TXT, MD, etc.)
    → intelligence.py (Ollama/Gemini: classify, summarize, redact PII)
    → staging.py (write to staging_manifest.json)
  → Dashboard review (human-in-the-loop)
  → executor.py
    → archiver.py (move original to ARCHIVE_PATH/{target_folder})
    → exporter.py (write redacted markdown to VAULT_PATH/Ingested/)
    → RAG indexing (parent-child chunks into LanceDB)
```

All pipeline modules live at `src/` root level (not inside subdirectories).

### Key Subsystems

| Directory | Purpose | Status |
|-----------|---------|--------|
| `src/mcp_server/` | FastMCP server + tool definitions for Claude Desktop | **Wired** |
| `src/search/` | Hybrid search, HyDE, reranker, multi-query, decay scoring, conversational search | **Wired** |
| `src/embeddings/` | all-MiniLM-L6-v2 with caching, MPS-optimized | **Wired** |
| `src/ingestion/` | ~~File processing pipeline orchestrator~~ | **Deleted** (orphaned scaffold) |
| `src/storage/` | ~~LanceDB vector store wrapper~~ | **Deleted** (orphaned scaffold) |
| `src/chunking/` | Parent-child hierarchical chunking | **Wired** (via executor) |
| `src/quality/` | Duplicate detection, link checker, freshness, conflict detection, golden set manager | **Wired** (MCP tools + ingestion pipeline) |
| `src/classification/` | Keyword + embedding-based auto-tagging, learned rules from corrections | **Wired** (via processor) |
| `src/analytics/` | Query tracking + semantic cache | **Wired** (initialized in MCP server) |
| `src/obsidian/` | Markdown export to Obsidian vault with backlinks | **Deleted** (orphaned — `exporter.py` handles export directly) |
| `src/graph/` | GraphRAG entity-based knowledge graph (SQLite) | **Wired** (entity extraction in executor, search_by_entity MCP tool) |
| `src/memory/` | Episodic memory for user context / search patterns | **Wired** (get_user_context, add_user_fact MCP tools) |
| `src/maintenance/` | LanceDB optimizer, health reports, maintenance scheduler | **Wired** (MCP tools) |
| `src/ocr/` | macOS Vision.framework text extraction | **Wired** (via extractor fallback) |
| `src/audio/` | mlx-whisper transcription + topic segmentation | **Wired** (via extractor) |
| `src/video/` | OpenCV keyframe + scene detection | **Wired** (via extractor) |
| `src/multimodal/` | VLM image captioning (LLaVA) | **Wired** (via extractor) |
| `src/menubar/` | macOS menu bar app (rumps) — CR icon, dashboard launcher, status polling | **Wired** |
| `src/export/` | BacklinkGenerator — inline wikilinks + Related section from knowledge graph | **Wired** (via exporter) |
| `src/auth/` | AccessControl scaffold — RBAC with ADMIN/EDITOR/VIEWER roles, PII filtering | Scaffold (not wired into routes) |
| `src/integrations/` | Plugin architecture + ReadwisePlugin for external data sync | **Wired** (MCP tools) |
| `src/utils/` | SafeProcessor, hardware monitor, PII detection, checkpoints, queue manager, retry, logging | **Wired** |

### Data Models

Core models in `src/models/` and defined in `architecture/data_schema.md`:
- **Document**: Source file with metadata, privacy tier (public/private/sensitive), processing status
- **Chunk**: Text segment with 384d embedding vector (all-MiniLM-L6-v2), parent-child hierarchy, tags
- **SearchResult**: Scored result with context snippets

### Collection Tags

Tags let you isolate source material for focused search sessions (e.g., tag SPHR study materials with `sphr-study`, then search only within that collection).

- **Storage**: Comma-delimited string in LanceDB (`",tag1,tag2,"`) for `LIKE '%,tag,%'` filtering
- **Ingest-time**: Apply via CLI (`-t sphr-study`), auto-tagger, or dashboard UI
- **Dashboard**: Editable tag pills per card + "Apply Tag to All" bulk action
- **Search filtering**: Pass `tags` param to MCP `search_knowledge()`, REST `/api/v1/search`, or hybrid search
- **Post-ingestion**: Edit tags on committed documents via `POST /api/documents/{doc_id}/tags`
- **Registry**: `TagManager` (`src/utils/tagging.py`) tracks all tags in `~/.corerag/tags/`

### Staging Manifest

`staging_manifest.json` tracks each document through the pipeline:
- Status flow: `processing` -> `pending` -> `approved` -> `completed` (or `error`)
- Each item stores: original path, AI metadata (category, year, type, summary, is_sensitive), redacted text, proposed filename/target_folder/tags

## Configuration

### Environment Variables (`.env`)
```bash
INBOX_PATH=~/Desktop/Inbox                # Watched folder for new documents
VAULT_PATH=~/Documents/ObsidianVault      # Obsidian vault for markdown exports
ARCHIVE_PATH=~/Documents                  # Long-term storage for originals (in Knowledge/ subfolder)
GOOGLE_API_KEY=...                        # Optional: Gemini API (omit to use local Ollama)
OLLAMA_HOST=http://localhost:11434        # Ollama endpoint (default)
OLLAMA_MODEL=qwen2.5:32b                 # Ollama model for analysis (default)
CORERAG_DB_PATH=~/.corerag/lancedb               # LanceDB vector database path
CORERAG_EMBEDDING_MODEL=all-MiniLM-L6-v2     # Embedding model (default)
CORERAG_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2  # Reranker model (default)
CORERAG_API_KEY=...                       # Optional: API key for /api/v1/* endpoints (omit for open access)
```

### Claude Desktop MCP Setup

Already configured in `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "corerag": {
      "command": "/path/to/CoreRag/venv/bin/python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/CoreRag"
    }
  }
}
```

The MCP server uses **stdio transport** (not HTTP). It initializes: LanceDB connection, HybridSearcher with FTS index, EmbeddingService, CrossEncoderReranker, and CoreRagTools.

## Conventions

- Python 3.12+ (per pyproject.toml), type hints on all function signatures
- PEP 8 + `black` at 100 char line length, `ruff` for linting
- Imports: stdlib -> third-party -> local (`from src.models import ...`)
- Dataclasses or Pydantic for data structures
- All file processors inherit from `BaseProcessor` (see `CONVENTIONS.md`)
- Heavy processing wrapped in `SafeProcessor` for memory throttling
- Custom exception hierarchy: `CoreRagError` -> `ProcessingError`, `EmbeddingError`, `DatabaseError`
- Commit format: `<type>: <description>` (feat/fix/docs/refactor/test/chore/perf)
- `.coreragignore` controls which files are excluded from indexing (gitignore syntax)
- CUI prefix: files with detected PII get `CUI_` prepended to suggested filenames

## Memory Safety

- **Batch processor + commit runner** (`batch_processor.py`, `server.py`): pause at **92%** RAM, resume at **88%**. Checks between each file.
- **SafeProcessor** (`src/utils/safe_processor.py`): pause at **75%** RAM, resume at **65%**. Used for background indexing.
- `gc.collect()` called between files to free extraction buffers.
- Embedding batch size of 32 tuned for M4 Max.

## File Type Support

**Currently working**: PDF (with OCR fallback for scanned docs), DOCX, TXT, Markdown, JSON, YAML, CSV, log files, PNG/JPG/WebP/HEIC (Vision.framework OCR + VLM captioning), MP3/WAV/M4A (mlx-whisper transcription), MP4/MOV (keyframe + scene detection + audio extraction).
**Not yet supported**: XLSX/XLS (spreadsheet processor deleted — needs reimplementation), Python/JS/TS/Go/Rust (code chunker deleted — needs reimplementation).

## Wiring Plan

A 12-phase plan exists to wire all ~46 unwired modules into the main pipeline. Full details in [`_project/DevPlan.md`](./_project/DevPlan.md#wiring-plan-status).

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Fix MCP Server (stdio transport, FastMCP) | **Complete** |
| — | PII Redesign (three-layer detection, custom dictionary, manual override) | **Complete** |
| 2 | Wire Search Stack (HyDE, multi-query, decay scoring) | **Complete** |
| 3 | Wire OCR into ingestion | **Complete** (extractor.py handles images, scanned PDFs, audio, video) |
| 4 | Wire auto-tagging | **Complete** (processor.py calls AutoTagger) |
| 5 | Wire knowledge graph | **Complete** (entity extraction in executor, search_by_entity MCP tool) |
| 6 | Wire episodic memory | **Complete** (get_user_context, add_user_fact MCP tools) |
| 7 | Wire quality modules | **Complete** (freshness, link checker, conflict detector, duplicate detector) |
| 8 | Wire utility modules | **Complete** (logging, retry, exceptions, SafeProcessor, QueueManager all wired) |
| 9 | Wire analytics & queue | **Complete** (QueryAnalytics, SemanticCache, SessionTracker initialized) |
| 10 | Wire multimodal | **Complete** (OCR, VLM, Whisper, video all wired in extractor.py) |
| 11 | Config cleanup & dead code removal | **Complete** (all constants centralized, dead code removed) |
| 12 | CLI integration | **Complete** (13 commands: search, ingest, status, check-links, duplicates, stale, tag, pii, health, optimize-db, backup, graph, memory) |

### Remaining Wiring Work

All 12 phases are **complete**. No remaining wiring work.
- `HybridSearcher.search(query, query_vector, k, filters)` is async
- `intelligence.py` methods (`analyze_document`, `suggest_folder_structure`) are async (httpx)

## Troubleshooting

**Ollama not running**: Most analysis/classification requires Ollama. Start it with `ollama serve` or verify it's accessible at `OLLAMA_HOST` (default `http://localhost:11434`). If the model isn't pulled yet: `ollama pull qwen2.5:32b`.

**MCP connection failure / JSON parse error**: The MCP server uses stdio transport — any non-JSON output on stdout corrupts the stream. All logging goes to stderr. If you see "Unexpected number in JSON" in Claude Desktop, check that no module writes to `sys.stdout`. The fix (applied in Session 16): `logging_config.py` console handler uses `sys.stderr`, and `config.py` print statements use `file=sys.stderr`.

**LanceDB FTS index corruption**: If full-text search returns errors, delete the FTS index and let it rebuild: `rm -rf ~/.corerag/lancedb/*.lance/_indices/`. The `HybridSearcher.__init__` creates FTS indexes on first use.

**High memory usage**: The batch processor pauses at 92% RAM and resumes at 88%. SafeProcessor pauses background work at 75%. If the system is consistently hitting these thresholds, reduce `EMBEDDING_BATCH_SIZE` in `src/config.py` (default 32) or process fewer files per batch.

**Embedding model mismatch**: If you change `CORERAG_EMBEDDING_MODEL`, you must re-index all documents — existing vectors will have incompatible dimensions. The default model (`all-MiniLM-L6-v2`) produces 384-dimensional vectors. Check `EMBEDDING_DIMENSIONS` in `src/config.py` matches your model.
