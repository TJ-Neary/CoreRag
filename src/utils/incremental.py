"""
Incremental update detection for CoreRag.

Tracks file modifications to avoid reprocessing unchanged content.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FileState:
    """Tracked state of a file."""
    path: str
    mtime: float  # Last modified time
    size: int  # File size in bytes
    content_hash: Optional[str] = None  # Optional content hash
    doc_id: Optional[str] = None  # Associated document ID
    last_processed: Optional[str] = None


@dataclass
class ChangeSet:
    """Set of changes detected in a directory."""
    new_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)
    unchanged_files: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return bool(self.new_files or self.modified_files or self.deleted_files)

    @property
    def files_to_process(self) -> List[str]:
        """Get list of files that need processing."""
        return self.new_files + self.modified_files

    def summary(self) -> str:
        """Get a summary of changes."""
        return (
            f"Changes: {len(self.new_files)} new, "
            f"{len(self.modified_files)} modified, "
            f"{len(self.deleted_files)} deleted, "
            f"{len(self.unchanged_files)} unchanged"
        )


class IncrementalTracker:
    """
    Track file changes for incremental processing.

    Uses a combination of:
    - File modification time (fast check)
    - File size (quick verification)
    - Content hash (optional, thorough check)

    Usage:
        tracker = IncrementalTracker()

        # Get what changed since last run
        changes = tracker.detect_changes("/path/to/watch")

        # Process only changed files
        for file_path in changes.files_to_process:
            result = process_file(file_path)
            tracker.mark_processed(file_path, doc_id=result.id)

        # Handle deletions
        for file_path in changes.deleted_files:
            delete_from_db(tracker.get_doc_id(file_path))
            tracker.mark_deleted(file_path)
    """

    SUPPORTED_EXTENSIONS = {
        '.md', '.txt', '.pdf', '.docx', '.doc',
        '.mp3', '.wav', '.m4a', '.flac',
        '.mp4', '.mov', '.avi', '.mkv',
        '.png', '.jpg', '.jpeg', '.gif', '.webp',
        '.html', '.htm', '.json', '.csv', '.xlsx'
    }

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        use_content_hash: bool = False
    ):
        """
        Initialize incremental tracker.

        Args:
            state_dir: Directory to store tracking state
            use_content_hash: Whether to compute content hashes (slower but thorough)
        """
        self.state_dir = state_dir or Path.home() / ".corerag" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.use_content_hash = use_content_hash
        self._file_states: Dict[str, FileState] = {}
        self._load_state()

    def detect_changes(
        self,
        directory: Path,
        extensions: Optional[Set[str]] = None,
        recursive: bool = True
    ) -> ChangeSet:
        """
        Detect changes in a directory since last check.

        Args:
            directory: Directory to scan
            extensions: File extensions to track (default: SUPPORTED_EXTENSIONS)
            recursive: Whether to scan subdirectories

        Returns:
            ChangeSet with categorized files
        """
        extensions = extensions or self.SUPPORTED_EXTENSIONS
        directory = Path(directory)

        changes = ChangeSet()
        current_files: Set[str] = set()

        # Scan directory
        pattern = "**/*" if recursive else "*"
        for file_path in directory.glob(pattern):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue

            path_str = str(file_path.absolute())
            current_files.add(path_str)

            # Check if file is tracked
            if path_str not in self._file_states:
                changes.new_files.append(path_str)
                continue

            # Check for modifications
            old_state = self._file_states[path_str]
            try:
                stat = file_path.stat()

                # Quick check: mtime and size
                if stat.st_mtime != old_state.mtime or stat.st_size != old_state.size:
                    # Definitely changed
                    changes.modified_files.append(path_str)
                elif self.use_content_hash and old_state.content_hash:
                    # Thorough check: content hash
                    current_hash = self._compute_hash(file_path)
                    if current_hash != old_state.content_hash:
                        changes.modified_files.append(path_str)
                    else:
                        changes.unchanged_files.append(path_str)
                else:
                    changes.unchanged_files.append(path_str)

            except OSError as e:
                logger.warning(f"Could not stat file {path_str}: {e}")
                changes.modified_files.append(path_str)

        # Find deleted files
        tracked_in_dir = {
            p for p in self._file_states.keys()
            if p.startswith(str(directory))
        }
        changes.deleted_files = list(tracked_in_dir - current_files)

        logger.info(f"Scan complete: {changes.summary()}")

        return changes

    def mark_processed(
        self,
        file_path: Path,
        doc_id: Optional[str] = None,
        content_hash: Optional[str] = None
    ) -> None:
        """
        Mark a file as processed.

        Args:
            file_path: Path to the file
            doc_id: Document ID in the database
            content_hash: Pre-computed content hash
        """
        file_path = Path(file_path)
        path_str = str(file_path.absolute())

        try:
            stat = file_path.stat()

            self._file_states[path_str] = FileState(
                path=path_str,
                mtime=stat.st_mtime,
                size=stat.st_size,
                content_hash=content_hash or (
                    self._compute_hash(file_path) if self.use_content_hash else None
                ),
                doc_id=doc_id,
                last_processed=datetime.now().isoformat()
            )

            self._save_state()

        except OSError as e:
            logger.error(f"Could not mark file processed: {e}")

    def mark_deleted(self, file_path: str) -> Optional[str]:
        """
        Remove a file from tracking.

        Args:
            file_path: Path to the deleted file

        Returns:
            The doc_id if it was tracked, for cleanup
        """
        if file_path in self._file_states:
            state = self._file_states.pop(file_path)
            self._save_state()
            return state.doc_id
        return None

    def get_doc_id(self, file_path: str) -> Optional[str]:
        """Get the document ID for a tracked file."""
        state = self._file_states.get(file_path)
        return state.doc_id if state else None

    def get_state(self, file_path: str) -> Optional[FileState]:
        """Get the tracked state for a file."""
        return self._file_states.get(file_path)

    def get_all_tracked(self) -> List[FileState]:
        """Get all tracked files."""
        return list(self._file_states.values())

    def get_stats(self) -> Dict:
        """Get tracking statistics."""
        return {
            "total_tracked": len(self._file_states),
            "with_doc_id": sum(1 for s in self._file_states.values() if s.doc_id),
            "with_content_hash": sum(1 for s in self._file_states.values() if s.content_hash),
        }

    def clear(self) -> None:
        """Clear all tracking state."""
        self._file_states.clear()
        self._save_state()
        logger.info("Tracking state cleared")

    @staticmethod
    def _compute_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_dir / "incremental_state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)

                for path_str, state_data in data.get("files", {}).items():
                    self._file_states[path_str] = FileState(**state_data)

                logger.info(f"Loaded tracking state: {len(self._file_states)} files")
            except Exception as e:
                logger.error(f"Failed to load tracking state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.state_dir / "incremental_state.json"

        data = {
            "files": {
                path: {
                    "path": state.path,
                    "mtime": state.mtime,
                    "size": state.size,
                    "content_hash": state.content_hash,
                    "doc_id": state.doc_id,
                    "last_processed": state.last_processed
                }
                for path, state in self._file_states.items()
            },
            "updated_at": datetime.now().isoformat()
        }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)


class WatchdogIntegration:
    """
    Real-time file watching using watchdog library.

    Provides live change detection for continuous sync.
    """

    def __init__(
        self,
        tracker: IncrementalTracker,
        on_change: Optional[callable] = None
    ):
        """
        Initialize watchdog integration.

        Args:
            tracker: IncrementalTracker instance
            on_change: Callback for file changes
        """
        self.tracker = tracker
        self.on_change = on_change
        self._observer = None

    def start(self, directory: Path) -> None:
        """Start watching a directory."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class ChangeHandler(FileSystemEventHandler):
                def __init__(handler_self):
                    handler_self.tracker = self.tracker
                    handler_self.callback = self.on_change

                def on_any_event(handler_self, event):
                    if event.is_directory:
                        return

                    path = Path(event.src_path)
                    if path.suffix.lower() not in self.tracker.SUPPORTED_EXTENSIONS:
                        return

                    logger.debug(f"File event: {event.event_type} - {path}")

                    if handler_self.callback:
                        handler_self.callback(event.event_type, path)

            self._observer = Observer()
            self._observer.schedule(ChangeHandler(), str(directory), recursive=True)
            self._observer.start()

            logger.info(f"Started watching: {directory}")

        except ImportError:
            logger.warning("watchdog not installed. Real-time watching disabled.")

    def stop(self) -> None:
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Stopped watching")
