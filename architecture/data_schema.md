# Data Schema

> **Status**: ✅ Implemented | See `src/models/` for implementation

> **CRITICAL**: All code must match these data structures exactly.

---

## Core Models

### Document

Represents a single source file in the knowledge base.

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from enum import Enum

class PrivacyTier(Enum):
    PUBLIC = "public"      # Can be sent to cloud APIs
    PRIVATE = "private"    # Local processing only
    SENSITIVE = "sensitive" # Extra care, local only

class FileType(Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "markdown"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "image"
    XLSX = "xlsx"

@dataclass
class Document:
    """A source document in the knowledge base."""

    # Identity
    id: str                          # UUID
    file_path: Path                  # Original file location
    file_hash: str                   # SHA-256 for deduplication

    # File metadata
    file_type: FileType
    file_size_bytes: int
    file_name: str
    file_extension: str

    # Timestamps
    created_at: datetime             # When added to PKM
    modified_at: datetime            # Last file modification
    indexed_at: datetime             # When last processed

    # Extracted metadata
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    language: str = "en"
    page_count: Optional[int] = None
    word_count: Optional[int] = None
    duration_seconds: Optional[float] = None  # For audio/video

    # Classification
    topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    collection: Optional[str] = None
    privacy_tier: PrivacyTier = PrivacyTier.PRIVATE

    # AI-generated
    summary: Optional[str] = None
    keywords: List[str] = field(default_factory=list)

    # Processing status
    processing_status: str = "pending"  # pending, processing, complete, error
    error_message: Optional[str] = None
```

### Chunk

Represents a segment of a document, the unit of embedding and retrieval.

```python
@dataclass
class Chunk:
    """A chunk of text from a document."""

    # Identity
    id: str                          # UUID
    document_id: str                 # Parent document ID

    # Content
    text: str                        # The actual text content
    embedding: List[float]           # 768-dimensional vector

    # Position in document
    chunk_index: int                 # 0, 1, 2, ... within document
    start_char: int                  # Character offset in source
    end_char: int                    # End character offset
    page_number: Optional[int] = None  # For PDFs
    timestamp_start: Optional[float] = None  # For audio/video
    timestamp_end: Optional[float] = None

    # Chunk metadata
    token_count: int = 0
    has_code: bool = False
    has_table: bool = False
    has_image_ref: bool = False

    # Context
    heading_hierarchy: List[str] = field(default_factory=list)  # ["Chapter 1", "Section 1.2"]
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
```

---

## LanceDB Table Schemas

### documents table

```python
import lancedb
import pyarrow as pa

documents_schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("file_path", pa.string()),
    pa.field("file_hash", pa.string()),
    pa.field("file_type", pa.string()),
    pa.field("file_size_bytes", pa.int64()),
    pa.field("file_name", pa.string()),
    pa.field("file_extension", pa.string()),
    pa.field("created_at", pa.timestamp("us")),
    pa.field("modified_at", pa.timestamp("us")),
    pa.field("indexed_at", pa.timestamp("us")),
    pa.field("title", pa.string()),
    pa.field("author", pa.string()),
    pa.field("subject", pa.string()),
    pa.field("language", pa.string()),
    pa.field("page_count", pa.int32()),
    pa.field("word_count", pa.int32()),
    pa.field("duration_seconds", pa.float64()),
    pa.field("topics", pa.list_(pa.string())),
    pa.field("tags", pa.list_(pa.string())),
    pa.field("collection", pa.string()),
    pa.field("privacy_tier", pa.string()),
    pa.field("summary", pa.string()),
    pa.field("keywords", pa.list_(pa.string())),
    pa.field("processing_status", pa.string()),
    pa.field("error_message", pa.string()),
])
```

### chunks table

```python
chunks_schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("document_id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("embedding", pa.list_(pa.float32(), 768)),  # Fixed 768 dimensions
    pa.field("chunk_index", pa.int32()),
    pa.field("start_char", pa.int32()),
    pa.field("end_char", pa.int32()),
    pa.field("page_number", pa.int32()),
    pa.field("timestamp_start", pa.float64()),
    pa.field("timestamp_end", pa.float64()),
    pa.field("token_count", pa.int32()),
    pa.field("has_code", pa.bool_()),
    pa.field("has_table", pa.bool_()),
    pa.field("has_image_ref", pa.bool_()),
    pa.field("heading_hierarchy", pa.list_(pa.string())),
    pa.field("prev_chunk_id", pa.string()),
    pa.field("next_chunk_id", pa.string()),
])
```

---

## Search Result

```python
@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    document_id: str
    score: float                     # Similarity score (0-1)

    # Chunk content
    text: str
    page_number: Optional[int]
    timestamp_start: Optional[float]

    # Document context
    document_title: str
    file_path: str
    file_type: str

    # Surrounding context
    context_before: Optional[str] = None
    context_after: Optional[str] = None


@dataclass
class SearchResponse:
    """Response from a search query."""

    query: str
    results: List[SearchResult]
    total_count: int
    search_time_ms: float
```

---

## Personal Context Schema

```python
@dataclass
class PersonalContext:
    """User's personal context for AI interactions."""

    # Identity
    name: str
    email: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None

    # Preferences
    communication_style: str = "balanced"  # concise, balanced, detailed
    technical_level: str = "intermediate"   # beginner, intermediate, expert
    preferred_format: str = "markdown"      # markdown, plain, structured

    # Active projects
    current_projects: List[str] = field(default_factory=list)
    active_interests: List[str] = field(default_factory=list)

    # Goals
    short_term_goals: List[str] = field(default_factory=list)
    long_term_goals: List[str] = field(default_factory=list)

    # Environment
    hardware: Optional[str] = None
    tools: List[str] = field(default_factory=list)

    # Last updated
    updated_at: datetime = field(default_factory=datetime.now)
```

---

## Embedding Specifications

| Property | Value |
|----------|-------|
| Model | nomic-ai/nomic-embed-text-v1.5 |
| Dimensions | 768 |
| Max Tokens | 8192 |
| Similarity Metric | Cosine |

```python
# Embedding generation example
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)

# For search queries, prefix with "search_query:"
query_embedding = model.encode("search_query: What is machine learning?")

# For documents, prefix with "search_document:"
doc_embedding = model.encode("search_document: Machine learning is a subset of AI...")
```

---

## Chunking Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Chunk Size | 512 tokens | Balances context and precision |
| Chunk Overlap | 50 tokens | Ensures continuity |
| Min Chunk Size | 100 tokens | Avoids tiny fragments |
| Max Chunk Size | 1024 tokens | Fits in context window |

---

## Topic Taxonomy

Top-level topics (expandable):

```python
TOPIC_TAXONOMY = {
    "ai": ["machine-learning", "deep-learning", "nlp", "computer-vision", "robotics"],
    "technology": ["software", "hardware", "cloud", "security", "data"],
    "research": ["papers", "studies", "experiments", "findings"],
    "personal": ["notes", "journal", "ideas", "drafts"],
    "business": ["strategy", "finance", "marketing", "operations"],
    "media": ["articles", "videos", "podcasts", "books"],
}
```

---

*All implementations must conform to these schemas. Update this document if schemas change.*
