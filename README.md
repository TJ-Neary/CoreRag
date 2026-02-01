# AntiGravity PKM - Personal Knowledge Management Reasoning Engine

A local-first, privacy-preserving knowledge management system that enables semantic search across all your documents via Claude Desktop's MCP protocol. Optimized for Apple Silicon (M4 Max, 48GB RAM).

## ✅ Status: Core Complete

All core features implemented. Ready for user setup and testing.

## Quick Start

```bash
# 1. Create Python environment
python3 -m venv ~/.pkm/venv
source ~/.pkm/venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup PKM folders
python scripts/setup_folders.py

# 4. Ingest documents (Inbox workflow)
export PKM_INBOX_DIR=~/Documents/PKM/Inbox
python -m src.cli.main ingest ~/Documents/PKM/Inbox -r

# 5. Search
python -m src.cli.main search "your query"
```

## Key Features

### 🔍 Advanced Search
- **Hybrid Search**: Vector (semantic) + Full-text (BM25) + Cross-encoder reranking
- **HyDE Expansion**: Hypothetical document embeddings for better query understanding
- **Obsidian Integration**: Auto-exports ingested content to your vault with backlinks

### 📥 Inbox Workflow
- **Drop & Forget**: Place files in `~/Documents/PKM/Inbox`
- **Auto-Processing**: System chunks, embeds, and indexes content
- **Smart Filing**: Original moves to `Processed/`, markdown copy goes to `Obsidian/PKM Imports`

### 📄 Multi-Format Processing
- **Documents**: PDF, DOCX, TXT, Markdown
- **Spreadsheets**: XLSX, XLS, CSV (formula-aware, sheet structure preserved)
- **Code**: Python, JavaScript, TypeScript, Go, Rust (AST-aware chunking)
- **Audio**: MP3, WAV, M4A (mlx-whisper transcription + topic segmentation)
- **Video**: MP4, MOV (keyframe extraction + scene detection + audio)
- **Images**: PNG, JPG, WebP (Vision.framework OCR + VLM captioning)

### 🛡️ Privacy & Safety
- **Local-First**: All processing on your machine
- **Presidio PII Detection**: Hybrid NER + regex for sensitive data
- **Memory Management**: Auto-pause at >75% RAM usage
- **Hardware Monitoring**: CPU/GPU temperature throttling

### 📊 Quality Assurance
- **Auto-Tagging**: Keyword + embedding-based classification
- **Duplicate Detection**: Content hash + MinHash/LSH + semantic similarity
- **Link Rot Checker**: Async URL validation with caching
- **Freshness Indicators**: Age classification + staleness warnings
- **Conflict Detection**: Find contradictions across documents

### 🔧 Advanced Features
- **GraphRAG**: Entity-based knowledge graph for relationship queries
- **Episodic Memory**: Track search history and patterns
- **Parent-Child Chunking**: Context-preserving chunk hierarchy
- **Zombie Reconciliation**: Detect orphaned entries from deleted files

## Project Structure

