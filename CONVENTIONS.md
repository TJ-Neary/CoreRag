# Coding Conventions

> Follow these patterns for all code in this project.

---

## Python Standards

### General
- Python 3.12+ required
- Use type hints for all function signatures
- Use dataclasses or Pydantic for data structures
- Follow PEP 8 style guide

### Imports
```python
# Standard library first
import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# Third-party second
import lancedb
from sentence_transformers import SentenceTransformer

# Local imports last
from src.models import Document, Chunk
from src.utils import compute_hash
```

### Naming
```python
# Classes: PascalCase
class DocumentProcessor:
    pass

# Functions/methods: snake_case
def process_document(file_path: Path) -> Document:
    pass

# Constants: UPPER_SNAKE_CASE
DEFAULT_CHUNK_SIZE = 512
MAX_CONTEXT_LENGTH = 8192

# Private methods: leading underscore
def _validate_input(self, data: dict) -> bool:
    pass
```

### Docstrings
```python
def search_documents(
    query: str,
    limit: int = 10,
    topic: Optional[str] = None
) -> List[SearchResult]:
    """
    Search the knowledge base using semantic similarity.

    Args:
        query: Natural language search query
        limit: Maximum number of results to return
        topic: Optional topic filter

    Returns:
        List of SearchResult objects with relevance scores

    Raises:
        ValueError: If query is empty
        DatabaseError: If LanceDB connection fails
    """
    pass
```

---

## Project Structure

```
CoreRag/
├── src/
│   ├── __init__.py
│   │
│   │   # ── Root-level pipeline modules ──
│   ├── config.py                # Centralized config (env vars, constants, thresholds)
│   ├── exceptions.py            # CoreRagError hierarchy (6 subtypes)
│   ├── server.py                # FastAPI app factory (mounts routers, auth)
│   ├── processor.py             # Document processing (PII detection, AI classification)
│   ├── executor.py              # Commit pipeline (archive, redact, export, RAG index)
│   ├── extractor.py             # Text extraction (PDF, DOCX, images, audio, video)
│   ├── intelligence.py          # LLM provider (Ollama/Gemini) for classification
│   ├── staging.py               # Staging manifest management
│   ├── exporter.py              # Obsidian markdown export with backlinks
│   ├── batch_processor.py       # Inbox batch processing with memory safety
│   ├── watchdog.py              # File watcher for inbox folder
│   ├── folder_manager.py        # Archive folder structure management
│   ├── correction_log.py        # User correction tracking for learning
│   ├── rag_verify.py            # RAG quality verification
│   │
│   │   # ── Subsystem packages ──
│   ├── api/                     # REST API layer
│   │   ├── __init__.py
│   │   ├── models.py            # Pydantic request/response schemas
│   │   ├── v1_routes.py         # API v1 (manifest, stats, search, ingest, delete)
│   │   └── dashboard_routes.py  # Dashboard UI + batch/commit/tag/RAG routes
│   │
│   ├── mcp_server/              # MCP interface for Claude Desktop
│   │   ├── __init__.py
│   │   ├── server.py            # FastMCP server (stdio transport)
│   │   └── tools.py             # Tool implementations (19 tools)
│   │
│   ├── embeddings/              # Embedding generation
│   │   ├── __init__.py
│   │   └── embedding_service.py # all-MiniLM-L6-v2 (384d) with caching
│   │
│   ├── search/                  # Search functionality
│   │   ├── __init__.py
│   │   ├── hybrid_search.py     # Vector + BM25 fusion
│   │   ├── hyde.py              # HyDE query expansion
│   │   ├── reranker.py          # Cross-encoder reranking
│   │   ├── decay_scoring.py     # Time-weighted relevance
│   │   └── multi_query.py       # Query decomposition + RRF
│   │
│   ├── chunking/                # Text chunking strategies
│   │   ├── __init__.py
│   │   └── parent_child.py      # Hierarchical chunking (512/2048 tokens)
│   │
│   ├── quality/                 # Quality assurance
│   │   ├── __init__.py
│   │   ├── duplicate_detector.py
│   │   ├── freshness.py
│   │   ├── link_checker.py
│   │   └── conflict_detector.py
│   │
│   ├── classification/          # Document classification
│   │   ├── __init__.py
│   │   └── auto_tagger.py       # Keyword + embedding tagging
│   │
│   ├── analytics/               # Usage analytics
│   │   ├── __init__.py
│   │   └── query_analytics.py   # Query tracking + semantic cache
│   │
│   ├── ocr/                     # Optical character recognition
│   │   ├── __init__.py
│   │   └── vision_ocr.py        # macOS Vision.framework
│   │
│   ├── multimodal/              # Multi-modal processing
│   │   ├── __init__.py
│   │   └── vlm_captioner.py     # VLM image captioning (LLaVA)
│   │
│   ├── audio/                   # Audio processing
│   │   ├── __init__.py
│   │   └── topic_segmentation.py # mlx-whisper + topic chunking
│   │
│   ├── video/                   # Video processing
│   │   ├── __init__.py
│   │   └── scene_detector.py    # OpenCV scene detection
│   │
│   ├── graph/                   # Knowledge graph
│   │   ├── __init__.py
│   │   └── knowledge_graph.py   # Entity extraction + SQLite graph
│   │
│   ├── memory/                  # Episodic memory
│   │   ├── __init__.py
│   │   └── episodic_memory.py   # User facts + correction patterns
│   │
│   ├── maintenance/             # Database maintenance
│   │   ├── __init__.py
│   │   └── db_optimizer.py      # LanceDB index optimization
│   │
│   ├── cli/                     # Command-line interface
│   │   ├── __init__.py
│   │   └── main.py              # 13 CLI commands
│   │
│   ├── menubar/                 # macOS menu bar app
│   │   ├── __init__.py
│   │   └── app.py               # rumps-based status app
│   │
│   ├── ui/                      # Dashboard templates
│   │   └── templates/
│   │       └── dashboard.html
│   │
│   └── utils/                   # Shared utilities
│       ├── __init__.py
│       ├── safe_processor.py    # Memory-aware processing + ingestion control
│       ├── hardware_monitor.py  # CPU/GPU/temp monitoring
│       ├── throttle_controller.py # Adaptive batch sizing
│       ├── privacy_audit.py     # PII detection (Presidio + custom dictionary)
│       ├── checkpoint.py        # Job persistence
│       ├── backup.py            # Automated backups
│       ├── health.py            # System health checks
│       ├── logging_config.py    # Centralized logging (stderr, rotating file, JSON)
│       ├── retry.py             # Retry strategies + circuit breaker
│       ├── tagging.py           # Tag registry management
│       ├── versioning.py        # Schema version tracking
│       ├── queue_manager.py     # Priority job queue
│       ├── path_validation.py   # Path canonicalization + traversal protection
│       ├── query_sanitize.py    # LanceDB query parameterization
│       └── secure_file.py       # Secure file/dir creation (0o700/0o600)
│
├── tests/
│   ├── conftest.py              # 25+ shared fixtures
│   └── test_*.py                # Unit + integration tests (185 passing)
│
├── architecture/                # Design documents (16 docs, indexed in README.md)
│   ├── README.md                # Table of contents by topic
│   └── *.md
│
├── scripts/
│   ├── run_system.sh            # Ensure server running + inbox notification
│   ├── security_scan.sh         # PII/secret scanner (pre-commit hook)
│   ├── install_menubar.sh       # Menu bar app installer
│   └── backfill_knowledge_graph.py
│
└── _project/
    └── DevPlan.md               # Development history + audit + roadmap
```

