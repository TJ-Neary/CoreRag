"""
Zombie Chunk Reconciliation

Handles the synchronization problem where:
1. Files are deleted/renamed but vectors remain
2. Files are moved but references point to old paths
3. Documents become orphaned (no corresponding file)

This prevents "zombie" references where the LLM answers based on
documents that no longer exist.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Optional, Dict
import os

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Results from a reconciliation run."""
    started_at: datetime
    completed_at: datetime
    total_indexed_paths: int
    valid_paths: int
    zombie_paths: int
    deleted_vectors: int
    errors: List[str]

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


class ZombieReconciler:
    """
    Reconciles vector database with filesystem.

    Detects and removes vectors whose source files no longer exist.

    Usage:
        reconciler = ZombieReconciler(db, watch_directories)
        result = reconciler.run()

        # Or schedule periodic runs
        reconciler.schedule(interval_hours=24)
    """

    def __init__(
        self,
        db,
        watch_directories: List[Path],
        parent_table_name: str = "parent_chunks",
        child_table_name: str = "child_chunks"
    ):
        """
        Initialize reconciler.

        Args:
            db: LanceDB connection
            watch_directories: Directories that should contain source files
            parent_table_name: Name of parent chunks table
            child_table_name: Name of child chunks table
        """
        self.db = db
        self.watch_directories = [Path(d) for d in watch_directories]
        self.parent_table_name = parent_table_name
        self.child_table_name = child_table_name

    def run(self, dry_run: bool = False) -> ReconciliationResult:
        """
        Run reconciliation to find and remove zombie vectors.

        Args:
            dry_run: If True, only report what would be deleted

        Returns:
            ReconciliationResult with statistics
        """
        started_at = datetime.now()
        errors = []

        try:
            # Get all unique source paths from database
            indexed_paths = self._get_indexed_paths()
            total_indexed = len(indexed_paths)

            # Check which paths still exist
            valid_paths = set()
            zombie_paths = set()

            for path_str in indexed_paths:
                path = Path(path_str)

                # Check if path exists and is within watched directories
                if self._path_is_valid(path):
                    valid_paths.add(path_str)
                else:
                    zombie_paths.add(path_str)

            # Delete zombie vectors
            deleted_count = 0
            if zombie_paths:
                if dry_run:
                    logger.info(f"DRY RUN: Would delete {len(zombie_paths)} zombie paths")
                    for zp in list(zombie_paths)[:10]:  # Log first 10
                        logger.info(f"  Would delete: {zp}")
                else:
                    deleted_count = self._delete_zombies(zombie_paths)
                    logger.warning(f"Deleted {deleted_count} zombie vectors from {len(zombie_paths)} paths")

            completed_at = datetime.now()

            return ReconciliationResult(
                started_at=started_at,
                completed_at=completed_at,
                total_indexed_paths=total_indexed,
                valid_paths=len(valid_paths),
                zombie_paths=len(zombie_paths),
                deleted_vectors=deleted_count,
                errors=errors
            )

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Reconciliation failed: {e}")

            return ReconciliationResult(
                started_at=started_at,
                completed_at=datetime.now(),
                total_indexed_paths=0,
                valid_paths=0,
                zombie_paths=0,
                deleted_vectors=0,
                errors=errors
            )

    def _get_indexed_paths(self) -> Set[str]:
        """Get all unique source paths from the database."""
        paths = set()

        try:
            parent_table = self.db.open_table(self.parent_table_name)
            # Query unique document source paths
            df = parent_table.to_pandas()

            if "source_path" in df.columns:
                paths.update(df["source_path"].dropna().unique())
            elif "metadata" in df.columns:
                # Extract from metadata JSON
                import json
                for meta in df["metadata"].dropna():
                    try:
                        m = json.loads(meta) if isinstance(meta, str) else meta
                        if "source_path" in m:
                            paths.add(m["source_path"])
                    except:
                        pass

        except Exception as e:
            logger.warning(f"Error reading parent table: {e}")

        return paths

    def _path_is_valid(self, path: Path) -> bool:
        """Check if a path is valid (exists and in watched directories)."""
        # First check: does file exist?
        if not path.exists():
            return False

        # Second check: is it in a watched directory?
        for watch_dir in self.watch_directories:
            try:
                path.relative_to(watch_dir)
                return True
            except ValueError:
                continue

        # Path exists but not in any watched directory
        logger.warning(f"Path exists but outside watched directories: {path}")
        return False

    def _delete_zombies(self, zombie_paths: Set[str]) -> int:
        """Delete vectors for zombie paths."""
        deleted = 0

        try:
            parent_table = self.db.open_table(self.parent_table_name)
            child_table = self.db.open_table(self.child_table_name)

            for path in zombie_paths:
                try:
                    # Get parent IDs for this path
                    parent_df = parent_table.to_pandas()

                    # Find matching parents
                    if "source_path" in parent_df.columns:
                        matching = parent_df[parent_df["source_path"] == path]
                    else:
                        # Check metadata
                        import json
                        mask = parent_df["metadata"].apply(
                            lambda m: json.loads(m).get("source_path") == path
                            if isinstance(m, str) else m.get("source_path") == path
                        )
                        matching = parent_df[mask]

                    parent_ids = matching["id"].tolist()

                    if parent_ids:
                        # Delete children first
                        for pid in parent_ids:
                            child_table.delete(f"parent_id = '{pid}'")

                        # Delete parents
                        for pid in parent_ids:
                            parent_table.delete(f"id = '{pid}'")

                        deleted += len(parent_ids)
                        logger.info(f"Deleted {len(parent_ids)} chunks for: {path}")

                except Exception as e:
                    logger.error(f"Error deleting chunks for {path}: {e}")

        except Exception as e:
            logger.error(f"Error during zombie deletion: {e}")

        return deleted


