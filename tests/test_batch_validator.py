"""Tests for src/quality/batch_validator.py — ingestion quality gates."""

from unittest.mock import MagicMock

from src.quality.batch_validator import (
    validate_batch,
    validate_commit,
    validate_database_integrity,
)


class TestValidateBatch:
    def test_empty_manifest(self):
        report = validate_batch({})
        assert report.passed is True
        assert report.total_items == 0

    def test_normal_batch_passes(self):
        manifest = {
            "1": {
                "metadata": {"is_sensitive": False},
                "redacted_text": "x" * 500,
                "original_path": "/tmp/a.pdf",
                "status": "pending",
            },
            "2": {
                "metadata": {"is_sensitive": False},
                "redacted_text": "y" * 500,
                "original_path": "/tmp/b.pdf",
                "status": "pending",
            },
        }
        report = validate_batch(manifest)
        assert report.passed is True
        assert report.sensitive_rate == 0.0

    def test_high_pii_rate_warns(self):
        manifest = {
            str(i): {
                "metadata": {"is_sensitive": True},
                "redacted_text": "x" * 500,
                "original_path": f"/tmp/{i}.pdf",
                "status": "pending",
            }
            for i in range(10)
        }
        report = validate_batch(manifest)
        assert report.passed is False
        assert report.sensitive_rate == 1.0
        assert any("PII rate" in w for w in report.warnings)

    def test_errors_flagged(self):
        manifest = {
            "1": {
                "metadata": {},
                "redacted_text": "",
                "original_path": "/tmp/a.epub",
                "status": "error",
            },
        }
        report = validate_batch(manifest)
        assert report.error_count == 1
        assert report.passed is False

    def test_50_percent_threshold(self):
        """Exactly 50% should NOT trigger (>50% required)."""
        manifest = {
            "1": {
                "metadata": {"is_sensitive": True},
                "redacted_text": "x" * 500,
                "original_path": "/tmp/a.pdf",
                "status": "pending",
            },
            "2": {
                "metadata": {"is_sensitive": False},
                "redacted_text": "y" * 500,
                "original_path": "/tmp/b.pdf",
                "status": "pending",
            },
        }
        report = validate_batch(manifest)
        assert report.passed is True  # 50% is not >50%


class TestValidateCommit:
    def test_skip_rag(self):
        result = validate_commit("test.pdf", skip_rag=True)
        assert result.passed is True

    def test_no_children_fails(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 3
        mock_child = MagicMock()
        mock_child.count_rows.return_value = 0

        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent,
            "child_chunks": mock_child,
        }[name]

        result = validate_commit("test.pdf", db=mock_db)
        assert result.passed is False
        assert result.orphans_cleaned == 3

    def test_healthy_commit_passes(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 2
        mock_child = MagicMock()
        mock_child.count_rows.return_value = 10

        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent,
            "child_chunks": mock_child,
        }[name]

        result = validate_commit("test.pdf", db=mock_db)
        assert result.passed is True
        assert result.parent_count == 2
        assert result.child_count == 10


class TestValidateDatabaseIntegrity:
    def test_no_tables(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        result = validate_database_integrity(db=mock_db)
        assert result["status"] == "skipped"

    def test_no_orphans(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_parent_arrow = MagicMock()
        mock_parent_arrow.column.return_value.to_pylist.return_value = ["a.pdf", "b.pdf"]
        mock_child_arrow = MagicMock()
        mock_child_arrow.column.return_value.to_pylist.return_value = ["a.pdf", "b.pdf"]

        mock_parent_table = MagicMock()
        mock_parent_table.to_arrow.return_value = mock_parent_arrow
        mock_child_table = MagicMock()
        mock_child_table.to_arrow.return_value = mock_child_arrow

        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        result = validate_database_integrity(db=mock_db)
        assert result["status"] == "ok"
        assert result["orphaned_files"] == 0
