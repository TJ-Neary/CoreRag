"""
Database backup and restore system for CoreRag.

Provides automated backups and point-in-time recovery.
"""

import json
import logging
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Information about a backup."""

    name: str
    timestamp: str
    size_bytes: int
    path: str
    backup_type: str  # "full", "incremental"
    components: List[str]  # What was backed up
    metadata: Dict


class BackupManager:
    """
    Manage database backups with rotation and verification.

    Usage:
        backup = BackupManager(data_dir="/path/to/data")

        # Create backup
        info = backup.create_backup("daily")

        # List backups
        backups = backup.list_backups()

        # Restore from backup
        backup.restore_backup("backup_20240115_120000")

        # Cleanup old backups
        backup.cleanup_old_backups(keep_count=7)
    """

    def __init__(self, data_dir: Path, backup_dir: Optional[Path] = None, max_backups: int = 10):
        """
        Initialize backup manager.

        Args:
            data_dir: Directory containing data to backup
            backup_dir: Directory to store backups
            max_backups: Maximum number of backups to retain
        """
        self.data_dir = Path(data_dir)
        from src.config import STATE_DIR

        self.backup_dir = backup_dir or (STATE_DIR / "backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.max_backups = max_backups

        # Components to backup
        self.components = [
            "lancedb",  # Vector database
            "state",  # Tracking state (dedup, incremental, checkpoints)
            "config",  # Configuration files
        ]

    def create_backup(
        self,
        backup_name: Optional[str] = None,
        backup_type: str = "full",
        components: Optional[List[str]] = None,
    ) -> BackupInfo:
        """
        Create a new backup.

        Args:
            backup_name: Optional name prefix for the backup
            backup_type: Type of backup ("full" or "incremental")
            components: Specific components to backup (default: all)

        Returns:
            BackupInfo with details about the backup
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{backup_name}_{timestamp}" if backup_name else f"backup_{timestamp}"
        components = components or self.components

        backup_path = self.backup_dir / f"{name}.tar.gz"
        metadata_path = self.backup_dir / f"{name}.json"

        logger.info(f"Creating {backup_type} backup: {name}")

        try:
            # Create tarball
            with tarfile.open(backup_path, "w:gz") as tar:
                for component in components:
                    component_path = self.data_dir / component
                    if component_path.exists():
                        logger.info(f"  Backing up: {component}")
                        tar.add(component_path, arcname=component)

            # Create metadata
            stat = backup_path.stat()
            metadata = {
                "name": name,
                "timestamp": datetime.now().isoformat(),
                "size_bytes": stat.st_size,
                "backup_type": backup_type,
                "components": components,
                "data_dir": str(self.data_dir),
                "checksum": self._compute_checksum(backup_path),
            }

            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            info = BackupInfo(
                name=name,
                timestamp=metadata["timestamp"],
                size_bytes=stat.st_size,
                path=str(backup_path),
                backup_type=backup_type,
                components=components,
                metadata=metadata,
            )

            logger.info(f"Backup complete: {name} " f"({self._format_size(stat.st_size)})")

            # Cleanup old backups
            self.cleanup_old_backups()

            return info

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            # Cleanup partial backup
            if backup_path.exists():
                backup_path.unlink()
            raise

    def restore_backup(
        self,
        backup_name: str,
        target_dir: Optional[Path] = None,
        components: Optional[List[str]] = None,
        verify_checksum: bool = True,
    ) -> bool:
        """
        Restore from a backup.

        Args:
            backup_name: Name of backup to restore
            target_dir: Directory to restore to (default: original data_dir)
            components: Specific components to restore (default: all)
            verify_checksum: Whether to verify backup integrity

        Returns:
            True if successful
        """
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        metadata_path = self.backup_dir / f"{backup_name}.json"

        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_name}")
            return False

        target_dir = target_dir or self.data_dir

        logger.info(f"Restoring backup: {backup_name} to {target_dir}")

        try:
            # Load and verify metadata
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)

                if verify_checksum:
                    current_checksum = self._compute_checksum(backup_path)
                    if current_checksum != metadata.get("checksum"):
                        logger.error("Backup checksum mismatch! Backup may be corrupted.")
                        return False

                components = components or metadata.get("components", [])

            # Create backup of current state before restore
            if target_dir.exists():
                pre_restore_backup = (
                    target_dir.parent
                    / f"{target_dir.name}_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                logger.info(f"Creating pre-restore backup: {pre_restore_backup}")
                shutil.copytree(target_dir, pre_restore_backup)

            # Extract backup
            with tarfile.open(backup_path, "r:gz") as tar:
                # Filter to requested components
                members = tar.getmembers()
                if components:
                    members = [m for m in members if any(m.name.startswith(c) for c in components)]

                for member in members:
                    logger.info(f"  Restoring: {member.name}")

                tar.extractall(target_dir, members=members)

            logger.info(f"Restore complete: {backup_name}")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def list_backups(self) -> List[BackupInfo]:
        """List all available backups."""
        backups = []

        for metadata_path in sorted(self.backup_dir.glob("*.json"), reverse=True):
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)

                backup_path = self.backup_dir / f"{metadata['name']}.tar.gz"
                if backup_path.exists():
                    backups.append(
                        BackupInfo(
                            name=metadata["name"],
                            timestamp=metadata["timestamp"],
                            size_bytes=metadata["size_bytes"],
                            path=str(backup_path),
                            backup_type=metadata.get("backup_type", "full"),
                            components=metadata.get("components", []),
                            metadata=metadata,
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not read backup metadata: {metadata_path}: {e}")

        return backups

    def get_backup_info(self, backup_name: str) -> Optional[BackupInfo]:
        """Get information about a specific backup."""
        metadata_path = self.backup_dir / f"{backup_name}.json"

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path) as f:
                metadata = json.load(f)

            backup_path = self.backup_dir / f"{metadata['name']}.tar.gz"
            if backup_path.exists():
                return BackupInfo(
                    name=metadata["name"],
                    timestamp=metadata["timestamp"],
                    size_bytes=metadata["size_bytes"],
                    path=str(backup_path),
                    backup_type=metadata.get("backup_type", "full"),
                    components=metadata.get("components", []),
                    metadata=metadata,
                )
        except Exception as e:
            logger.warning(f"Could not read backup: {e}")

        return None

    def verify_backup(self, backup_name: str) -> bool:
        """
        Verify backup integrity.

        Args:
            backup_name: Name of backup to verify

        Returns:
            True if backup is valid
        """
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        metadata_path = self.backup_dir / f"{backup_name}.json"

        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_name}")
            return False

        try:
            # Verify can be opened
            with tarfile.open(backup_path, "r:gz") as tar:
                members = tar.getmembers()
                logger.info(f"Backup contains {len(members)} entries")

            # Verify checksum
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)

                current_checksum = self._compute_checksum(backup_path)
                if current_checksum != metadata.get("checksum"):
                    logger.error("Checksum mismatch!")
                    return False

            logger.info(f"Backup verified: {backup_name}")
            return True

        except Exception as e:
            logger.error(f"Backup verification failed: {e}")
            return False

    def cleanup_old_backups(self, keep_count: Optional[int] = None) -> int:
        """
        Remove old backups, keeping the most recent.

        Args:
            keep_count: Number of backups to keep (default: max_backups)

        Returns:
            Number of backups removed
        """
        keep_count = keep_count or self.max_backups
        backups = self.list_backups()

        if len(backups) <= keep_count:
            return 0

        removed = 0
        for backup in backups[keep_count:]:
            try:
                backup_path = Path(backup.path)
                metadata_path = backup_path.with_suffix(".json")

                if backup_path.exists():
                    backup_path.unlink()
                if metadata_path.exists():
                    metadata_path.unlink()

                logger.info(f"Removed old backup: {backup.name}")
                removed += 1

            except Exception as e:
                logger.warning(f"Could not remove backup {backup.name}: {e}")

        return removed

    def delete_backup(self, backup_name: str) -> bool:
        """Delete a specific backup."""
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        metadata_path = self.backup_dir / f"{backup_name}.json"

        try:
            if backup_path.exists():
                backup_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            logger.info(f"Deleted backup: {backup_name}")
            return True
        except Exception as e:
            logger.error(f"Could not delete backup: {e}")
            return False

    @staticmethod
    def _compute_checksum(file_path: Path) -> str:
        """Compute SHA-256 checksum of a file."""
        import hashlib

        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format size in human-readable form."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


class AutoBackup:
    """
    Automatic backup scheduler.

    Runs backups on a schedule in the background.
    """

    def __init__(self, backup_manager: BackupManager, interval_hours: float = 24):
        """
        Initialize auto-backup.

        Args:
            backup_manager: BackupManager instance
            interval_hours: Hours between backups
        """
        self.manager = backup_manager
        self.interval_hours = interval_hours
        self._running = False
        self._thread = None

    def start(self) -> None:
        """Start automatic backups."""
        import threading

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._backup_loop, daemon=True)
        self._thread.start()
        logger.info(f"Auto-backup started (every {self.interval_hours} hours)")

    def stop(self) -> None:
        """Stop automatic backups."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Auto-backup stopped")

    def _backup_loop(self) -> None:
        """Background backup loop."""
        import time

        interval_seconds = self.interval_hours * 3600

        while self._running:
            try:
                self.manager.create_backup("auto")
            except Exception as e:
                logger.error(f"Auto-backup failed: {e}")

            # Sleep in small increments to allow stopping
            for _ in range(int(interval_seconds / 10)):
                if not self._running:
                    break
                time.sleep(10)
