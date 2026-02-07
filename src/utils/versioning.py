"""
Version history and changelog for documents.

Tracks document changes over time.
"""

import difflib
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DocumentVersion:
    """A single version of a document."""

    version_id: str
    document_id: str
    version_number: int
    content_hash: str
    created_at: str
    changed_by: str  # "user", "system", "sync"
    change_type: str  # "create", "update", "delete", "restore"
    change_summary: str
    metadata: Dict = field(default_factory=dict)

    # Content stored separately to save space
    content_stored: bool = False


@dataclass
class VersionDiff:
    """Difference between two versions."""

    from_version: int
    to_version: int
    additions: int
    deletions: int
    diff_lines: List[str]
    summary: str


class VersionManager:
    """
    Track document version history.

    Stores content snapshots and computes diffs.
    """

    MAX_VERSIONS_PER_DOC = 50  # Keep last 50 versions

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize version manager.

        Args:
            state_dir: Directory for version storage
        """
        from src.config import STATE_DIR

        self.state_dir = state_dir or STATE_DIR / "versions"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._versions: Dict[str, List[DocumentVersion]] = {}
        self._load_metadata()

    def create_version(
        self,
        document_id: str,
        content: str,
        changed_by: str = "user",
        change_type: str = "update",
        change_summary: str = "",
        metadata: Optional[Dict] = None,
    ) -> DocumentVersion:
        """
        Create a new version of a document.

        Args:
            document_id: Document ID
            content: Current content
            changed_by: Who made the change
            change_type: Type of change
            change_summary: Description of change
            metadata: Additional metadata

        Returns:
            Created version
        """
        # Get current version number
        versions = self._versions.get(document_id, [])
        version_number = len(versions) + 1

        # Compute content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check if content actually changed
        if versions:
            last_version = versions[-1]
            if last_version.content_hash == content_hash:
                logger.debug(f"No change in document {document_id}, skipping version")
                return last_version

        # Auto-generate summary if not provided
        if not change_summary and versions:
            last_content = self._load_content(document_id, versions[-1].version_id)
            if last_content:
                change_summary = self._generate_summary(last_content, content)

        version = DocumentVersion(
            version_id=f"v{version_number}_{content_hash}",
            document_id=document_id,
            version_number=version_number,
            content_hash=content_hash,
            created_at=datetime.now().isoformat(),
            changed_by=changed_by,
            change_type=change_type,
            change_summary=change_summary or f"Version {version_number}",
            metadata=metadata or {},
            content_stored=True,
        )

        # Store content
        self._save_content(document_id, version.version_id, content)

        # Add to version list
        if document_id not in self._versions:
            self._versions[document_id] = []
        self._versions[document_id].append(version)

        # Prune old versions
        self._prune_versions(document_id)

        # Save metadata
        self._save_metadata()

        logger.info(f"Created version {version_number} for document {document_id}")

        return version

    def get_versions(self, document_id: str) -> List[DocumentVersion]:
        """Get all versions of a document."""
        return self._versions.get(document_id, [])

    def get_version(self, document_id: str, version_number: int) -> Optional[DocumentVersion]:
        """Get a specific version."""
        versions = self._versions.get(document_id, [])
        for v in versions:
            if v.version_number == version_number:
                return v
        return None

    def get_latest_version(self, document_id: str) -> Optional[DocumentVersion]:
        """Get the latest version of a document."""
        versions = self._versions.get(document_id, [])
        return versions[-1] if versions else None

    def get_content(self, document_id: str, version_number: int) -> Optional[str]:
        """Get content of a specific version."""
        version = self.get_version(document_id, version_number)
        if version:
            return self._load_content(document_id, version.version_id)
        return None

    def get_diff(
        self, document_id: str, from_version: int, to_version: int
    ) -> Optional[VersionDiff]:
        """
        Get diff between two versions.

        Args:
            document_id: Document ID
            from_version: Starting version number
            to_version: Ending version number

        Returns:
            VersionDiff if both versions exist
        """
        from_content = self.get_content(document_id, from_version)
        to_content = self.get_content(document_id, to_version)

        if from_content is None or to_content is None:
            return None

        # Compute unified diff
        from_lines = from_content.splitlines(keepends=True)
        to_lines = to_content.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                from_lines, to_lines, fromfile=f"v{from_version}", tofile=f"v{to_version}"
            )
        )

        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return VersionDiff(
            from_version=from_version,
            to_version=to_version,
            additions=additions,
            deletions=deletions,
            diff_lines=diff,
            summary=f"+{additions}/-{deletions} lines",
        )

    def restore_version(self, document_id: str, version_number: int) -> Optional[DocumentVersion]:
        """
        Restore a previous version (creates new version with old content).

        Args:
            document_id: Document ID
            version_number: Version to restore

        Returns:
            New version created from restored content
        """
        content = self.get_content(document_id, version_number)
        if content is None:
            logger.error(f"Version {version_number} not found for {document_id}")
            return None

        return self.create_version(
            document_id=document_id,
            content=content,
            changed_by="user",
            change_type="restore",
            change_summary=f"Restored from version {version_number}",
        )

    def get_history(self, document_id: str, limit: int = 10) -> List[Dict]:
        """
        Get formatted version history.

        Args:
            document_id: Document ID
            limit: Maximum entries to return

        Returns:
            List of version info dicts
        """
        versions = self._versions.get(document_id, [])[-limit:]

        history = []
        for v in reversed(versions):
            history.append(
                {
                    "version": v.version_number,
                    "date": v.created_at,
                    "changed_by": v.changed_by,
                    "type": v.change_type,
                    "summary": v.change_summary,
                }
            )

        return history

    def _generate_summary(self, old_content: str, new_content: str) -> str:
        """Generate change summary from diff."""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        if len(new_lines) > len(old_lines):
            return f"Added {len(new_lines) - len(old_lines)} lines"
        elif len(new_lines) < len(old_lines):
            return f"Removed {len(old_lines) - len(new_lines)} lines"
        else:
            # Count changed lines
            changed = sum(1 for o, n in zip(old_lines, new_lines) if o != n)
            return f"Modified {changed} lines"

    def _save_content(self, document_id: str, version_id: str, content: str) -> None:
        """Save version content to disk."""
        doc_dir = self.state_dir / document_id
        doc_dir.mkdir(exist_ok=True)

        content_file = doc_dir / f"{version_id}.txt"
        content_file.write_text(content)

    def _load_content(self, document_id: str, version_id: str) -> Optional[str]:
        """Load version content from disk."""
        content_file = self.state_dir / document_id / f"{version_id}.txt"
        if content_file.exists():
            return content_file.read_text()
        return None

    def _prune_versions(self, document_id: str) -> None:
        """Remove old versions beyond limit."""
        versions = self._versions.get(document_id, [])

        if len(versions) > self.MAX_VERSIONS_PER_DOC:
            # Remove oldest versions
            to_remove = versions[: -self.MAX_VERSIONS_PER_DOC]
            self._versions[document_id] = versions[-self.MAX_VERSIONS_PER_DOC :]

            # Delete content files
            for v in to_remove:
                content_file = self.state_dir / document_id / f"{v.version_id}.txt"
                if content_file.exists():
                    content_file.unlink()

            logger.debug(f"Pruned {len(to_remove)} old versions from {document_id}")

    def _load_metadata(self) -> None:
        """Load version metadata from disk."""
        metadata_file = self.state_dir / "versions.json"
        if metadata_file.exists():
            try:
                with open(metadata_file) as f:
                    data = json.load(f)

                for doc_id, versions in data.get("documents", {}).items():
                    self._versions[doc_id] = [DocumentVersion(**v) for v in versions]

            except Exception as e:
                logger.error(f"Failed to load version metadata: {e}")

    def _save_metadata(self) -> None:
        """Save version metadata to disk."""
        metadata_file = self.state_dir / "versions.json"

        data = {
            "documents": {
                doc_id: [
                    {
                        "version_id": v.version_id,
                        "document_id": v.document_id,
                        "version_number": v.version_number,
                        "content_hash": v.content_hash,
                        "created_at": v.created_at,
                        "changed_by": v.changed_by,
                        "change_type": v.change_type,
                        "change_summary": v.change_summary,
                        "metadata": v.metadata,
                        "content_stored": v.content_stored,
                    }
                    for v in versions
                ]
                for doc_id, versions in self._versions.items()
            },
            "updated_at": datetime.now().isoformat(),
        }

        with open(metadata_file, "w") as f:
            json.dump(data, f, indent=2)
