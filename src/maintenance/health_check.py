"""
Unified Health Check for CoreRag.

Consolidates the fast integrity check (backup_triggers.check_database_integrity)
and the detailed performance analysis (db_optimizer.get_health_report) into a
single HealthChecker with quick and full report modes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import lancedb

logger = logging.getLogger(__name__)


@dataclass
class TableHealth:
    """Health info for a single database table."""

    name: str
    rows: int
    size_mb: float = 0.0
    fragmentation: float = 0.0


@dataclass
class UnifiedHealthReport:
    """Combined health report from all checks."""

    timestamp: str
    status: str  # "healthy", "degraded", "critical"
    db_path: str
    total_size_mb: float = 0.0
    tables: List[TableHealth] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "db_path": self.db_path,
            "total_size_mb": self.total_size_mb,
            "tables": [
                {
                    "name": t.name,
                    "rows": t.rows,
                    "size_mb": t.size_mb,
                    "fragmentation": t.fragmentation,
                }
                for t in self.tables
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class HealthChecker:
    """
    Unified health checker for CoreRag's LanceDB database.

    Combines:
    - Quick integrity check (db exists, critical tables present, rows > 0)
    - Performance analysis (table sizes, fragmentation, recommendations)
    """

    CRITICAL_TABLES = ["child_chunks", "parent_chunks"]

    def __init__(self, db_path: Optional[Path] = None):
        from src.config import DB_PATH

        self.db_path = db_path or DB_PATH

    def quick_check(self) -> UnifiedHealthReport:
        """Fast integrity check suitable for server startup.

        Verifies database exists, critical tables are present, and contain data.
        """
        report = UnifiedHealthReport(
            timestamp=datetime.now().isoformat(),
            status="healthy",
            db_path=str(self.db_path),
        )

        if not self.db_path.exists():
            report.status = "critical"
            report.errors.append(f"Database directory not found: {self.db_path}")
            return report

        try:
            db = lancedb.connect(str(self.db_path))
            table_names = db.table_names()

            if not table_names:
                report.status = "critical"
                report.errors.append("No tables found in database")
                return report

            for table_name in self.CRITICAL_TABLES:
                if table_name not in table_names:
                    report.status = "critical"
                    report.errors.append(f"Critical table missing: {table_name}")
                else:
                    try:
                        table = db.open_table(table_name)
                        count = table.count_rows()
                        report.tables.append(TableHealth(name=table_name, rows=count))
                        if count == 0:
                            report.warnings.append(f"Table {table_name} is empty")
                    except Exception as e:
                        report.status = "critical"
                        report.errors.append(f"Error reading table {table_name}: {e}")

        except Exception as e:
            report.status = "critical"
            report.errors.append(f"Database connection failed: {e}")

        if report.warnings and report.status == "healthy":
            report.status = "degraded"

        return report

    def full_report(self) -> UnifiedHealthReport:
        """Comprehensive health report with performance analysis.

        Includes everything from quick_check plus table sizes,
        fragmentation estimates, and maintenance recommendations.
        """
        report = self.quick_check()

        if report.status == "critical":
            return report

        try:
            db = lancedb.connect(str(self.db_path))

            # Calculate total DB size
            if self.db_path.exists():
                report.total_size_mb = sum(
                    f.stat().st_size for f in self.db_path.rglob("*") if f.is_file()
                ) / (1024 * 1024)

            # Enrich table info with size and fragmentation
            for table_health in report.tables:
                table_path = self.db_path / table_health.name
                if table_path.exists():
                    table_health.size_mb = sum(
                        f.stat().st_size for f in table_path.rglob("*") if f.is_file()
                    ) / (1024 * 1024)

                    # Fragmentation estimate
                    lance_files = list(table_path.glob("*.lance"))
                    fragment_files = list(table_path.glob("data/*.lance"))
                    total_files = len(lance_files) + len(fragment_files)

                    if table_health.rows > 0:
                        expected = max(1, table_health.rows // 100000)
                        frag = min(1.0, max(0.0, (total_files - expected) / max(expected, 1)))
                        table_health.fragmentation = frag

                        if frag > 0.3:
                            report.recommendations.append(
                                f"Table '{table_health.name}' has high fragmentation "
                                f"({frag:.0%}). Run optimize_table()."
                            )

                    if table_health.size_mb > 1000:
                        report.recommendations.append(
                            f"Table '{table_health.name}' is large "
                            f"({table_health.size_mb:.0f} MB). Consider archiving."
                        )

            # Also check non-critical tables
            for table_name in db.table_names():
                if table_name not in [t.name for t in report.tables]:
                    try:
                        table = db.open_table(table_name)
                        count = table.count_rows()
                        table_path = self.db_path / table_name
                        size_mb = 0.0
                        if table_path.exists():
                            size_mb = sum(
                                f.stat().st_size for f in table_path.rglob("*") if f.is_file()
                            ) / (1024 * 1024)
                        report.tables.append(
                            TableHealth(name=table_name, rows=count, size_mb=size_mb)
                        )
                    except Exception:
                        pass

            # Overall recommendation
            avg_frag = (
                sum(t.fragmentation for t in report.tables) / len(report.tables)
                if report.tables
                else 0
            )
            if avg_frag > 0.2:
                report.recommendations.insert(
                    0, "Database fragmentation is elevated. Run optimize_all()."
                )

        except Exception as e:
            report.warnings.append(f"Performance analysis incomplete: {e}")

        if report.warnings and report.status == "healthy":
            report.status = "degraded"

        return report


def check_health(db_path: Optional[Path] = None, full: bool = False) -> UnifiedHealthReport:
    """Convenience function for health checks.

    Args:
        db_path: Path to LanceDB database (uses config default if None)
        full: If True, run full report with performance analysis

    Returns:
        UnifiedHealthReport
    """
    checker = HealthChecker(db_path=db_path)
    return checker.full_report() if full else checker.quick_check()