```
AntiGravity_PKM/
├── README.md                 # This file
├── AGENT_INSTRUCTIONS.md     # AI agent instructions
├── SETUP_TASKS.md            # User setup checklist
├── PRD.md                    # Product requirements
├── CONVENTIONS.md            # Coding standards
├── requirements.txt          # Python dependencies
├── .pkmignore                # Files to exclude from indexing
│
├── architecture/             # Design documents
│   ├── data_schema.md        # Data structures
│   ├── HARDWARE_SAFETY.md    # Safety monitoring
│   ├── PERFORMANCE_GUIDE.md  # M4 Max optimization
│   ├── MIGRATION_STRATEGY.md # Embedding migration
│   └── ...
│
├── src/                      # Source code
│   ├── mcp_server/           # FastMCP server
│   │   ├── server.py         # Main entry point
│   │   └── tools.py          # MCP tool definitions
│   │
│   ├── embeddings/           # Embedding generation
│   │   └── embedding_service.py
│   │
│   ├── ingestion/            # File processing
│   │   └── pipeline.py       # Main orchestrator
│   │
│   ├── search/               # Search stack
│   │   ├── hybrid_search.py  # Vector + FTS
│   │   ├── hyde.py           # HyDE expansion
│   │   ├── reranker.py       # Cross-encoder
│   │   ├── multi_query.py    # Query fusion
│   │   └── decay_scoring.py  # Time weighting
│   │
│   ├── chunking/             # Text chunking
│   │   ├── parent_child.py   # Hierarchical chunks
│   │   └── code_chunker.py   # AST-based
│   │
│   ├── quality/              # Quality assurance
│   │   ├── duplicate_detector.py
│   │   ├── link_checker.py
│   │   ├── freshness.py
│   │   └── conflict_detector.py
│   │
│   ├── classification/       # Auto-tagging
│   │   └── auto_tagger.py
│   │
│   ├── analytics/            # Query analytics
│   │   └── query_analytics.py
│   │
│   ├── ocr/                  # Image text extraction
│   │   └── vision_ocr.py     # Vision.framework
│   │
│   ├── multimodal/           # VLM processing
│   │   └── vlm_captioner.py
│   │
│   ├── audio/                # Audio processing
│   │   └── topic_segmentation.py
│   │
│   ├── video/                # Video processing
│   │   └── scene_detector.py
│   │
│   ├── graph/                # Knowledge graph
│   │   └── knowledge_graph.py
│   │
│   ├── memory/               # Episodic memory
│   │   └── episodic_memory.py
│   │
│   ├── cli/                  # Command-line interface
│   │   └── main.py
│   │
│   ├── dashboard/            # Web UI
│   │   └── health_dashboard.py
│   │
│   └── utils/                # Shared utilities
│       ├── safe_processor.py   # Memory management
│       ├── hardware_monitor.py
│       ├── privacy_audit.py    # PII detection
│       ├── pkmignore.py        # File exclusion
│       ├── checkpoint.py       # State recovery
│       └── ...
│
├── tests/                    # Test files
│   ├── golden_set/           # Search quality tests
│   └── ...
│
└── docs/                     # User documentation
    └── USER_GUIDE.md
```

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Vector Database | LanceDB | Embedded, TB-scale, Lance format |
| Embeddings | nomic-embed-text-v1.5 | 768d, MPS-optimized |
| Audio | mlx-whisper | Apple Silicon transcription |
| Video | OpenCV | Keyframe + scene detection |
| OCR | Vision.framework | Native macOS text extraction |
| VLM | LLaVA (optional) | Image descriptions |
| PII | Presidio + Regex | Hybrid detection |
| MCP | FastMCP | Claude Desktop integration |
| File Processing | Unstructured | Multi-format support |
| Code Parsing | tree-sitter | AST-aware chunking |

## CLI Commands

```bash
# System status
python -m src.cli.main status

# Search knowledge base
python -m src.cli.main search "your query"

# Ingest files
python -m src.cli.main ingest /path/to/folder -r

# Check for broken links
python -m src.cli.main check-links /path/to/folder

# Find duplicates
python -m src.cli.main duplicates /path/to/folder

# Find stale content
python -m src.cli.main stale /path/to/folder --days 365

# Auto-tag files
python -m src.cli.main tag /path/to/folder
```

## Configuration

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

### Environment Variables

Create `.env` in project root:

```bash
PKM_DB_PATH=~/.pkm/lancedb
PKM_LOG_LEVEL=INFO
PKM_MEMORY_THRESHOLD=75
PKM_BATCH_SIZE=32
```

## User Setup Required

Before full operation, complete the tasks in `SETUP_TASKS.md`:

1. **Presidio Installation** - PII detection
2. **Vision.framework Verification** - OCR capability
3. **Tailscale Setup** (optional) - Remote access
4. **Web Clipper** (optional) - Article capture
5. **Golden Set Creation** - Search quality testing

## Performance Notes

- **Memory**: Pauses ingestion at >75% RAM, resumes at <65%
- **Batch Size**: 32 for embeddings (optimal for M4 Max)
- **Workers**: Up to 8 parallel file processors
- **Query Time**: Target <3 seconds including reranking

## Documentation

| Document | Purpose |
|----------|---------|
| `AGENT_INSTRUCTIONS.md` | AI agent guide (read first) |
| `SETUP_TASKS.md` | User setup checklist |
| `PRD.md` | Full requirements |
| `architecture/data_schema.md` | Data structures |
| `architecture/HARDWARE_SAFETY.md` | Safety monitoring |
| `architecture/PERFORMANCE_GUIDE.md` | M4 Max optimization |
| `docs/USER_GUIDE.md` | End-user documentation |

---

*AntiGravity PKM v2.0 | Created: 2026-01-31*
# PKM_V1
