# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AntiGravity PKM is a local-first, privacy-preserving Personal Knowledge Management system. It provides semantic search across documents via Claude Desktop's MCP protocol, optimized for Apple Silicon (M4 Max, 48GB RAM). The system ingests documents from an inbox folder, processes them through an AI pipeline (text extraction, PII detection, classification), stages them for human review via a web dashboard, then archives originals and exports redacted markdown to an Obsidian vault.

## Development Commands

### Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # Runtime deps
pip install -r requirements-dev.txt      # Dev deps (pytest, black, ruff, mypy)
```

### Running the System
```bash
./scripts/run_system.sh                  # Starts server + watchdog + opens dashboard
python -m src.server                     # Server only (port 8000)
python -m src.watchdog                   # File watcher only
```

### CLI
```bash
python -m src.cli.main status
python -m src.cli.main search "query"
python -m src.cli.main ingest /path/to/folder -r
python -m src.cli.main check-links /path
python -m src.cli.main duplicates /path
python -m src.cli.main stale /path --days 365
python -m src.cli.main tag /path
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

### Linting & Formatting
```bash
black src/ tests/ --line-length 100
ruff check src/ tests/
mypy src/
```

## Architecture

### Two Subsystems

**1. MCP Server + Search Stack** (`src/mcp_server/`, `src/search/`, `src/embeddings/`)
- FastMCP server exposes tools to Claude Desktop
- Hybrid search: Vector (nomic-embed-text-v1.5, 768d) + BM25 full-text via LanceDB
- HyDE query expansion, cross-encoder reranking, multi-query fusion with RRF
- Time-decay scoring for freshness weighting

**2. Ingestion + HITL Dashboard** (root-level modules in `src/`)
- `watchdog.py` monitors `INBOX_PATH` for new files
- Two-phase staging: files appear immediately in dashboard as "processing", then update to "pending" when AI finishes
- `server.py` serves dashboard at `localhost:8000` for reviewing/editing AI proposals
- `executor.py` handles rename, archive to `ARCHIVE_PATH/{category}/{year}`, export redacted markdown to `VAULT_PATH/Ingested/`
- Config loaded via `src/config.py` (uses `python-dotenv`, reads `.env`)

### Ingestion Pipeline Flow

`watchdog.py` -> `processor.py` -> `extractor.py` -> `intelligence.py` -> `staging.py` -> (dashboard review) -> `executor.py` -> `archiver.py` + `exporter.py`

All pipeline modules live at `src/` root level (not inside subdirectories).

### Key Subsystems

| Directory | Purpose |
|-----------|---------|
| `src/mcp_server/` | FastMCP server + tool definitions for Claude Desktop |
| `src/search/` | Hybrid search, HyDE, reranker, multi-query, decay scoring |
| `src/embeddings/` | nomic-embed-text with caching, MPS-optimized |
| `src/ingestion/` | File processing pipeline orchestrator |
| `src/storage/` | LanceDB vector store wrapper |
| `src/chunking/` | Parent-child hierarchical chunking + AST-based code chunking |
| `src/quality/` | Duplicate detection (hash+MinHash+semantic), link checker, freshness, conflict detection |
| `src/classification/` | Keyword + embedding-based auto-tagging |
| `src/analytics/` | Query tracking + semantic cache |
| `src/obsidian/` | Markdown export to Obsidian vault with backlinks |
| `src/graph/` | GraphRAG entity-based knowledge graph |
| `src/memory/` | Episodic memory for search history patterns |
| `src/ocr/` | macOS Vision.framework text extraction |
| `src/audio/` | mlx-whisper transcription + topic segmentation |
| `src/video/` | OpenCV keyframe + scene detection |
| `src/multimodal/` | VLM image captioning (LLaVA) |
| `src/utils/` | SafeProcessor, hardware monitor, PII detection, checkpoints, queue manager, retry, logging |

### Data Models

Core models in `src/models/` and defined in `architecture/data_schema.md`:
- **Document**: Source file with metadata, privacy tier (public/private/sensitive), processing status
- **Chunk**: Text segment with 768d embedding vector, parent-child hierarchy support
- **SearchResult**: Scored result with context snippets

### Staging Manifest

`staging_manifest.json` tracks each document through the pipeline:
- Status flow: `processing` -> `pending` -> `approved` -> `completed` (or `error`)
- Each item stores: original path, AI metadata, redacted text, proposed filename/category/year

## Configuration

### Environment Variables (`.env`)
```bash
INBOX_PATH=~/Desktop/Inbox           # Watched folder (auto-created if missing)
VAULT_PATH=~/Documents/ObsidianVault # Obsidian vault for markdown exports
ARCHIVE_PATH=~/Documents             # Long-term storage for originals
GOOGLE_API_KEY=...                   # For Gemini intelligence (falls back to simulation)
PKM_DB_PATH=~/.pkm/lancedb          # LanceDB vector database
PKM_LOG_LEVEL=INFO
PKM_MEMORY_THRESHOLD=75             # Pause ingestion at this % RAM
PKM_BATCH_SIZE=32                   # Embedding batch size
```

### Claude Desktop MCP Setup
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "pkm": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/AntiGravity_PKM"
    }
  }
}
```

### macOS Automation
```bash
./scripts/install_automation.sh      # Install launchd agent (triggers on Inbox changes)
```

## Conventions

- Python 3.11+, type hints on all function signatures
- PEP 8 + `black` at 100 char line length, `ruff` for linting
- Imports: stdlib -> third-party -> local (`from src.models import ...`)
- Dataclasses or Pydantic for data structures
- All file processors inherit from `BaseProcessor` (see `CONVENTIONS.md`)
- Heavy processing wrapped in `SafeProcessor` for memory throttling (pause >75% RAM, resume <65%)
- Custom exception hierarchy: `PKMError` -> `ProcessingError`, `EmbeddingError`, `DatabaseError`
- Commit format: `<type>: <description>` (feat/fix/docs/refactor/test/chore/perf)
- `.pkmignore` controls which files are excluded from indexing (gitignore syntax)
- CUI prefix: files with detected PII get `CUI_` prepended to suggested filenames

## File Type Support

Text extraction handles: PDF, DOCX, TXT, Markdown, JSON, YAML, CSV, log files.
Full processing pipeline also supports: XLSX/XLS (formula-aware), Python/JS/TS/Go/Rust (AST chunking), MP3/WAV/M4A (mlx-whisper), MP4/MOV (keyframe + scene detection), PNG/JPG/WebP (Vision.framework OCR).

## Hardware Safety

Memory management auto-pauses at >75% RAM and resumes at <65%. CPU/GPU temperature throttling is built in. Embedding batch size of 32 is tuned for M4 Max.
