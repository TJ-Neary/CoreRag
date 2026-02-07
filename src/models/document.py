"""Document and Chunk models for CoreRag."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional


class PrivacyTier(Enum):
    """Privacy classification for documents."""

    PUBLIC = "public"  # Can be sent to cloud APIs
    PRIVATE = "private"  # Local processing only (default)
    SENSITIVE = "sensitive"  # Extra care, local only, encrypted


class FileType(Enum):
    """Supported file types."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "markdown"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "image"
    XLSX = "xlsx"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, ext: str) -> "FileType":
        """Get FileType from file extension."""
        ext = ext.lower().lstrip(".")
        mapping = {
            "pdf": cls.PDF,
            "docx": cls.DOCX,
            "doc": cls.DOCX,
            "txt": cls.TXT,
            "md": cls.MD,
            "markdown": cls.MD,
            "mp3": cls.AUDIO,
            "m4a": cls.AUDIO,
            "wav": cls.AUDIO,
            "mp4": cls.VIDEO,
            "mov": cls.VIDEO,
            "avi": cls.VIDEO,
            "png": cls.IMAGE,
            "jpg": cls.IMAGE,
            "jpeg": cls.IMAGE,
            "xlsx": cls.XLSX,
            "xls": cls.XLSX,
        }
        return mapping.get(ext, cls.UNKNOWN)


@dataclass
class Document:
    """A source document in the knowledge base."""

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_path: Path = field(default_factory=Path)
    file_hash: str = ""  # SHA-256 for deduplication

    # File metadata
    file_type: FileType = FileType.UNKNOWN
    file_size_bytes: int = 0
    file_name: str = ""
    file_extension: str = ""

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    indexed_at: datetime = field(default_factory=datetime.now)

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

    # Chunks (populated after processing)
    chunks: List["Chunk"] = field(default_factory=list)

    @classmethod
    def from_file(cls, file_path: Path) -> "Document":
        """Create a Document from a file path."""
        import hashlib

        path = Path(file_path)
        stat = path.stat()

        # Compute file hash
        with open(path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        return cls(
            file_path=path,
            file_hash=file_hash,
            file_type=FileType.from_extension(path.suffix),
            file_size_bytes=stat.st_size,
            file_name=path.name,
            file_extension=path.suffix.lower(),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "file_path": str(self.file_path),
            "file_hash": self.file_hash,
            "file_type": self.file_type.value,
            "file_size_bytes": self.file_size_bytes,
            "file_name": self.file_name,
            "file_extension": self.file_extension,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "indexed_at": self.indexed_at.isoformat(),
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "language": self.language,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "duration_seconds": self.duration_seconds,
            "topics": self.topics,
            "tags": self.tags,
            "collection": self.collection,
            "privacy_tier": self.privacy_tier.value,
            "summary": self.summary,
            "keywords": self.keywords,
            "processing_status": self.processing_status,
            "error_message": self.error_message,
        }


@dataclass
class Chunk:
    """A chunk of text from a document."""

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""

    # Content
    text: str = ""
    embedding: List[float] = field(
        default_factory=list
    )  # 384-dimensional vector (all-MiniLM-L6-v2)

    # Position in document
    chunk_index: int = 0  # 0, 1, 2, ... within document
    start_char: int = 0  # Character offset in source
    end_char: int = 0  # End character offset
    page_number: Optional[int] = None  # For PDFs
    timestamp_start: Optional[float] = None  # For audio/video (seconds)
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

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "text": self.text,
            "embedding": self.embedding,
            "chunk_index": self.chunk_index,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "page_number": self.page_number,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "token_count": self.token_count,
            "has_code": self.has_code,
            "has_table": self.has_table,
            "has_image_ref": self.has_image_ref,
            "heading_hierarchy": self.heading_hierarchy,
            "prev_chunk_id": self.prev_chunk_id,
            "next_chunk_id": self.next_chunk_id,
        }
