"""
Ingestion Pipeline Orchestrator for PKM.

Routes files to appropriate processors based on type:
- Documents (MD, TXT, DOCX, PDF) → Text extraction + chunking
- Images (PNG, JPG, etc.) → VLM captioning
- Audio (MP3, WAV, M4A) → Whisper transcription + topic segmentation
- Video (MP4, MOV) → Scene detection + captioning
- Code (PY, JS, etc.) → AST chunking
- Spreadsheets (XLSX, CSV) → Summary generation

Handles:
- File watching for automatic ingestion
- Queue management with priority
- Memory-aware throttling
- Privacy scanning
- Deduplication
"""

import asyncio
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Any
import hashlib
import json
import threading
import shutil
from queue import PriorityQueue

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

logger = logging.getLogger(__name__)


class FileType(Enum):
    """Supported file types for ingestion."""
    MARKDOWN = "markdown"
    TEXT = "text"
    PDF = "pdf"
    DOCX = "docx"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    CODE = "code"
    SPREADSHEET = "spreadsheet"
    UNKNOWN = "unknown"


class IngestionStatus(Enum):
    """Status of an ingestion job."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(order=True)
class IngestionJob:
    """A file to be ingested."""
    priority: int
    file_path: Path = field(compare=False)
    file_type: FileType = field(compare=False)
    status: IngestionStatus = field(default=IngestionStatus.QUEUED, compare=False)
    created_at: datetime = field(default_factory=datetime.now, compare=False)
    started_at: Optional[datetime] = field(default=None, compare=False)
    completed_at: Optional[datetime] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    result: Optional[Dict] = field(default=None, compare=False)


@dataclass
class IngestionResult:
    """Result of ingesting a file."""
    file_path: str
    file_type: FileType
    success: bool
    chunks_created: int = 0
    entities_extracted: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class FileTypeDetector:
    """Detect file types for routing to appropriate processor."""

    # Extension to FileType mapping
    EXTENSION_MAP = {
        # Documents
        ".md": FileType.MARKDOWN,
        ".markdown": FileType.MARKDOWN,
        ".txt": FileType.TEXT,
        ".pdf": FileType.PDF,
        ".docx": FileType.DOCX,
        ".doc": FileType.DOCX,

        # Images
        ".png": FileType.IMAGE,
        ".jpg": FileType.IMAGE,
        ".jpeg": FileType.IMAGE,
        ".gif": FileType.IMAGE,
        ".webp": FileType.IMAGE,
        ".svg": FileType.IMAGE,
        ".bmp": FileType.IMAGE,

        # Audio
        ".mp3": FileType.AUDIO,
        ".wav": FileType.AUDIO,
        ".m4a": FileType.AUDIO,
        ".flac": FileType.AUDIO,
        ".ogg": FileType.AUDIO,

        # Video
        ".mp4": FileType.VIDEO,
        ".mov": FileType.VIDEO,
        ".avi": FileType.VIDEO,
        ".mkv": FileType.VIDEO,
        ".webm": FileType.VIDEO,

        # Code
        ".py": FileType.CODE,
        ".js": FileType.CODE,
        ".ts": FileType.CODE,
        ".jsx": FileType.CODE,
        ".tsx": FileType.CODE,
        ".java": FileType.CODE,
        ".cpp": FileType.CODE,
        ".c": FileType.CODE,
        ".go": FileType.CODE,
        ".rs": FileType.CODE,
        ".rb": FileType.CODE,
        ".php": FileType.CODE,
        ".swift": FileType.CODE,
        ".kt": FileType.CODE,

        # Spreadsheets
        ".xlsx": FileType.SPREADSHEET,
        ".xls": FileType.SPREADSHEET,
        ".csv": FileType.SPREADSHEET,
        ".tsv": FileType.SPREADSHEET,
    }

    @classmethod
    def detect(cls, file_path: Path) -> FileType:
        """Detect file type from path."""
        ext = file_path.suffix.lower()
        return cls.EXTENSION_MAP.get(ext, FileType.UNKNOWN)


class IngestionPipeline:
    """
    Main orchestrator for file ingestion.

    Routes files to appropriate processors and manages the queue.
    """

    def __init__(
        self,
        watch_dirs: Optional[List[Path]] = None,
        state_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        max_workers: int = 4,
        enable_watch: bool = True,
    ):
        """
        Initialize ingestion pipeline.

        Args:
            watch_dirs: Directories to watch for new files
            state_dir: Directory for state persistence
            db_path: Path to LanceDB database
            max_workers: Maximum concurrent processing jobs
            enable_watch: Whether to enable file watching
        """
        # Get defaults from environment or use standard paths
        default_watch = os.getenv("PKM_WATCH_DIR", str(Path.home() / "Documents" / "PKM_Input"))
        default_state = os.getenv("PKM_STATE_DIR", str(Path.home() / ".pkm" / "ingestion"))
        default_db = os.getenv("PKM_DB_PATH", str(Path.home() / ".pkm" / "lancedb"))
        
        self.watch_dirs = watch_dirs or [Path(default_watch)]
        self.state_dir = state_dir or Path(default_state)
        self.db_path = db_path or Path(default_db)
        self.max_workers = max_workers
        self.enable_watch = enable_watch

        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Queue management
        self._queue: PriorityQueue = PriorityQueue()
        self._processing: Dict[str, IngestionJob] = {}
        self._completed: List[IngestionResult] = []
        self._lock = threading.Lock()

        # File watching
        self._observer: Optional[Observer] = None
        self._ignore_patterns: Set[str] = set()

        # Processors (lazy loaded)
        self._processors: Dict[FileType, Callable] = {}

        # Lazy-loaded services for ingestion
        self._chunker = None
        self._embedder = None
        self._db = None
        self._obsidian_exporter = None

        # Load state
        self._load_state()

        # Load ignore patterns
        self._load_ignore_patterns()

    def start(self) -> None:
        """Start the ingestion pipeline."""
        logger.info("Starting ingestion pipeline...")

        # Start file watcher
        if self.enable_watch:
            self._start_watcher()

        # Start processing workers
        for i in range(self.max_workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"ingestion-worker-{i}",
                daemon=True,
            )
            thread.start()

        logger.info(f"Ingestion pipeline started with {self.max_workers} workers")

    def stop(self) -> None:
        """Stop the ingestion pipeline."""
        logger.info("Stopping ingestion pipeline...")

        if self._observer:
            self._observer.stop()
            self._observer.join()

        self._save_state()
        logger.info("Ingestion pipeline stopped")

    def add_file(
        self,
        file_path: Path,
        priority: int = 5,
        force: bool = False,
    ) -> Optional[IngestionJob]:
        """
        Add a file to the ingestion queue.

        Args:
            file_path: Path to file
            priority: Priority (1=highest, 10=lowest)
            force: Force re-ingestion even if already processed

        Returns:
            IngestionJob if queued, None if skipped
        """
        file_path = Path(file_path).resolve()

        # Check if file exists
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        # Check ignore patterns
        if self._should_ignore(file_path):
            logger.debug(f"Ignoring file: {file_path}")
            return None

        # Check if already processed (unless force)
        if not force and self._is_processed(file_path):
            logger.debug(f"Already processed: {file_path}")
            return None

        # Detect file type
        file_type = FileTypeDetector.detect(file_path)
        if file_type == FileType.UNKNOWN:
            logger.warning(f"Unknown file type: {file_path}")
            return None

        # Create job
        job = IngestionJob(
            priority=priority,
            file_path=file_path,
            file_type=file_type,
        )

        # Add to queue
        with self._lock:
            self._queue.put(job)

        logger.info(f"Queued for ingestion: {file_path.name} ({file_type.value})")
        return job

    def add_directory(
        self,
        dir_path: Path,
        recursive: bool = True,
        priority: int = 5,
    ) -> int:
        """
        Add all files in a directory to the queue.

        Returns:
            Number of files queued
        """
        dir_path = Path(dir_path)
        count = 0

        pattern = "**/*" if recursive else "*"
        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                if self.add_file(file_path, priority=priority):
                    count += 1

        logger.info(f"Queued {count} files from {dir_path}")
        return count

    def get_queue_status(self) -> Dict:
        """Get current queue status."""
        with self._lock:
            return {
                "queued": self._queue.qsize(),
                "processing": len(self._processing),
                "completed": len(self._completed),
                "processing_files": [
                    str(j.file_path.name) for j in self._processing.values()
                ],
            }

    def get_recent_results(self, limit: int = 10) -> List[IngestionResult]:
        """Get recent ingestion results."""
        with self._lock:
            return self._completed[-limit:]

    def register_processor(
        self,
        file_type: FileType,
        processor: Callable[[Path], IngestionResult],
    ) -> None:
        """
        Register a processor for a file type.

        Args:
            file_type: File type to handle
            processor: Function that processes the file
        """
        self._processors[file_type] = processor
        logger.info(f"Registered processor for {file_type.value}")

    def _worker_loop(self) -> None:
        """Worker loop for processing queue."""
        while True:
            try:
                # Get next job (blocks until available)
                job = self._queue.get(timeout=1.0)

                # Process the job
                self._process_job(job)

            except Exception as e:
                if "Empty" not in str(type(e)):
                    logger.error(f"Worker error: {e}")

    def _process_job(self, job: IngestionJob) -> None:
        """Process a single ingestion job."""
        job.status = IngestionStatus.PROCESSING
        job.started_at = datetime.now()

        with self._lock:
            self._processing[str(job.file_path)] = job

        try:
            # Get processor for file type
            processor = self._processors.get(job.file_type)

            if processor:
                result = processor(job.file_path)
            else:
                # Use default processor
                result = self._default_processor(job)

            job.status = IngestionStatus.COMPLETED
            job.result = result.__dict__ if hasattr(result, '__dict__') else result

            with self._lock:
                self._completed.append(result)

            logger.info(f"Ingested: {job.file_path.name}")

        except Exception as e:
            job.status = IngestionStatus.FAILED
            job.error = str(e)
            logger.error(f"Failed to ingest {job.file_path.name}: {e}")

        finally:
            job.completed_at = datetime.now()

            with self._lock:
                del self._processing[str(job.file_path)]

            # Save state periodically
            self._save_state()

    def _get_chunker(self):
        """Lazy-load the chunker."""
        if self._chunker is None:
            from src.chunking.parent_child import ParentChildChunker
            self._chunker = ParentChildChunker()
        return self._chunker

    def _get_embedder(self):
        """Lazy-load the embedding service."""
        if self._embedder is None:
            from src.embeddings.embedding_service import create_embedding_service
            self._embedder = create_embedding_service()
        return self._embedder

    def _get_db(self):
        """Lazy-load the database connection."""
        if self._db is None:
            import lancedb
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    def _get_obsidian_exporter(self):
        """Lazy-load the Obsidian exporter."""
        if self._obsidian_exporter is None:
            from src.obsidian.obsidian_export import ObsidianExporter
            self._obsidian_exporter = ObsidianExporter()
        return self._obsidian_exporter

    def _move_to_processed(self, file_path: Path) -> Path:
        """Move file from inbox to processed folder with date prefix."""
        # Check if file is in inbox
        inbox_dir = Path(os.getenv("PKM_INBOX_DIR", str(Path.home() / "Documents" / "PKM" / "Inbox")))
        processed_dir = Path(os.getenv("PKM_PROCESSED_DIR", str(Path.home() / "Documents" / "PKM" / "Processed")))
        
        # Only move if the file is actually in the inbox directory tree
        try:
            file_path.relative_to(inbox_dir)
        except ValueError:
            # File is not in inbox (e.g. manual ingest from elsewhere), don't move
            return file_path

        processed_dir.mkdir(parents=True, exist_ok=True)
        date_prefix = datetime.now().strftime("%Y-%m-%d")
        new_name = f"{date_prefix}_{file_path.name}"
        dest = processed_dir / new_name
        
        # Handle duplicates in processed folder
        if dest.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            new_name = f"{date_prefix}_{timestamp}_{file_path.name}"
            dest = processed_dir / new_name
            
        try:
            shutil.move(str(file_path), str(dest))
            logger.info(f"Moved processed file to: {dest}")
            return dest
        except Exception as e:
            logger.error(f"Failed to move file to processed: {e}")
            return file_path

    def _extract_text(self, job: IngestionJob) -> str:
        """Extract text content from file based on type."""
        if job.file_type in {FileType.MARKDOWN, FileType.TEXT}:
            with open(job.file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        elif job.file_type == FileType.CODE:
            # For code files, include the content with file info
            with open(job.file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return f"# File: {job.file_path.name}\n\n{content}"
        elif job.file_type == FileType.PDF:
            # Try to extract PDF text
            try:
                import pdfplumber
                text_parts = []
                with pdfplumber.open(job.file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                return "\n\n".join(text_parts)
            except ImportError:
                logger.warning("pdfplumber not installed, skipping PDF")
                return ""
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")
                return ""
        else:
            # For unsupported types, return empty
            return ""

    def _default_processor(self, job: IngestionJob) -> IngestionResult:
        """Process files with chunking, embedding, and storage."""
        import time
        from datetime import datetime
        start = time.time()

        # Extract text content
        content = self._extract_text(job)
        if not content or len(content.strip()) < 50:
            return IngestionResult(
                file_path=str(job.file_path),
                file_type=job.file_type,
                success=False,
                error="No extractable content or content too short",
                duration_seconds=time.time() - start,
            )

        try:
            # Get services
            chunker = self._get_chunker()
            embedder = self._get_embedder()
            db = self._get_db()

            # Generate document ID from file hash
            document_id = self._hash_file(job.file_path)

            # Chunk the document
            logger.info(f"Chunking: {job.file_path.name}")
            parents, children = chunker.chunk_document(
                content=content,
                document_id=document_id,
                metadata={
                    "source_path": str(job.file_path),
                    "file_type": job.file_type.value,
                    "file_name": job.file_path.name,
                }
            )

            if not children:
                return IngestionResult(
                    file_path=str(job.file_path),
                    file_type=job.file_type,
                    success=False,
                    error="No chunks created",
                    duration_seconds=time.time() - start,
                )

            # Generate embeddings for child chunks
            logger.info(f"Embedding {len(children)} chunks...")
            child_texts = [c.content for c in children]
            embeddings = embedder.embed_documents(child_texts, show_progress=False)

            # Prepare data for storage
            parent_data = []
            for p in parents:
                parent_data.append({
                    "id": p.id,
                    "document_id": p.document_id,
                    "content": p.content,
                    "source_path": str(job.file_path),
                    "section_title": p.section_title or "",
                    "token_count": p.token_count,
                    "created_at": datetime.now().isoformat(),
                })

            child_data = []
            for c, emb in zip(children, embeddings):
                child_data.append({
                    "id": c.id,
                    "parent_id": c.parent_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "vector": emb,
                    "chunk_index": c.chunk_index,
                    "source_path": str(job.file_path),
                })

            # Store in LanceDB (with race condition handling)
            logger.info(f"Storing {len(parents)} parents, {len(children)} children...")
            
            # Create or append to parent_chunks table
            try:
                parent_table = db.open_table("parent_chunks")
                parent_table.add(parent_data)
            except Exception:
                # Table doesn't exist, create it
                try:
                    db.create_table("parent_chunks", parent_data)
                except Exception:
                    # Race condition - table was created by another worker
                    parent_table = db.open_table("parent_chunks")
                    parent_table.add(parent_data)

            # Create or append to child_chunks table
            try:
                child_table = db.open_table("child_chunks")
                child_table.add(child_data)
            except Exception:
                # Table doesn't exist, create it
                try:
                    db.create_table("child_chunks", child_data)
                except Exception:
                    # Race condition - table was created by another worker
                    child_table = db.open_table("child_chunks")
                    child_table.add(child_data)

            # Mark file as processed
            # Mark file as processed
            self._mark_processed(job.file_path, document_id)

            # Export to Obsidian
            try:
                exporter = self._get_obsidian_exporter()
                # Use metadata from extracted chunks or job
                export_metadata = {
                    "file_type": job.file_type.value,
                    "document_id": document_id,
                    "chunks": len(children)
                }
                exporter.export_to_vault(job.file_path, content, export_metadata)
            except Exception as e:
                logger.error(f"Obsidian export failed: {e}")
                # Don't fail the whole ingestion if export fails

            # Move to processed folder
            final_path = self._move_to_processed(job.file_path)

            return IngestionResult(
                file_path=str(final_path),
                file_type=job.file_type,
                success=True,
                chunks_created=len(children),
                entities_extracted=len(parents),
                duration_seconds=time.time() - start,
                metadata={
                    "document_id": document_id,
                    "parent_chunks": len(parents),
                    "child_chunks": len(children),
                }
            )

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            return IngestionResult(
                file_path=str(job.file_path),
                file_type=job.file_type,
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    def _mark_processed(self, file_path: Path, file_hash: str) -> None:
        """Mark a file as processed."""
        processed_file = self.state_dir / "processed.json"
        processed = {"hashes": {}}
        
        if processed_file.exists():
            try:
                with open(processed_file) as f:
                    processed = json.load(f)
            except Exception:
                pass
        
        processed["hashes"][file_hash] = {
            "path": str(file_path),
            "processed_at": datetime.now().isoformat(),
        }
        
        with open(processed_file, "w") as f:
            json.dump(processed, f, indent=2)

    def _start_watcher(self) -> None:
        """Start file system watcher."""
        self._observer = Observer()

        handler = _FileEventHandler(self)

        for watch_dir in self.watch_dirs:
            if watch_dir.exists():
                self._observer.schedule(handler, str(watch_dir), recursive=True)
                logger.info(f"Watching directory: {watch_dir}")

        self._observer.start()

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if file should be ignored."""
        # Check against ignore patterns
        path_str = str(file_path)

        for pattern in self._ignore_patterns:
            if pattern in path_str:
                return True

        # Ignore hidden files
        if file_path.name.startswith("."):
            return True

        # Ignore system files
        if file_path.name in {"Thumbs.db", ".DS_Store", "desktop.ini"}:
            return True

        return False

    def _is_processed(self, file_path: Path) -> bool:
        """Check if file was already processed."""
        # Check by file hash
        file_hash = self._hash_file(file_path)
        processed_file = self.state_dir / "processed.json"

        if processed_file.exists():
            with open(processed_file) as f:
                processed = json.load(f)
                return file_hash in processed.get("hashes", {})

        return False

    def _hash_file(self, file_path: Path) -> str:
        """Generate hash of file for deduplication."""
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _load_ignore_patterns(self) -> None:
        """Load ignore patterns from .pkmignore."""
        for watch_dir in self.watch_dirs:
            ignore_file = watch_dir / ".pkmignore"
            if ignore_file.exists():
                with open(ignore_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            self._ignore_patterns.add(line)

    def _load_state(self) -> None:
        """Load pipeline state from disk."""
        state_file = self.state_dir / "pipeline_state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    # Restore completed count
                    logger.info(f"Loaded state: {state.get('total_processed', 0)} files processed")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")

    def _save_state(self) -> None:
        """Save pipeline state to disk."""
        state_file = self.state_dir / "pipeline_state.json"

        state = {
            "total_processed": len(self._completed),
            "last_updated": datetime.now().isoformat(),
        }

        try:
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")


class _FileEventHandler(FileSystemEventHandler):
    """Handle file system events for auto-ingestion."""

    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self.pipeline.add_file(Path(event.src_path), priority=5)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self.pipeline.add_file(Path(event.src_path), priority=7, force=True)


# Convenience function
def create_pipeline(**kwargs) -> IngestionPipeline:
    """Create and start an ingestion pipeline."""
    pipeline = IngestionPipeline(**kwargs)
    pipeline.start()
    return pipeline