---

## Design Patterns

### Processor Pattern
All file processors inherit from BaseProcessor:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List
from src.models import Document, Chunk

class BaseProcessor(ABC):
    """Base class for all file processors."""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        pass

    @abstractmethod
    def process(self, file_path: Path) -> Document:
        """Process a file and return a Document."""
        pass

    @abstractmethod
    def extract_metadata(self, file_path: Path) -> dict:
        """Extract metadata from file."""
        pass
```

### Safe Processor Pattern
All heavy processing uses SafeProcessor for memory safety:

```python
from src.utils.safe_processor import SafeProcessor

class AudioProcessor(BaseProcessor):
    def __init__(self):
        self.safe = SafeProcessor(
            base_batch_size=4,
            base_workers=2,
            memory_pause_threshold=0.75,
            memory_resume_threshold=0.65
        )

    def process_batch(self, files: List[Path]) -> List[Document]:
        # SafeProcessor handles memory throttling
        with self.safe.managed_processing():
            return [self._process_single(f) for f in files]
```

### Configuration Pattern
Use environment variables with sensible defaults:

```python
from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass
class Config:
    # Paths
    corerag_home: Path = field(default_factory=lambda: Path.home() / ".corerag")
    db_path: Path = field(default_factory=lambda: Path.home() / ".corerag" / "lancedb")

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 50
    parent_chunk_size: int = 2048

    # Embeddings (actual model: all-MiniLM-L6-v2)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    embedding_batch_size: int = 32

    # Memory thresholds
    memory_pause_threshold: float = 0.75
    memory_resume_threshold: float = 0.65

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            corerag_home=Path(os.getenv("CORERAG_HOME", str(cls().corerag_home))),
            chunk_size=int(os.getenv("CORERAG_CHUNK_SIZE", cls().chunk_size)),
            memory_pause_threshold=float(os.getenv("CORERAG_MEMORY_PAUSE", cls().memory_pause_threshold)),
        )

