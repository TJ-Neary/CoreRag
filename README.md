# CoreRag

![CoreRag Banner](assets/core_rag_banner.png)

A local-first, privacy-preserving knowledge engine with semantic search, exposed via MCP (Claude Desktop) and REST API. Optimized for Apple Silicon.

## Features

### Search
- **Hybrid Search**: Vector (BAAI/bge-m3, 1024d) + BM25 full-text with RRF fusion
- **Cross-Encoder Reranking**: ms-marco-MiniLM-L-6-v2
- **HyDE Expansion**: Hypothetical document embeddings for better recall
- **Multi-Query Fusion**: Parallel query variants merged via RRF
- **Time-Decay Scoring**: Recent documents weighted higher
- **Collection Tags**: Filter searches by tagged document groups

### Ingestion Pipeline
- **Inbox Workflow**: Drop files, auto-process via watchdog or dashboard batch
- **Human-in-the-Loop**: Web dashboard for reviewing AI proposals before commit
- **Three-Layer PII Detection**: Presidio NER + custom dictionary + LLM advisory
- **Smart Filing**: Archive originals, export redacted markdown to Obsidian vault
- **Parent-Child Chunking**: Context-preserving hierarchical chunks with quality scoring
- **Corrective RAG**: Post-retrieval relevance filtering (correct/ambiguous/incorrect)

### Multi-Format Support
- **Documents**: PDF (with OCR fallback), DOCX, TXT, Markdown, JSON, YAML, CSV
- **Images**: PNG, JPG, WebP, HEIC (Vision.framework OCR + VLM captioning)
- **Audio**: MP3, WAV, M4A (mlx-whisper transcription + topic segmentation)
- **Video**: MP4, MOV (keyframe extraction + scene detection + audio)

### Quality Assurance
- **Auto-Tagging**: Keyword + embedding-based classification
- **Duplicate Detection**: Content hash + MinHash/LSH + semantic similarity
- **Link Checker**: Async URL validation with caching
- **Freshness Indicators**: Age classification + staleness warnings
- **Conflict Detection**: Find contradictions across documents

### Advanced
- **GraphRAG**: Bitemporal knowledge graph with confidence decay
- **Episodic Memory**: User context and search pattern tracking
- **Rate-Limited REST API**: Authenticated v1 endpoints with slowapi
- **MCP Server**: Full tool suite for Claude Desktop integration
- **Memory Safety**: Auto-pause at high RAM usage, GC between files

## Quick Start

```bash
# Clone and setup
git clone https://github.com/yourusername/CoreRag.git
cd CoreRag
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg

# Copy and configure environment
cp .env.example .env
# Edit .env with your paths

# Install menu bar app (auto-starts server at login)
./scripts/install_menubar.sh

# Or start manually
./scripts/run_system.sh
```

See [StartHere.md](StartHere.md) for detailed setup instructions.

## Usage

### CLI

```bash
python -m src.cli.main status                          # System status
python -m src.cli.main search "your query"             # Search knowledge base
python -m src.cli.main ingest /path/to/folder -r -t mytag  # Ingest with tags
python -m src.cli.main health                          # System health checks
python -m src.cli.main check-links /path               # Find broken links
python -m src.cli.main duplicates /path                # Find duplicates
python -m src.cli.main stale /path --days 365          # Find stale content
python -m src.cli.main tag /path                       # Auto-tag files
python -m src.cli.main pii list                        # Manage PII dictionary
python -m src.cli.main optimize-db                     # Optimize LanceDB
python -m src.cli.main backup create                   # Create backup
python -m src.cli.main graph stats                     # Knowledge graph stats
python -m src.cli.main memory list                     # Episodic memory
```

### REST API (v1)

```bash
# Capability manifest (no auth required)
curl http://localhost:8000/api/v1/manifest

# Search (with optional tag filtering)
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CORERAG_API_KEY" \
  -d '{"query": "authentication setup", "k": 5, "tags": ["sphr-study"]}'

# Ingest content
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CORERAG_API_KEY" \
  -d '{"content": "...", "source": "my-app", "metadata": {}}'

# Stats and deletion
curl -H "X-API-Key: $CORERAG_API_KEY" http://localhost:8000/api/v1/stats
curl -X DELETE -H "X-API-Key: $CORERAG_API_KEY" http://localhost:8000/api/v1/documents/{id}
```

### MCP (Claude Desktop)

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

### Dashboard

```bash
python -m src.server    # http://localhost:8000
```

Web UI for reviewing AI-proposed metadata, editing tags, marking sensitivity, and committing documents through the pipeline.

## Configuration

Create `.env` from the example:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `INBOX_PATH` | `~/Desktop/Inbox` | Watched folder for new documents |
| `VAULT_PATH` | `~/Documents/ObsidianVault` | Obsidian vault for markdown exports |
| `ARCHIVE_PATH` | `~/Documents` | Long-term storage for originals |
| `CORERAG_DB_PATH` | `~/.corerag/lancedb` | LanceDB vector database |
| `CORERAG_API_KEY` | *(unset)* | API key for v1 endpoints (omit for open access) |
| `OLLAMA_MODEL` | `qwen2.5:32b` | Local LLM for document analysis |
| `CORERAG_EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding model (1024d) |

## Technology Stack

| Component | Technology |
|-----------|------------|
| Vector Database | LanceDB (embedded, Lance format) |
| Embeddings | BAAI/bge-m3 (1024d, MPS-optimized) |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| LLM | Ollama (qwen2.5:32b, local) |
| Audio | mlx-whisper (Apple Silicon) |
| Video | OpenCV (keyframe + scene detection) |
| OCR | Vision.framework (native macOS) |
| VLM | LLaVA (optional image captioning) |
| PII | Presidio + spaCy + custom dictionary |
| MCP | FastMCP (stdio transport) |
| Web | FastAPI + Jinja2 |
| Rate Limiting | slowapi |

## Testing

```bash
pytest                           # Full suite with coverage
pytest -m "not slow"             # Skip slow tests
pytest -m "not integration"      # Skip integration tests
pytest -k "test_name"            # Single test
```

## Development

```bash
black src/ tests/ --line-length 100    # Format
ruff check src/ tests/                 # Lint
mypy src/                              # Type check
./scripts/security_scan.sh --staged    # Security scan before commit
```

See [CONVENTIONS.md](CONVENTIONS.md) for coding standards and [CLAUDE.md](CLAUDE.md) for AI agent instructions.

## License

[MIT](LICENSE)