class FileRenameHandler:
    """
    Handles file renames by updating vector metadata.

    Treat rename as: Delete old path + Add new path
    This ensures clean metadata without ghost references.
    """

    def __init__(self, db, reconciler: ZombieReconciler):
        self.db = db
        self.reconciler = reconciler

    def handle_rename(self, old_path: Path, new_path: Path) -> bool:
        """
        Handle a file rename.

        Strategy: Delete vectors for old path, trigger re-index for new path.
        This is cleaner than trying to update metadata.

        Args:
            old_path: Original file path
            new_path: New file path

        Returns:
            True if handled successfully
        """
        try:
            # Step 1: Delete old vectors
            result = self.reconciler.run(dry_run=False)

            # Step 2: Trigger re-indexing of new path
            # (This would be done by the ingestion system)
            logger.info(f"Renamed: {old_path} -> {new_path}")
            logger.info(f"Deleted {result.deleted_vectors} old vectors")
            logger.info("New path needs re-indexing")

            return True

        except Exception as e:
            logger.error(f"Failed to handle rename: {e}")
            return False


def schedule_reconciliation(
    db,
    watch_directories: List[Path],
    interval_hours: int = 24,
    run_immediately: bool = False
) -> None:
    """
    Schedule periodic reconciliation.

    Args:
        db: LanceDB connection
        watch_directories: Directories to watch
        interval_hours: Hours between runs
        run_immediately: Run once immediately on start
    """
    import threading
    import time

    reconciler = ZombieReconciler(db, watch_directories)

    def run_periodically():
        while True:
            try:
                result = reconciler.run()
                logger.info(
                    f"Reconciliation complete: "
                    f"{result.zombie_paths} zombies found, "
                    f"{result.deleted_vectors} vectors deleted"
                )
            except Exception as e:
                logger.error(f"Scheduled reconciliation failed: {e}")

            time.sleep(interval_hours * 3600)

    if run_immediately:
        reconciler.run()

    thread = threading.Thread(target=run_periodically, daemon=True)
    thread.start()

    logger.info(f"Reconciliation scheduled every {interval_hours} hours")