# Usage
config = Config.from_env()
```

---

## Error Handling

### Custom Exceptions
Custom exceptions are defined in `src/exceptions.py`. Always use specific exception types instead of bare `except:` or `except Exception:`.

```python
from src.exceptions import (
    CoreRagError,           # Base exception (catch-all for our exceptions)
    ProcessingError,        # File processing failures (extraction, analysis)
    EmbeddingError,         # Embedding generation failures
    DatabaseError,          # LanceDB operations (connection, query, write)
    SearchError,            # Search pipeline failures (hybrid, reranker)
    ConfigurationError,     # Missing/invalid config (env vars, paths)
    CoreRagMemoryError,     # Memory threshold exceeded (not stdlib MemoryError)
)

# Each exception includes context-aware messages:
raise DatabaseError("LanceDB connection failed", {"db_path": db_path})
raise ProcessingError("Text extraction failed", {"file": str(file_path)})
```

### Try/Except Pattern
```python
from src.exceptions import ProcessingError, CoreRagMemoryError, DatabaseError

def process_file(file_path: Path) -> Optional[Document]:
    """Process a file with proper error handling."""
    try:
        processor = get_processor_for_file(file_path)
        return processor.process(file_path)
    except ProcessingError as e:
        logger.warning(f"Failed to process {file_path}: {e}")
        return None
    except CoreRagMemoryError as e:
        logger.error(f"Memory exceeded processing {file_path}: {e}")
        raise  # Re-raise for SafeProcessor to handle
    except DatabaseError as e:
        logger.error(f"Database error processing {file_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing {file_path}: {e}")
        raise
```

---

## Logging

```python
import logging
from pathlib import Path

def setup_logging(log_dir: Path = Path.home() / ".corerag" / "logs"):
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "corerag.log"),
            logging.StreamHandler()
        ]
    )

# In each module
logger = logging.getLogger(__name__)
```

---

## Testing

### File Structure
```
tests/
├── conftest.py              # Shared fixtures
├── golden_set/              # Search quality regression
│   ├── test_queries.json
│   └── expected_results.json
├── test_embeddings.py
├── test_storage.py
├── test_search/
│   ├── test_hybrid.py
│   ├── test_hyde.py
│   └── test_reranker.py
├── test_ingestion/
│   ├── test_pipeline.py
│   └── test_processors.py
└── test_mcp/
    └── test_tools.py
```

### Test Pattern
```python
import pytest
from pathlib import Path
from src.ingestion.pipeline import IngestionPipeline

@pytest.fixture
def sample_pdf(tmp_path):
    """Create a sample PDF for testing."""
    # Create or copy sample file
    return tmp_path / "sample.pdf"

@pytest.fixture
def pipeline():
    """Create test pipeline instance."""
    return IngestionPipeline(test_mode=True)

class TestIngestionPipeline:
    def test_process_extracts_text(self, pipeline, sample_pdf):
        doc = pipeline.process_file(sample_pdf)

        assert doc is not None
        assert len(doc.chunks) > 0

    def test_handles_corrupted_file(self, pipeline, tmp_path):
        bad_file = tmp_path / "bad.pdf"
        bad_file.write_bytes(b"not a pdf")

        result = pipeline.process_file(bad_file)
        assert result is None  # Graceful failure

    def test_respects_memory_limits(self, pipeline, large_batch):
        # Should pause when memory threshold exceeded
        with pytest.raises(MemoryError):
            pipeline.process_batch(large_batch, force_oom=True)
```

---

## Git Commit Messages

Format: `<type>: <description>`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance
- `perf`: Performance improvement

Examples:
```
feat: add hybrid search with BM25 fusion
fix: handle memory overflow in batch processing
docs: update README with CLI commands
refactor: extract chunking logic to separate module
test: add golden set regression tests
perf: add semantic cache for repeated queries
```

---

## Comments

```python
# Good: Explains WHY, not WHAT
# Pause processing to prevent OOM - M4 Max can spike during embedding
if memory_usage > 0.75:
    self._pause_processing()

# Good: Explains non-obvious behavior
# RRF constant k=60 provides good balance between precision and recall
# per Cormack et al. (2009)
k = 60

# Bad: States the obvious
# Check if hash is in set
if file_hash in processed_hashes:
    return None
```

---

## CLI Conventions

```python
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="CoreRag CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search knowledge base")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--limit", type=int, default=10)

    args = parser.parse_args()

    if args.command == "search":
        return cmd_search(args)

    parser.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())
```

---

*Follow these conventions consistently. Update this file if new patterns emerge.*
*Last Updated: 2026-02-07*
