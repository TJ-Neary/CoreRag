"""
Automatic backup triggers for CoreRag.

Provides cooldown-based backup creation and LanceDB integrity checking.
Used by server startup and pre-commit hooks.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.backup import BackupInfo, BackupManager

logger = logging.getLogger(__name__)


def should_backup(manager: BackupManager, cooldown_hours: float, label: str = "auto") -> bool:
    """Check if a backup should be created based on cooldown period."""
    backups = manager.list_backups()

    if not backups:
        logger.info("No existing backups found, creating %s backup", label)
        return True

    latest = backups[0]  # list_backups returns newest-first
    latest_time = datetime.fromisoformat(latest.timestamp)
    age_hours = (datetime.now() - latest_time).total_seconds() / 3600

    if age_hours >= cooldown_hours:
        logger.info(
            "Last backup is %.1fh old (threshold: %.0fh), creating %s backup",
            age_hours,
            cooldown_hours,
            label,
        )
        return True

    logger.debug(
        "Last backup is %.1fh old, skipping %s backup (threshold: %.0fh)",
        age_hours,
        label,
        cooldown_hours,
    )
    return False


def create_backup_if_needed(
    manager: BackupManager, cooldown_hours: float, backup_name: str = "auto"
) -> Optional[BackupInfo]:
    """Create a backup if the cooldown period has elapsed. Never raises."""
    if not should_backup(manager, cooldown_hours, backup_name):
        return None

    try:
        info = manager.create_backup(backup_name=backup_name, backup_type="full")
        logger.info("Backup created: %s (%.1f MB)", info.name, info.size_bytes / (1024**2))
        return info
    except Exception:
        logger.warning("Backup creation failed", exc_info=True)
        return None


def check_database_integrity(db_path: Path) -> dict[str, Any]:
    """
    Fast integrity check on LanceDB.

    Verifies database exists, critical tables are present,
    and tables contain data. Returns structured results.
    """
    result: dict[str, Any] = {
        "healthy": True,
        "errors": [],
        "warnings": [],
        "table_counts": {},
    }

    if not db_path.exists():
        result["healthy"] = False
        result["errors"].append(f"Database directory not found: {db_path}")
        return result

    try:
        import lancedb

        db = lancedb.connect(str(db_path))
        table_names = db.table_names()

        if not table_names:
            result["healthy"] = False
            result["errors"].append("No tables found in database")
            return result

        critical_tables = ["child_chunks", "parent_chunks"]
        for table_name in critical_tables:
            if table_name not in table_names:
                result["healthy"] = False
                result["errors"].append(f"Critical table missing: {table_name}")
            else:
                try:
                    table = db.open_table(table_name)
                    count = table.count_rows()
                    result["table_counts"][table_name] = count
                    if count == 0:
                        result["warnings"].append(f"Table {table_name} is empty")
                except Exception as e:
                    result["healthy"] = False
                    result["errors"].append(f"Error reading table {table_name}: {e}")

    except Exception as e:
        result["healthy"] = False
        result["errors"].append(f"Database connection failed: {e}")

    return result
