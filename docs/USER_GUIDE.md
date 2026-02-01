# PKM System User Guide

A comprehensive Personal Knowledge Management system with AI-powered semantic search.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [CLI Commands](#cli-commands)
3. [Ingesting Content](#ingesting-content)
4. [Inbox & Obsidian Workflow](#inbox--obsidian-workflow)
5. [Searching Your Knowledge](#searching-your-knowledge)
6. [Using with Claude Desktop](#using-with-claude-desktop)
7. [Quality Tools](#quality-tools)
7. [Health Monitoring](#health-monitoring)
8. [Privacy and Security](#privacy-and-security)
9. [Backup and Recovery](#backup-and-recovery)
10. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Prerequisites

- **Hardware**: Apple Silicon Mac (M1/M2/M3/M4) with 16GB+ RAM
- **macOS**: 13.0 or later
- **Python**: 3.11 or later
- **Storage**: 50GB+ free space recommended

### Installation

1. Clone the repository:
   ```bash
   cd ~/Projects
   git clone <repository-url> AntiGravity_PKM
   cd AntiGravity_PKM
   ```

2. Create and activate virtual environment:
   ```bash
   python3 -m venv ~/.pkm/venv
   source ~/.pkm/venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create required directories:
   ```bash
   mkdir -p ~/.pkm/{lancedb,logs,cache,checkpoints,backups}
   mkdir -p ~/PKM/{inbox,processed,vault}
   ```

5. (Optional) Install PII detection:
   ```bash
   pip install presidio-analyzer presidio-anonymizer
   python -m spacy download en_core_web_lg
   ```

### Quick Start

```bash
# Check system status
python -m src.cli.main status

# Ingest some files
python -m src.cli.main ingest ~/Documents/Research -r

# Search your knowledge
python -m src.cli.main search "machine learning concepts"
```

---

## CLI Commands

The PKM system includes a comprehensive command-line interface.

### Search

Search your knowledge base:

```bash
# Basic search
python -m src.cli.main search "your query"

# Limit results
python -m src.cli.main search "your query" -n 5

# Include file type filter
python -m src.cli.main search "neural networks" --type pdf
```

### Ingest

Add files to your knowledge base:

```bash
# Single file
python -m src.cli.main ingest /path/to/document.pdf

# Directory (non-recursive)
python -m src.cli.main ingest /path/to/folder

# Directory (recursive)
python -m src.cli.main ingest /path/to/folder -r
```

### Status

Check system health:

```bash
python -m src.cli.main status
```

Output includes:
- Document count
- Storage usage
- Memory status
- Last indexing time

### Check Links

Find broken URLs in your documents:

```bash
# Check directory
python -m src.cli.main check-links /path/to/folder

# Recursive check
python -m src.cli.main check-links /path/to/folder -r
```

### Find Duplicates

Detect duplicate content:

```bash
# Find duplicates
python -m src.cli.main duplicates /path/to/folder

# Set similarity threshold (0.0-1.0)
python -m src.cli.main duplicates /path/to/folder --threshold 0.9
```

### Find Stale Content

Identify outdated documents:

```bash
# Default (365 days)
python -m src.cli.main stale /path/to/folder

# Custom threshold
python -m src.cli.main stale /path/to/folder --days 180
```

### Auto-Tag

Automatically tag documents:

```bash
python -m src.cli.main tag /path/to/folder -r
```

---

## Ingesting Content

### Supported File Types

| Type | Extensions | Processing |
|------|-----------|------------|
| Documents | `.md`, `.txt`, `.docx`, `.pdf` | Text extraction, parent-child chunking |
| Audio | `.mp3`, `.wav`, `.m4a` | mlx-whisper transcription, topic segmentation |
| Video | `.mp4`, `.mov` | Scene detection, VLM captioning |
| Images | `.png`, `.jpg`, `.webp` | Vision.framework OCR |
| Data | `.json`, `.csv`, `.xlsx` | Structured parsing |
| Code | `.py`, `.js`, `.ts`, etc. | AST-aware chunking |

### Excluded by Default

See `.pkmignore` for full list:
- System files (`.DS_Store`, `node_modules/`)
- Build artifacts (`dist/`, `build/`)
- Version control (`.git/`)
- Large binaries (`.exe`, `.dll`)
- Obsidian canvas files (`*.canvas`)

### Ingestion Pipeline

```python
from src.ingestion.pipeline import IngestionPipeline

pipeline = IngestionPipeline()

# Ingest single file
result = pipeline.ingest_file("/path/to/document.pdf")
print(f"Created {result.chunk_count} chunks")

# Ingest directory
results = pipeline.ingest_directory(
    "/path/to/documents",
    recursive=True
)
print(f"Processed {results.successful} files")
```

### Memory-Safe Processing

The system automatically manages memory:
- Pauses at 75% RAM usage
- Resumes at 65% RAM usage
- Throttles CPU at 90°C

- Throttles CPU at 90°C

---

## Inbox & Obsidian Workflow

The system provides a seamless workflow for processing files and integrating with Obsidian.

### Folder Structure

Run `python scripts/setup_folders.py` to create:

```
~/Documents/PKM/
├── Inbox/          ← Drop new files here
├── Processed/      ← Files moved here after ingestion
└── Obsidian/       ← Your vault
    └── PKM Imports/  ← New .md files created from ingested content
```

### The "Drop & Forget" Workflow

1. **Drop a file** (PDF, Docx, etc.) into `Inbox/`.
2. **Run Ingestion**:
   ```bash
   python -m src.cli.main ingest ~/Documents/PKM/Inbox -r
   ```
3. **Automatic Actions**:
   - File is chunked, embedded, and stored in LanceDB.
   - A markdown copy is created in `Obsidian/PKM Imports/` with metadata.
   - Original file is moved to `Processed/` with a date prefix (e.g., `2026-02-01_note.pdf`).

### Obsidian Integration Details

The exported markdown files contain YAML frontmatter:

```yaml
---
source_file: meeting_notes.pdf
source_path: /Users/tjneary/Documents/PKM/Processed/2026-02-01_meeting_notes.pdf
ingested_at: 2026-02-01T14:30:00
type: pkm_import
tags:
  - pkm/import
  - type/pdf
---

# Imported: meeting_notes.pdf

[Extracted text content...]
```

This makes your ingested content searchable and linkable within Obsidian immediately.

---

## Searching Your Knowledge

### Basic Search

```python
from src.search.hybrid_search import HybridSearcher

searcher = HybridSearcher()

# Simple semantic search
results = searcher.search("How do neural networks learn?")

for result in results:
    print(f"📄 {result.title}")
    print(f"   Score: {result.score:.2f}")
    print(f"   {result.snippet[:200]}...")
```

### Advanced Search Features

#### Hybrid Search (Vector + BM25)
Combines semantic similarity with keyword matching.

#### HyDE (Hypothetical Document Embeddings)
Expands queries by generating hypothetical answers.

#### Cross-Encoder Reranking
Uses `mxbai-rerank-base-v1` for precision reranking.

#### Decay Scoring
Weights recent documents higher for time-sensitive queries.

#### Multi-Query Fusion
Breaks complex queries into sub-queries, combines via RRF.

### Search with Filters

```python
results = searcher.search(
    "machine learning optimization",
    filters={
        "file_type": ["md", "pdf"],
        "modified_after": "2025-01-01"
    },
    limit=10
)
```

---

## Using with Claude Desktop

### Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pkm": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/AntiGravity_PKM",
      "env": {
        "PKM_HOME": "/Users/yourname/.pkm"
      }
    }
  }
}
```

### Restart Claude Desktop

After saving the config, restart Claude Desktop to load the MCP server.

### Available MCP Tools

Once connected, Claude can use:

| Tool | Purpose |
|------|---------|
| `search_knowledge` | Semantic search with filters |
| `list_recent_files` | Browse recently modified files |
| `get_system_status` | Check system health |
| `get_file_structure` | View directory hierarchy |

### Example Claude Usage

```
You: What do my notes say about Python async programming?

Claude: [Uses search_knowledge tool]
Based on your notes, here's what you've documented about Python async...

You: Show me recent files about machine learning

Claude: [Uses list_recent_files tool]
Here are your recent ML-related files...
```

---

## Quality Tools

### Duplicate Detection

Three-tier detection:
1. **Hash matching** - Exact duplicates (fastest)
2. **MinHash/LSH** - Near-duplicates (fast)
3. **Semantic similarity** - Content duplicates (thorough)

```python
from src.quality.duplicate_detector import DuplicateDetector

detector = DuplicateDetector()
report = detector.scan_directory("/path/to/folder")

for group in report.duplicate_groups:
    print(f"Duplicates: {[d.path for d in group.documents]}")
```

### Link Rot Checking

Async URL validation with caching:

```python
from src.quality.link_checker import LinkChecker
import asyncio

checker = LinkChecker()
report = asyncio.run(checker.scan_directory("/path/to/folder"))

for broken in report.broken_links:
    print(f"Broken: {broken.url} in {broken.file}")
```

### Freshness Tracking

Identify stale content:

```python
from src.quality.freshness_tracker import FreshnessTracker

tracker = FreshnessTracker()
stale = tracker.find_stale_documents(days=365)

for doc in stale:
    print(f"Stale: {doc.path} (last modified: {doc.modified_at})")
```

### Conflict Detection

Find contradictory information:

```python
from src.quality.conflict_detector import ConflictDetector

detector = ConflictDetector()
report = detector.scan_directory("/path/to/folder")

for conflict in report.conflicts:
    print(f"Conflict: {conflict.doc1} vs {conflict.doc2}")
    print(f"  {conflict.description}")
```

---

## Health Monitoring

### Dashboard

Start the web dashboard:

```bash
python -m src.dashboard.health_dashboard
```

Access at: http://127.0.0.1:8765

Features:
- Real-time memory usage
- CPU/GPU temperature
- Document count
- Query statistics
- Recent errors

### Programmatic Monitoring

```python
from src.utils.hardware_monitor import HardwareMonitor

monitor = HardwareMonitor()
status = monitor.get_status()

print(f"Memory: {status.memory_percent:.1f}%")
print(f"CPU Temp: {status.cpu_temp}°C")
print(f"Safe to process: {status.is_safe}")
```

---

## Privacy and Security

### Privacy Tiers

| Tier | Description | Handling |
|------|-------------|----------|
| Public | Safe to share | Normal indexing |
| Private | Personal | Local only (default) |
| Sensitive | PII detected | Extra protection |

### PII Detection

Automatic detection of:
- Email addresses
- Phone numbers
- SSN/Tax IDs
- Credit card numbers
- Names and addresses

```python
from src.utils.privacy_audit import PrivacyAuditManager

audit = PrivacyAuditManager()
result = audit.audit_file("/path/to/document.pdf")

if result.pii_detected:
    print(f"PII found: {result.pii_types}")
    print(f"Recommendation: {result.privacy_tier}")
```

### Default Behavior

- All content is "private" by default
- PII is flagged before indexing
- Sensitive content requires manual approval
- No data leaves your device

---

## Backup and Recovery

### Creating Backups

```python
from src.utils.backup_manager import BackupManager

backup = BackupManager()
info = backup.create_backup("manual")

print(f"Backup created: {info.path}")
print(f"Size: {info.size_mb:.1f} MB")
```

### Automatic Backups

Configure in environment:

```bash
export PKM_AUTO_BACKUP=true
export PKM_BACKUP_INTERVAL=24  # hours
```

### Restoring from Backup

```python
# List backups
backups = backup.list_backups()
for b in backups:
    print(f"{b.name} - {b.timestamp}")

# Restore
backup.restore_backup("manual_20260131_120000")
```

### Checkpoint System

Resume interrupted ingestion jobs:

```python
from src.utils.checkpoint_manager import CheckpointManager

checkpoint = CheckpointManager()

# Find interrupted jobs
jobs = checkpoint.list_jobs()
for job in jobs:
    if job.status == "in_progress":
        remaining = checkpoint.get_remaining_files(job.job_id)
        print(f"Job {job.job_id}: {len(remaining)} files remaining")
```

---

## Troubleshooting

### Common Issues

#### "Out of Memory" Errors

The system should automatically pause, but if issues persist:

```bash
# Reduce batch size
export PKM_EMBEDDING_BATCH=16

# Reduce workers
export PKM_MAX_WORKERS=4
```

#### Slow Embedding Performance

Check MLX is being used:

```python
import mlx.core as mx
print(f"MLX Metal available: {mx.metal.is_available()}")
```

#### Search Returns Poor Results

1. Check document count:
   ```bash
   python -m src.cli.main status
   ```

2. Verify content is indexed:
   ```bash
   python -m src.cli.main search "exact phrase from document"
   ```

3. Rebuild index if corrupted:
   ```python
   from src.maintenance.db_optimizer import DBOptimizer
   optimizer = DBOptimizer()
   optimizer.rebuild_indices()
   ```

#### MCP Server Not Connecting

1. Check server starts manually:
   ```bash
   python -m src.mcp_server.server
   ```

2. Verify config path is correct
3. Restart Claude Desktop
4. Check logs: `~/.pkm/logs/pkm.log`

### Debug Mode

```bash
# Enable debug logging
PKM_LOG_LEVEL=DEBUG python -m src.cli.main search "query"
```

### Getting Help

1. Check `architecture/` for system design
2. Review `CONVENTIONS.md` for code patterns
3. Run tests: `pytest tests/ -v`
4. Check status: `python -m src.cli.main status`

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PKM_HOME` | `~/.pkm` | Data directory |
| `PKM_EMBEDDING_MODEL` | `nomic-embed-text-v1.5` | Embedding model |
| `PKM_EMBEDDING_BATCH` | `32` | Batch size |
| `PKM_LOG_LEVEL` | `INFO` | Logging verbosity |
| `PKM_MAX_WORKERS` | `8` | Parallel workers |
| `PKM_MEMORY_PAUSE` | `0.75` | Memory pause threshold |
| `PKM_MEMORY_RESUME` | `0.65` | Memory resume threshold |

### Performance Tuning

For M4 Max (48GB):
```bash
export PKM_EMBEDDING_BATCH=64
export PKM_MAX_WORKERS=12
export PKM_CHUNK_SIZE=1000
```

For M1/M2 (16GB):
```bash
export PKM_EMBEDDING_BATCH=16
export PKM_MAX_WORKERS=4
export PKM_CHUNK_SIZE=500
```

---

*PKM System User Guide | Version 2.0 | Last Updated: 2026-01-31*
