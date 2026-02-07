"""
LanceDB optimization and maintenance utilities.

Handles database hygiene to prevent fragmentation and latency creep:
- Compact fragmented data files
- Rebuild indexes for optimal query performance
- Clean up orphaned data
- Monitor database health

Designed to run as a scheduled weekly job.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Check for LanceDB availability
LANCEDB_AVAILABLE = False
try:
    import lancedb

    LANCEDB_AVAILABLE = True
except ImportError:
    logger.warning("LanceDB not installed. Install with: pip install lancedb")


@dataclass
class OptimizationResult:
    """Result of a database optimization run."""

    table_name: str
    timestamp: str
    success: bool
    original_size_mb: float
    optimized_size_mb: float
    space_saved_mb: float
    duration_seconds: float
    rows_before: int
    rows_after: int
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """Database health report."""

    db_path: str
    timestamp: str
    total_size_mb: float
    tables: List[Dict[str, Any]]
    fragmentation_estimate: float  # 0-1, higher = more fragmented
    recommendations: List[str] = field(default_factory=list)


class LanceDBOptimizer:
    """
    Optimize and maintain LanceDB databases.

    Features:
    - Table compaction to reduce fragmentation
    - Index rebuilding for query performance
    - Orphan cleanup for deleted data
    - Health monitoring and reporting
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        backup_before_optimize: bool = True,
        backup_dir: Optional[Path] = None,
    ):
        """
        Initialize optimizer.

        Args:
            db_path: Path to LanceDB database
            backup_before_optimize: Create backup before optimization
            backup_dir: Directory for backups
        """
        if not LANCEDB_AVAILABLE:
            raise ImportError("LanceDB required. Install: pip install lancedb")

        from src.config import DB_PATH, STATE_DIR

        self.db_path = db_path or DB_PATH
        self.backup_before_optimize = backup_before_optimize
        self.backup_dir = backup_dir or STATE_DIR / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self._db: Optional[lancedb.DBConnection] = None

    def connect(self) -> lancedb.DBConnection:
        """Connect to the database."""
        if self._db is None:
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    def optimize_table(self, table_name: str) -> OptimizationResult:
        """
        Optimize a single table.

        Performs:
        - Compaction of data files
        - Cleanup of deleted rows
        - Index optimization

        Args:
            table_name: Name of table to optimize

        Returns:
            OptimizationResult with details
        """
        import time

        start_time = time.time()
        timestamp = datetime.now().isoformat()

        try:
            db = self.connect()

            # Check if table exists
            if table_name not in db.table_names():
                return OptimizationResult(
                    table_name=table_name,
                    timestamp=timestamp,
                    success=False,
                    original_size_mb=0,
                    optimized_size_mb=0,
                    space_saved_mb=0,
                    duration_seconds=0,
                    rows_before=0,
                    rows_after=0,
                    error=f"Table '{table_name}' not found",
                )

            # Get original stats
            table = db.open_table(table_name)
            rows_before = table.count_rows()
            original_size = self._get_table_size(table_name)

            logger.info(
                f"Optimizing table '{table_name}': {rows_before} rows, {original_size:.2f} MB"
            )

            # Create backup if enabled
            if self.backup_before_optimize:
                self._backup_table(table_name)

            # Perform optimization
            # LanceDB's optimize() compacts fragments and removes deleted data
            table.optimize()

            # Get new stats
            rows_after = table.count_rows()
            optimized_size = self._get_table_size(table_name)

            duration = time.time() - start_time
            space_saved = original_size - optimized_size

            logger.info(
                f"Optimization complete: {space_saved:.2f} MB saved "
                f"({(space_saved/original_size*100):.1f}% reduction)"
            )

            return OptimizationResult(
                table_name=table_name,
                timestamp=timestamp,
                success=True,
                original_size_mb=original_size,
                optimized_size_mb=optimized_size,
                space_saved_mb=space_saved,
                duration_seconds=duration,
                rows_before=rows_before,
                rows_after=rows_after,
            )

        except Exception as e:
            logger.error(f"Optimization failed for '{table_name}': {e}")
            return OptimizationResult(
                table_name=table_name,
                timestamp=timestamp,
                success=False,
                original_size_mb=0,
                optimized_size_mb=0,
                space_saved_mb=0,
                duration_seconds=time.time() - start_time,
                rows_before=0,
                rows_after=0,
                error=str(e),
            )

    def optimize_all(self) -> List[OptimizationResult]:
        """
        Optimize all tables in the database.

        Returns:
            List of OptimizationResult for each table
        """
        db = self.connect()
        results = []

        for table_name in db.table_names():
            logger.info(f"Optimizing table: {table_name}")
            result = self.optimize_table(table_name)
            results.append(result)

        return results

    def get_health_report(self) -> HealthReport:
        """
        Generate a health report for the database.

        Returns:
            HealthReport with analysis and recommendations
        """
        db = self.connect()
        timestamp = datetime.now().isoformat()

        total_size = self._get_db_size()
        tables = []
        recommendations = []

        for table_name in db.table_names():
            table = db.open_table(table_name)
            table_size = self._get_table_size(table_name)
            row_count = table.count_rows()

            # Estimate fragmentation by checking file count vs expected
            fragment_estimate = self._estimate_fragmentation(table_name)

            table_info = {
                "name": table_name,
                "rows": row_count,
                "size_mb": table_size,
                "fragmentation": fragment_estimate,
            }
            tables.append(table_info)

            # Generate recommendations
            if fragment_estimate > 0.3:
                recommendations.append(
                    f"Table '{table_name}' has high fragmentation ({fragment_estimate:.0%}). "
                    "Consider running optimize_table()."
                )

            if table_size > 1000:  # > 1GB
                recommendations.append(
                    f"Table '{table_name}' is large ({table_size:.0f} MB). "
                    "Consider partitioning or archiving old data."
                )

        # Overall fragmentation
        avg_fragmentation = sum(t["fragmentation"] for t in tables) / len(tables) if tables else 0

        if avg_fragmentation > 0.2:
            recommendations.insert(0, "Database fragmentation is elevated. Run optimize_all().")

        return HealthReport(
            db_path=str(self.db_path),
            timestamp=timestamp,
            total_size_mb=total_size,
            tables=tables,
            fragmentation_estimate=avg_fragmentation,
            recommendations=recommendations,
        )

    def _get_table_size(self, table_name: str) -> float:
        """Get size of a table in MB."""
        table_path = self.db_path / table_name
        if table_path.exists():
            total = sum(f.stat().st_size for f in table_path.rglob("*") if f.is_file())
            return total / (1024 * 1024)
        return 0.0

    def _get_db_size(self) -> float:
        """Get total database size in MB."""
        if self.db_path.exists():
            total = sum(f.stat().st_size for f in self.db_path.rglob("*") if f.is_file())
            return total / (1024 * 1024)
        return 0.0

    def _estimate_fragmentation(self, table_name: str) -> float:
        """
        Estimate fragmentation level (0-1).

        Higher values indicate more fragmentation.
        """
        table_path = self.db_path / table_name

        if not table_path.exists():
            return 0.0

        # Count data files (lance files)
        lance_files = list(table_path.glob("*.lance"))
        fragment_files = list(table_path.glob("data/*.lance"))

        total_files = len(lance_files) + len(fragment_files)

        # Heuristic: more than ~10 files per 100K rows suggests fragmentation
        try:
            db = self.connect()
            table = db.open_table(table_name)
            row_count = table.count_rows()

            if row_count == 0:
                return 0.0

            expected_files = max(1, row_count // 100000)
            fragmentation = min(1.0, (total_files - expected_files) / max(expected_files, 1))
            return max(0.0, fragmentation)

        except Exception:
            return 0.0

    def _backup_table(self, table_name: str) -> Optional[Path]:
        """Create a backup of a table."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"{table_name}_{timestamp}"

            table_path = self.db_path / table_name
            if table_path.exists():
                shutil.copytree(table_path, backup_path)
                logger.info(f"Backup created: {backup_path}")
                return backup_path

        except Exception as e:
            logger.warning(f"Backup failed: {e}")

        return None

    def cleanup_old_backups(self, max_age_days: int = 30) -> int:
        """
        Remove backups older than specified days.

        Returns:
            Number of backups removed
        """
        import time

        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        removed = 0

        for backup in self.backup_dir.iterdir():
            if backup.is_dir() and backup.stat().st_mtime < cutoff:
                shutil.rmtree(backup)
                logger.info(f"Removed old backup: {backup}")
                removed += 1

        return removed


class MaintenanceScheduler:
    """
    Schedule regular maintenance tasks.

    Designed to be run as a cron job or launchd service.
    """

    def __init__(
        self,
        optimizer: Optional[LanceDBOptimizer] = None,
        state_file: Optional[Path] = None,
    ):
        """
        Initialize scheduler.

        Args:
            optimizer: LanceDBOptimizer instance
            state_file: File to track last run times
        """
        self.optimizer = optimizer or LanceDBOptimizer()
        from src.config import STATE_DIR

        self.state_file = state_file or STATE_DIR / "maintenance_state.json"

    def should_run_optimization(self, min_hours_between: int = 168) -> bool:
        """Check if enough time has passed since last optimization."""
        state = self._load_state()
        last_run = state.get("last_optimization")

        if not last_run:
            return True

        from datetime import datetime, timedelta

        last_dt = datetime.fromisoformat(last_run)
        return datetime.now() - last_dt > timedelta(hours=min_hours_between)

    def run_weekly_maintenance(self) -> Dict[str, Any]:
        """
        Run weekly maintenance tasks.

        Returns:
            Summary of actions taken
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "optimization_results": [],
            "health_report": None,
            "backups_cleaned": 0,
        }

        # Optimize all tables
        logger.info("Running weekly optimization...")
        results = self.optimizer.optimize_all()
        summary["optimization_results"] = [
            {
                "table": r.table_name,
                "success": r.success,
                "space_saved_mb": r.space_saved_mb,
            }
            for r in results
        ]

        # Generate health report
        report = self.optimizer.get_health_report()
        summary["health_report"] = {
            "total_size_mb": report.total_size_mb,
            "fragmentation": report.fragmentation_estimate,
            "recommendations": report.recommendations,
        }

        # Clean old backups
        summary["backups_cleaned"] = self.optimizer.cleanup_old_backups()

        # Update state
        self._save_state({"last_optimization": datetime.now().isoformat()})

        logger.info(f"Maintenance complete: {summary}")
        return summary

    def _load_state(self) -> Dict[str, Any]:
        """Load scheduler state."""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save scheduler state."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)


# Convenience functions
def optimize_database(db_path: Optional[Path] = None) -> List[OptimizationResult]:
    """
    Quick optimization of all tables in database.

    Args:
        db_path: Path to LanceDB database

    Returns:
        List of optimization results
    """
    optimizer = LanceDBOptimizer(db_path=db_path)
    return optimizer.optimize_all()


def check_database_health(db_path: Optional[Path] = None) -> HealthReport:
    """
    Quick health check of database.

    Args:
        db_path: Path to LanceDB database

    Returns:
        Health report with recommendations
    """
    optimizer = LanceDBOptimizer(db_path=db_path)
    return optimizer.get_health_report()


def run_maintenance() -> Dict[str, Any]:
    """
    Run full maintenance suite.

    Designed to be called from cron:
        0 3 * * 0 python -c "from src.maintenance.db_optimizer import run_maintenance; run_maintenance()"

    Returns:
        Maintenance summary
    """
    scheduler = MaintenanceScheduler()
    return scheduler.run_weekly_maintenance()
