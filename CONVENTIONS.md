# Coding Conventions

> Follow these patterns for all code in this project.

---

## Python Standards

### General
- Python 3.11+ required
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
AntiGravity_PKM/
├── src/
│   ├── __init__.py
│   │
│   ├── mcp_server/              # MCP interface for Claude
│   │   ├── __init__.py
│   │   ├── server.py            # FastMCP server
│   │   └── tools.py             # Tool implementations
│   │
│   ├── embeddings/              # Embedding generation
│   │   ├── __init__.py
│   │   └── embedding_service.py # nomic-embed-text with caching
│   │
│   ├── storage/                 # Database operations
│   │   ├── __init__.py
│   │   └── vector_store.py      # LanceDB wrapper
│   │
│   ├── ingestion/               # File ingestion pipeline
│   │   ├── __init__.py
│   │   ├── pipeline.py          # Main orchestrator
│   │   └── queue_manager.py     # Priority queue
│   │
│   ├── search/                  # Search functionality
│   │   ├── __init__.py
│   │   ├── hybrid_search.py     # Vector + BM25 fusion
│   │   ├── hyde_search.py       # HyDE query expansion
│   │   ├── reranker.py          # Cross-encoder reranking
│   │   ├── decay_scoring.py     # Time-weighted relevance
│   │   └── multi_query.py       # Query decomposition + RRF
│   │
│   ├── chunking/                # Text chunking strategies
│   │   ├── __init__.py
│   │   ├── parent_child.py      # Hierarchical chunking
│   │   └── code_ast.py          # AST-aware code chunking
│   │
│   ├── quality/                 # Quality assurance
│   │   ├── __init__.py
│   │   ├── duplicate_detector.py    # Hash + MinHash + semantic
│   │   ├── freshness_tracker.py     # Stale content detection
│   │   ├── link_checker.py          # Async URL validation
│   │   └── conflict_detector.py     # Contradiction finder
│   │
│   ├── classification/          # Document classification
│   │   ├── __init__.py
│   │   └── auto_tagger.py       # Keyword + embedding tagging
│   │
│   ├── analytics/               # Usage analytics
│   │   ├── __init__.py
│   │   ├── query_analytics.py   # Query tracking
│   │   └── semantic_cache.py    # Similarity-based caching
│   │
│   ├── ocr/                     # Optical character recognition
│   │   ├── __init__.py
│   │   └── vision_ocr.py        # macOS Vision.framework
│   │
│   ├── multimodal/              # Multi-modal processing
│   │   ├── __init__.py
│   │   └── vlm_captioner.py     # VLM image captioning
│   │
│   ├── audio/                   # Audio processing
│   │   ├── __init__.py
│   │   └── topic_segmenter.py   # Topic-based chunking
│   │
│   ├── video/                   # Video processing
│   │   ├── __init__.py
│   │   └── scene_detector.py    # OpenCV scene detection
│   │
│   ├── graph/                   # Knowledge graph
│   │   ├── __init__.py
│   │   └── knowledge_graph.py   # GraphRAG implementation
│   │
│   ├── memory/                  # Conversation memory
│   │   ├── __init__.py
│   │   └── episodic_memory.py   # Session memory
│   │
│   ├── sync/                    # Synchronization
│   │   ├── __init__.py
│   │   └── zombie_reconciler.py # Orphan cleanup
│   │
│   ├── maintenance/             # Database maintenance
│   │   ├── __init__.py
│   │   └── db_optimizer.py      # Index optimization
│   │
│   ├── processors/              # File processors
│   │   ├── __init__.py
│   │   └── spreadsheet_processor.py  # Excel/CSV
│   │
│   ├── cli/                     # Command-line interface
│   │   ├── __init__.py
│   │   └── main.py              # CLI commands
│   │
│   ├── dashboard/               # Monitoring dashboard
│   │   ├── __init__.py
│   │   └── health_dashboard.py  # Web UI
│   │
│   └── utils/                   # Shared utilities
│       ├── __init__.py
│       ├── safe_processor.py    # Memory-aware processing
│       ├── hardware_monitor.py  # CPU/GPU monitoring
│       ├── privacy_audit.py     # PII detection
│       ├── checkpoint_manager.py # Job persistence
│       └── backup_manager.py    # Automated backups
│
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── golden_set/              # Search quality tests
│   │   └── test_queries.json
│   └── test_*.py                # Unit tests
│
├── architecture/                # Design documents
│   ├── data_schema.md
│   ├── HARDWARE_SAFETY.md
│   ├── PERFORMANCE_GUIDE.md
│   └── PKM_Design_*.md
│
└── docs/
    └── USER_GUIDE.md            # End-user documentation
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
    pkm_home: Path = field(default_factory=lambda: Path.home() / ".pkm")
    db_path: Path = field(default_factory=lambda: Path.home() / ".pkm" / "lancedb")

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 50
    parent_chunk_size: int = 2048

    # Embeddings
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 32

    # Memory thresholds
    memory_pause_threshold: float = 0.75
    memory_resume_threshold: float = 0.65

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            pkm_home=Path(os.getenv("PKM_HOME", str(cls().pkm_home))),
            chunk_size=int(os.getenv("PKM_CHUNK_SIZE", cls().chunk_size)),
            memory_pause_threshold=float(os.getenv("PKM_MEMORY_PAUSE", cls().memory_pause_threshold)),
        )

# Usage
config = Config.from_env()
```

---

## Error Handling

### Custom Exceptions
```python
class PKMError(Exception):
    """Base exception for PKM system."""
    pass

class ProcessingError(PKMError):
    """Error during file processing."""
    pass

class EmbeddingError(PKMError):
    """Error generating embeddings."""
    pass

class DatabaseError(PKMError):
    """Error with vector database operations."""
    pass

class MemoryError(PKMError):
    """Memory threshold exceeded."""
    pass
```

### Try/Except Pattern
```python
def process_file(file_path: Path) -> Optional[Document]:
    """Process a file with proper error handling."""
    try:
        processor = get_processor_for_file(file_path)
        return processor.process(file_path)
    except ProcessingError as e:
        logger.warning(f"Failed to process {file_path}: {e}")
        return None
    except MemoryError as e:
        logger.error(f"Memory exceeded processing {file_path}: {e}")
        raise  # Re-raise for SafeProcessor to handle
    except Exception as e:
        logger.error(f"Unexpected error processing {file_path}: {e}")
        raise
```

---

## Logging

```python
import logging
from pathlib import Path

def setup_logging(log_dir: Path = Path.home() / ".pkm" / "logs"):
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "pkm.log"),
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
        description="PKM System CLI",
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
*Last Updated: 2026-01-31*
