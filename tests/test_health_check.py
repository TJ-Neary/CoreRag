"""
Tests for src/maintenance/health_check.py

Tests the unified health checker with quick and full report modes.
"""

from unittest.mock import MagicMock, patch

from src.maintenance.health_check import (
    HealthChecker,
    TableHealth,
    UnifiedHealthReport,
    check_health,
)


class TestTableHealth:
    """Tests for TableHealth dataclass."""

    def test_defaults(self):
        th = TableHealth(name="test", rows=100)
        assert th.name == "test"
        assert th.rows == 100
        assert th.size_mb == 0.0
        assert th.fragmentation == 0.0


class TestUnifiedHealthReport:
    """Tests for UnifiedHealthReport dataclass."""

    def test_to_dict(self):
        report = UnifiedHealthReport(
            timestamp="2026-01-01T00:00:00",
            status="healthy",
            db_path="/tmp/db",
            total_size_mb=10.5,
            tables=[TableHealth(name="child_chunks", rows=50, size_mb=5.0, fragmentation=0.1)],
            errors=[],
            warnings=["something minor"],
            recommendations=["optimize"],
        )
        d = report.to_dict()
        assert d["status"] == "healthy"
        assert d["total_size_mb"] == 10.5
        assert len(d["tables"]) == 1
        assert d["tables"][0]["name"] == "child_chunks"
        assert d["tables"][0]["fragmentation"] == 0.1
        assert d["warnings"] == ["something minor"]
        assert d["recommendations"] == ["optimize"]

    def test_empty_report(self):
        report = UnifiedHealthReport(
            timestamp="2026-01-01T00:00:00",
            status="healthy",
            db_path="/tmp/db",
        )
        d = report.to_dict()
        assert d["tables"] == []
        assert d["errors"] == []
        assert d["warnings"] == []


class TestHealthCheckerQuickCheck:
    """Tests for HealthChecker.quick_check()."""

    @patch("src.maintenance.health_check.lancedb")
    def test_healthy_database(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

        mock_child = MagicMock()
        mock_child.count_rows.return_value = 100
        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 20

        mock_db.open_table.side_effect = lambda name: (
            mock_child if name == "child_chunks" else mock_parent
        )

        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "healthy"
        assert len(report.tables) == 2
        assert report.errors == []
        assert report.warnings == []

    def test_missing_db_directory(self, tmp_path):
        db_path = tmp_path / "nonexistent"
        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "critical"
        assert any("not found" in e for e in report.errors)

    @patch("src.maintenance.health_check.lancedb")
    def test_no_tables(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = []

        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "critical"
        assert any("No tables" in e for e in report.errors)

    @patch("src.maintenance.health_check.lancedb")
    def test_missing_critical_table(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks"]

        mock_table = MagicMock()
        mock_table.count_rows.return_value = 50
        mock_db.open_table.return_value = mock_table

        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "critical"
        assert any("parent_chunks" in e for e in report.errors)

    @patch("src.maintenance.health_check.lancedb")
    def test_empty_table_warning(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

        mock_child = MagicMock()
        mock_child.count_rows.return_value = 0
        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 10

        mock_db.open_table.side_effect = lambda name: (
            mock_child if name == "child_chunks" else mock_parent
        )

        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "degraded"
        assert any("empty" in w for w in report.warnings)

    @patch("src.maintenance.health_check.lancedb")
    def test_connection_failure(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_lancedb.connect.side_effect = Exception("connection refused")

        checker = HealthChecker(db_path=db_path)
        report = checker.quick_check()

        assert report.status == "critical"
        assert any("connection" in e.lower() for e in report.errors)


class TestHealthCheckerFullReport:
    """Tests for HealthChecker.full_report()."""

    @patch("src.maintenance.health_check.lancedb")
    def test_full_report_enriches_tables(self, mock_lancedb, tmp_path):
        # Set up db directory with table subdirectories
        db_path = tmp_path / "lancedb"
        db_path.mkdir()
        child_dir = db_path / "child_chunks"
        child_dir.mkdir()
        (child_dir / "data.lance").write_bytes(b"x" * 1024)

        parent_dir = db_path / "parent_chunks"
        parent_dir.mkdir()
        (parent_dir / "data.lance").write_bytes(b"x" * 512)

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

        mock_child = MagicMock()
        mock_child.count_rows.return_value = 100
        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 20

        mock_db.open_table.side_effect = lambda name: (
            mock_child if name == "child_chunks" else mock_parent
        )

        checker = HealthChecker(db_path=db_path)
        report = checker.full_report()

        assert report.status == "healthy"
        assert report.total_size_mb > 0
        # Tables should have size info
        for t in report.tables:
            if t.name in ("child_chunks", "parent_chunks"):
                assert t.size_mb >= 0

    def test_full_report_critical_skips_enrichment(self, tmp_path):
        """Full report on missing DB returns critical without enrichment."""
        db_path = tmp_path / "nonexistent"
        checker = HealthChecker(db_path=db_path)
        report = checker.full_report()

        assert report.status == "critical"
        assert report.total_size_mb == 0.0

    @patch("src.maintenance.health_check.lancedb")
    def test_full_report_includes_non_critical_tables(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = [
            "child_chunks",
            "parent_chunks",
            "extra_table",
        ]

        mock_child = MagicMock()
        mock_child.count_rows.return_value = 100
        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 20
        mock_extra = MagicMock()
        mock_extra.count_rows.return_value = 5

        mock_db.open_table.side_effect = lambda name: {
            "child_chunks": mock_child,
            "parent_chunks": mock_parent,
            "extra_table": mock_extra,
        }[name]

        checker = HealthChecker(db_path=db_path)
        report = checker.full_report()

        table_names = [t.name for t in report.tables]
        assert "extra_table" in table_names


class TestCheckHealthConvenience:
    """Tests for the check_health() convenience function."""

    @patch("src.maintenance.health_check.lancedb")
    def test_quick_mode(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

        mock_table = MagicMock()
        mock_table.count_rows.return_value = 10
        mock_db.open_table.return_value = mock_table

        report = check_health(db_path=db_path, full=False)
        assert report.status == "healthy"

    @patch("src.maintenance.health_check.lancedb")
    def test_full_mode(self, mock_lancedb, tmp_path):
        db_path = tmp_path / "lancedb"
        db_path.mkdir()

        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

        mock_table = MagicMock()
        mock_table.count_rows.return_value = 10
        mock_db.open_table.return_value = mock_table

        report = check_health(db_path=db_path, full=True)
        assert report.total_size_mb >= 0
