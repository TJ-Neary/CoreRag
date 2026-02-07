# CoreRag User Guide

CoreRag is a local-first knowledge engine with AI-powered semantic search, PII detection, and MCP integration.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [CLI Commands](#cli-commands)
3. [Ingesting Content](#ingesting-content)
4. [Dashboard Workflow](#dashboard-workflow)
5. [Searching Your Knowledge](#searching-your-knowledge)
6. [Using with Claude Desktop](#using-with-claude-desktop)
7. [REST API](#rest-api)
8. [Quality Tools](#quality-tools)
9. [Privacy and Security](#privacy-and-security)
10. [Backup and Recovery](#backup-and-recovery)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Prerequisites

- **Hardware**: Apple Silicon Mac (M1/M2/M3/M4) with 16GB+ RAM
- **macOS**: 13.0 or later
- **Python**: 3.12 or later
- **Ollama**: Running locally with `qwen2.5:32b` (or set `OLLAMA_MODEL` for alternative)
- **Storage**: 50GB+ free space recommended

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/CoreRag.git
   cd CoreRag
   ```

2. Create and activate virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install PII detection (recommended):
   ```bash
   pip install presidio-analyzer presidio-anonymizer
   python -m spacy download en_core_web_lg
   ```

5. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your paths (INBOX_PATH, VAULT_PATH, ARCHIVE_PATH)
   ```

6. Create data directories:
   ```bash
   mkdir -p ~/.corerag/{lancedb,logs,state,backups,tags}
   ```

### Quick Start

```bash
# Check system status
python -m src.cli.main status

# Ingest some files
python -m src.cli.main ingest ~/Documents/Research -r

# Search your knowledge
python -m src.cli.main search "machine learning concepts"

# Start the dashboard
python -m src.server
# Open http://localhost:8000
```

---

## CLI Commands

### Search

```bash
# Basic search
python -m src.cli.main search "your query"

# Limit results
python -m src.cli.main search "your query" -n 5

# Filter by collection tags
python -m src.cli.main search "neural networks" -t research
```

### Ingest

```bash
# Single file
python -m src.cli.main ingest /path/to/document.pdf

# Directory (recursive, with tags)
python -m src.cli.main ingest /path/to/folder -r -t study-notes -t cert-prep
```

### System Health

```bash
python -m src.cli.main status        # System overview
python -m src.cli.main health        # Detailed health checks
```

### Quality Tools

```bash
python -m src.cli.main check-links /path    # Find broken URLs
python -m src.cli.main duplicates /path     # Detect duplicate content
python -m src.cli.main stale /path --days 365  # Find outdated documents
python -m src.cli.main tag /path            # Auto-tag files
```

### PII Management

```bash
python -m src.cli.main pii list             # View custom PII terms
python -m src.cli.main pii add "John" --type NAME
python -m src.cli.main pii remove "John"
```

### Database & Backups

```bash
python -m src.cli.main optimize-db          # Optimize LanceDB indices
python -m src.cli.main optimize-db --report-only  # Stats only
python -m src.cli.main backup create        # Create backup
python -m src.cli.main backup list          # List backups
python -m src.cli.main backup restore <name>
python -m src.cli.main backup cleanup       # Remove old backups
```

### Knowledge Graph

```bash
python -m src.cli.main graph stats          # Graph statistics
python -m src.cli.main graph query "entity" # Find connections
python -m src.cli.main graph path "A" "B"   # Find path between entities
```

### Episodic Memory

```bash
python -m src.cli.main memory list          # List stored facts
python -m src.cli.main memory add "Prefers dark mode"
python -m src.cli.main memory context       # View current context
python -m src.cli.main memory export        # Export all facts
```

---

## Ingesting Content

### Supported File Types

| Type | Extensions | Processing |
|------|-----------|------------|
| Documents | `.pdf`, `.docx`, `.txt`, `.md` | Text extraction, parent-child chunking |
| Data | `.json`, `.yaml`, `.csv`, `.log` | Structured parsing |
| Images | `.png`, `.jpg`, `.webp`, `.heic` | Vision.framework OCR + VLM captioning |
| Audio | `.mp3`, `.wav`, `.m4a` | mlx-whisper transcription + topic segmentation |
| Video | `.mp4`, `.mov` | Keyframe extraction + scene detection + audio |

### Ingestion Pipeline

Files go through this flow:

1. **Text Extraction** — `extractor.py` routes to the appropriate handler (PDF parser, OCR, Whisper, etc.)
2. **AI Analysis** — `intelligence.py` classifies, summarizes, and suggests metadata via Ollama
3. **PII Detection** — `processor.py` runs Presidio + custom dictionary scan
4. **Staging** — Results written to `staging_manifest.json` for dashboard review
5. **Human Review** — Dashboard at `localhost:8000` shows proposals for approval
6. **Commit** — `executor.py` archives originals, exports redacted markdown to Obsidian, indexes into LanceDB

### Memory-Safe Processing

The system automatically manages memory:
- Batch processor pauses at 92% RAM, resumes at 88%
- SafeProcessor pauses at 75% RAM, resumes at 65%
- `gc.collect()` runs between files to free buffers

---

## Dashboard Workflow

### Starting the Dashboard

```bash
# Dashboard + watchdog + opens browser
./scripts/run_system.sh

# Or dashboard server only
python -m src.server
```

Access at: **http://localhost:8000**

### Dashboard Features

- **File Review**: See AI-proposed metadata (category, year, type, summary, filename)
- **PII Controls**: View detections, toggle sensitivity, override auto-detection
- **Tag Management**: Edit tags per document, apply tags in bulk
- **Batch Processing**: "Start Analysis" processes all inbox files
- **Commit Runner**: Approve and commit reviewed documents
- **RAG Browser**: Search and browse indexed content
- **Chat**: Query your knowledge base conversationally

### Workflow

1. Drop files in your inbox folder
2. Click "Start Analysis" in the dashboard (or let the watchdog auto-detect)
3. Review AI proposals — edit metadata, adjust sensitivity, add tags
4. Click "Approve" on each document (or "Approve All")
5. Click "Commit" to archive, export, and index

---

## Searching Your Knowledge

### Search Features

| Feature | Description |
|---------|-------------|
| **Hybrid Search** | Vector (semantic) + BM25 (keyword) combined via RRF fusion |
| **Cross-Encoder Reranking** | `cross-encoder/ms-marco-MiniLM-L-6-v2` for precision |
| **HyDE Expansion** | Generates hypothetical answers to improve recall |
| **Multi-Query Fusion** | Decomposes complex queries into sub-queries |
| **Time-Decay Scoring** | Weights recent documents higher |
| **Collection Tags** | Filter results to specific tagged collections |

### Search via CLI

```bash
python -m src.cli.main search "How do neural networks learn?"
```

### Search via REST API

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CORERAG_API_KEY" \
  -d '{"query": "neural networks", "k": 5, "tags": ["research"]}'
```

### Search via MCP (Claude Desktop)

Once connected, ask Claude naturally:
```
You: What do my notes say about Python async programming?
Claude: [Uses search_knowledge tool to find relevant documents]
```

---

## Using with Claude Desktop

### Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Replace `/path/to/CoreRag` with your actual project path.

### Restart Claude Desktop

After saving the config, restart Claude Desktop to load the MCP server.

### Available MCP Tools

| Tool | Purpose |
|------|---------|
| `search_knowledge` | Semantic search with tag filtering |
| `search_by_entity` | Knowledge graph entity search |
| `get_user_context` | Retrieve episodic memory context |
| `add_user_fact` | Store user facts for personalization |
| `check_freshness` | Document age analysis |
| `check_duplicates` | Find duplicate content |
| `check_links` | Validate URLs in documents |
| `detect_conflicts` | Find contradictions |
| `get_system_health` | System status and stats |
| `optimize_database` | LanceDB maintenance |
| `get_maintenance_report` | Database health report |

---

## REST API

### Authentication

Set `CORERAG_API_KEY` in `.env` to enable API key auth. Include `X-API-Key` header in requests. The manifest endpoint is always public.

### Endpoints

```bash
# Capability manifest (no auth required)
curl http://localhost:8000/api/v1/manifest

# Search
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CORERAG_API_KEY" \
  -d '{"query": "search terms", "k": 5}'

# Database stats
curl -H "X-API-Key: $CORERAG_API_KEY" \
  http://localhost:8000/api/v1/stats

# Ingest content
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CORERAG_API_KEY" \
  -d '{"content": "...", "source": "my-app", "metadata": {}}'

# Delete document
curl -X DELETE \
  -H "X-API-Key: $CORERAG_API_KEY" \
  http://localhost:8000/api/v1/documents/{document_id}
```

### Rate Limits

| Endpoint | Limit |
|----------|-------|
| Search | 60/min |
| Ingest | 30/min |
| Stats | 120/min |
| Delete | 30/min |
| Manifest | Unlimited |

---

## Quality Tools

### Duplicate Detection

Three-tier detection:
1. **Hash matching** — Exact duplicates (fastest)
2. **MinHash/LSH** — Near-duplicates (fast)
3. **Semantic similarity** — Content duplicates (thorough)

```bash
python -m src.cli.main duplicates /path/to/folder
```

### Link Checking

Async URL validation with caching:

```bash
python -m src.cli.main check-links /path/to/folder
```

### Freshness Tracking

Identify stale content:

```bash
python -m src.cli.main stale /path/to/folder --days 365
```

### Conflict Detection

Find contradictory information across documents. Available via MCP tools and the dashboard.

---

## Privacy and Security

### Three-Layer PII Detection

1. **Presidio + spaCy** (`en_core_web_lg`): NER-based detection of names, organizations, locations, plus regex for SSNs, phone numbers, emails, credit cards, API keys
2. **Custom PII Dictionary** (`~/.corerag/pii_terms.yaml`): Your own terms matched at confidence=1.0
3. **LLM Advisory**: The AI notes PII it observes — informational only, doesn't set the sensitivity flag

### Sensitivity Flow

- `is_sensitive` is set by layers 1+2 (confidence >= 0.70)
- Dashboard "Mark as Sensitive" checkbox allows manual override
- Sensitive files get `CUI_` prefix on suggested filename
- Archived originals are never redacted
- Obsidian exports and RAG index get redacted text

### Local-First Privacy

- All processing runs on your machine
- No data leaves your device (unless you enable Gemini via `GOOGLE_API_KEY`)
- Database stored at `~/.corerag/lancedb/` (your home directory)
- Server binds to `127.0.0.1` only

### Security Scanner

Run before every commit:

```bash
./scripts/security_scan.sh --staged    # Scan staged changes
./scripts/security_scan.sh             # Scan all tracked files
./scripts/security_scan.sh --fix       # Show remediation suggestions
```

---

## Backup and Recovery

### CLI Backup Commands

```bash
python -m src.cli.main backup create       # Create backup
python -m src.cli.main backup list         # List all backups
python -m src.cli.main backup restore <name>  # Restore from backup
python -m src.cli.main backup cleanup      # Remove old backups
```

### Database Optimization

```bash
python -m src.cli.main optimize-db             # Optimize indices
python -m src.cli.main optimize-db --report-only  # Stats only
```

---

## Troubleshooting

### Ollama Not Running

```
Error: Cannot connect to Ollama at localhost:11434
```

Start Ollama and verify the model is available:
```bash
ollama serve &
ollama list  # Should show qwen2.5:32b
```

### MCP Server Not Connecting

1. Verify the server starts manually:
   ```bash
   python -m src.mcp_server.server
   # Should produce no stdout output (stdio transport)
   ```
2. Check the path in `claude_desktop_config.json` points to your venv Python
3. Restart Claude Desktop after config changes
4. Check logs: `~/.corerag/logs/corerag.log`

### Out of Memory

The system should auto-pause, but if issues persist:
- Reduce embedding batch size: set `CORERAG_EMBEDDING_BATCH=16` in `.env`
- Process fewer files at once in the dashboard

### LanceDB FTS Corruption

If full-text search returns errors:
```bash
python -m src.cli.main optimize-db
```
This rebuilds the FTS index.

### Search Returns Poor Results

1. Check document count: `python -m src.cli.main status`
2. Verify content is indexed: search for an exact phrase you know exists
3. Rebuild indices: `python -m src.cli.main optimize-db`

### High Memory Usage

Monitor with:
```bash
python -m src.cli.main health
```

The system pauses batch processing at 92% RAM and SafeProcessor at 75% RAM.

### Debug Mode

```bash
CORERAG_LOG_LEVEL=DEBUG python -m src.cli.main search "query"
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INBOX_PATH` | `~/Desktop/Inbox` | Watched folder for new documents |
| `VAULT_PATH` | `~/Documents/ObsidianVault` | Obsidian vault for markdown exports |
| `ARCHIVE_PATH` | `~/Documents` | Long-term storage for originals |
| `CORERAG_DB_PATH` | `~/.corerag/lancedb` | LanceDB vector database path |
| `CORERAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model (384d) |
| `CORERAG_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker model |
| `CORERAG_API_KEY` | *(unset)* | API key for v1 endpoints |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:32b` | Ollama model for analysis |
| `CORERAG_LOG_LEVEL` | `INFO` | Logging verbosity |

---

*CoreRag User Guide | v0.1.0 | Last Updated: 2026-02-07*
