"""
Tests for automatic backup triggers and integrity checks.

Run with: pytest tests/test_backup_triggers.py -v
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestBackupCooldown:
    """Tests for cooldown-based backup logic."""

    def test_should_backup_no_existing(self, temp_dir: Path):
        """Should create backup when no backups exist."""
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import should_backup

        mgr = BackupManager(data_dir=temp_dir, backup_dir=temp_dir / "backups")
        assert should_backup(mgr, cooldown_hours=24, label="test") is True

    def test_should_backup_old_backup(self, temp_dir: Path):
        """Should create backup when last backup exceeds cooldown."""
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import should_backup

        mgr = BackupManager(data_dir=temp_dir, backup_dir=temp_dir / "backups")

        old_backup = MagicMock()
        old_backup.timestamp = (datetime.now() - timedelta(hours=25)).isoformat()

        with patch.object(mgr, "list_backups", return_value=[old_backup]):
            assert should_backup(mgr, cooldown_hours=24, label="test") is True

    def test_should_skip_recent_backup(self, temp_dir: Path):
        """Should skip backup when last backup is within cooldown."""
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import should_backup

        mgr = BackupManager(data_dir=temp_dir, backup_dir=temp_dir / "backups")

        recent_backup = MagicMock()
        recent_backup.timestamp = (datetime.now() - timedelta(minutes=30)).isoformat()

        with patch.object(mgr, "list_backups", return_value=[recent_backup]):
            assert should_backup(mgr, cooldown_hours=24, label="test") is False

    def test_create_backup_if_needed_creates(self, temp_dir: Path):
        """Should create backup when cooldown has elapsed."""
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import create_backup_if_needed

        # Create minimal data so the tarball has content
        (temp_dir / "lancedb").mkdir()
        (temp_dir / "lancedb" / "data.bin").write_text("test")

        mgr = BackupManager(data_dir=temp_dir, backup_dir=temp_dir / "backups", max_backups=5)
        info = create_backup_if_needed(mgr, cooldown_hours=24, backup_name="test")

        assert info is not None
        assert "test" in info.name

    def test_create_backup_if_needed_skips(self, temp_dir: Path):
        """Should skip backup when within cooldown period."""
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import create_backup_if_needed

        (temp_dir / "lancedb").mkdir()
        (temp_dir / "lancedb" / "data.bin").write_text("test")

        mgr = BackupManager(data_dir=temp_dir, backup_dir=temp_dir / "backups", max_backups=5)

        # Create initial backup
        first = mgr.create_backup("initial")
        assert first is not None

        # Immediately try again — should skip
        second = create_backup_if_needed(mgr, cooldown_hours=1, backup_name="test")
        assert second is None


class TestDatabaseIntegrity:
    """Tests for LanceDB integrity checks."""

    def test_missing_database(self, temp_dir: Path):
        """Should detect missing database directory."""
        from src.utils.backup_triggers import check_database_integrity

        result = check_database_integrity(temp_dir / "nonexistent")

        assert result["healthy"] is False
        assert any("not found" in e.lower() for e in result["errors"])

    @patch("lancedb.connect")
    def test_no_tables(self, mock_connect: MagicMock, temp_dir: Path):
        """Should detect empty database."""
        from src.utils.backup_triggers import check_database_integrity

        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        mock_connect.return_value = mock_db

        db_path = temp_dir / "lancedb"
        db_path.mkdir()

        result = check_database_integrity(db_path)

        assert result["healthy"] is False
        assert any("no tables" in e.lower() for e in result["errors"])

    @patch("lancedb.connect")
    def test_missing_critical_table(self, mock_connect: MagicMock, temp_dir: Path):
        """Should detect missing critical tables."""
        from src.utils.backup_triggers import check_database_integrity

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks"]  # Missing parent_chunks
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 50
        mock_db.open_table.return_value = mock_table
        mock_connect.return_value = mock_db

        db_path = temp_dir / "lancedb"
        db_path.mkdir()

        result = check_database_integrity(db_path)

        assert result["healthy"] is False
        assert any("parent_chunks" in e for e in result["errors"])

    @patch("lancedb.connect")
    def test_empty_tables_warns(self, mock_connect: MagicMock, temp_dir: Path):
        """Empty tables should warn but not fail."""
        from src.utils.backup_triggers import check_database_integrity

        mock_table = MagicMock()
        mock_table.count_rows.return_value = 0

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]
        mock_db.open_table.return_value = mock_table
        mock_connect.return_value = mock_db

        db_path = temp_dir / "lancedb"
        db_path.mkdir()

        result = check_database_integrity(db_path)

        assert result["healthy"] is True
        assert len(result["warnings"]) == 2
        assert result["table_counts"]["child_chunks"] == 0

    @patch("lancedb.connect")
    def test_healthy_database(self, mock_connect: MagicMock, temp_dir: Path):
        """Should pass for healthy database."""
        from src.utils.backup_triggers import check_database_integrity

        mock_table = MagicMock()
        mock_table.count_rows.return_value = 100

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]
        mock_db.open_table.return_value = mock_table
        mock_connect.return_value = mock_db

        db_path = temp_dir / "lancedb"
        db_path.mkdir()

        result = check_database_integrity(db_path)

        assert result["healthy"] is True
        assert len(result["errors"]) == 0
        assert len(result["warnings"]) == 0
        assert result["table_counts"]["child_chunks"] == 100
        assert result["table_counts"]["parent_chunks"] == 100
