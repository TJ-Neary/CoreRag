"""Tests for CatalogManager — SQLite-backed document catalog."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.catalog.catalog_manager import CatalogManager, DocumentRecord, ExportRecord


@pytest.fixture
def catalog(tmp_path: Path) -> CatalogManager:
    """Create a CatalogManager with a temp database."""
    db_path = tmp_path / "_catalog.db"
    return CatalogManager(db_path=db_path)


def _make_record(**overrides: object) -> DocumentRecord:
    """Helper to create a DocumentRecord with sensible defaults."""
    defaults: dict[str, object] = {
        "original_filename": "test_doc.pdf",
        "original_path": "/inbox/test_doc.pdf",
        "category": "notes",
        "year": "2026",
        "tags": ",study,cert-prep,",
        "file_type": "pdf",
        "file_size": 1024,
        "summary": "A test document for unit testing.",
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)  # type: ignore[arg-type]


class TestRegisterAndGet:
    """Test document registration and retrieval."""

    def test_register_and_get(self, catalog: CatalogManager) -> None:
        """Register a document and retrieve it by ID."""
        record = _make_record()
        doc_id = catalog.register(record)

        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.id == doc_id
        assert retrieved.original_filename == "test_doc.pdf"
        assert retrieved.category == "notes"
        assert retrieved.year == "2026"
        assert retrieved.tags == ",study,cert-prep,"
        assert retrieved.file_type == "pdf"
        assert retrieved.file_size == 1024
        assert retrieved.status == "active"
        assert retrieved.ingested_at is not None
        assert retrieved.updated_at is not None

    def test_get_nonexistent(self, catalog: CatalogManager) -> None:
        """Getting a nonexistent document returns None."""
        result = catalog.get("nonexistent-id")
        assert result is None


class TestUpdate:
    """Test document update operations."""

    def test_update(self, catalog: CatalogManager) -> None:
        """Register a document, update its category, verify the change."""
        record = _make_record(category="notes")
        doc_id = catalog.register(record)

        updated = catalog.update(doc_id, category="reference")
        assert updated is True

        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.category == "reference"

    def test_update_nonexistent(self, catalog: CatalogManager) -> None:
        """Updating a nonexistent document returns False."""
        result = catalog.update("nonexistent-id", category="notes")
        assert result is False

    def test_update_no_kwargs(self, catalog: CatalogManager) -> None:
        """Updating with no kwargs returns False."""
        record = _make_record()
        catalog.register(record)
        result = catalog.update(record.id)
        assert result is False

    def test_update_invalid_field(self, catalog: CatalogManager) -> None:
        """Updating with an invalid field raises ValueError."""
        record = _make_record()
        catalog.register(record)
        with pytest.raises(ValueError, match="Invalid fields"):
            catalog.update(record.id, nonexistent_field="value")

    def test_update_sets_updated_at(self, catalog: CatalogManager) -> None:
        """Update should refresh the updated_at timestamp."""
        record = _make_record()
        doc_id = catalog.register(record)

        original = catalog.get(doc_id)
        assert original is not None
        original_updated_at = original.updated_at

        catalog.update(doc_id, summary="Updated summary")

        refreshed = catalog.get(doc_id)
        assert refreshed is not None
        assert refreshed.updated_at != original_updated_at


class TestSearch:
    """Test document search operations."""

    def test_search_by_category(self, catalog: CatalogManager) -> None:
        """Register 3 docs with different categories, search by category."""
        catalog.register(_make_record(category="notes"))
        catalog.register(_make_record(category="reference"))
        catalog.register(_make_record(category="notes"))

        results = catalog.search(category="notes")
        assert len(results) == 2
        assert all(r.category == "notes" for r in results)

    def test_search_by_tag(self, catalog: CatalogManager) -> None:
        """Search by tag substring within comma-delimited tags."""
        catalog.register(_make_record(tags=",sphr-study,cert-prep,"))
        catalog.register(_make_record(tags=",general,"))
        catalog.register(_make_record(tags=",sphr-study,review,"))

        results = catalog.search(tag="sphr-study")
        assert len(results) == 2

    def test_search_by_tag_boundary(self, catalog: CatalogManager) -> None:
        """Tag search should not match partial tag names."""
        catalog.register(_make_record(tags="sphr-study,cert-prep"))
        catalog.register(_make_record(tags="general"))

        # "study" should NOT match "sphr-study" (boundary-aware)
        results = catalog.search(tag="study")
        assert len(results) == 0

        # "sphr-study" should match exactly
        results = catalog.search(tag="sphr-study")
        assert len(results) == 1

    def test_search_by_sensitive(self, catalog: CatalogManager) -> None:
        """Filter sensitive documents only."""
        catalog.register(_make_record(is_sensitive=True))
        catalog.register(_make_record(is_sensitive=False))
        catalog.register(_make_record(is_sensitive=True))

        results = catalog.search(is_sensitive=True)
        assert len(results) == 2
        assert all(r.is_sensitive for r in results)

    def test_search_excludes_deleted_by_default(self, catalog: CatalogManager) -> None:
        """Search should exclude deleted documents by default."""
        record = _make_record()
        doc_id = catalog.register(record)
        catalog.delete(doc_id)

        results = catalog.search(category="notes")
        assert len(results) == 0

    def test_search_includes_deleted_when_requested(self, catalog: CatalogManager) -> None:
        """Search with status='deleted' returns deleted documents."""
        record = _make_record()
        doc_id = catalog.register(record)
        catalog.delete(doc_id)

        results = catalog.search(status="deleted")
        assert len(results) == 1
        assert results[0].id == doc_id

    def test_search_no_filters(self, catalog: CatalogManager) -> None:
        """Search with no filters returns all active documents."""
        catalog.register(_make_record())
        catalog.register(_make_record())

        results = catalog.search()
        assert len(results) == 2


class TestExports:
    """Test export recording and retrieval."""

    def test_record_export(self, catalog: CatalogManager) -> None:
        """Register a doc, record 2 exports, get_exports returns both."""
        record = _make_record()
        doc_id = catalog.register(record)

        catalog.record_export(
            ExportRecord(
                document_id=doc_id,
                destination="main_rag",
                path="/rag/chunks/test_doc",
                redacted=False,
            )
        )
        catalog.record_export(
            ExportRecord(
                document_id=doc_id,
                destination="obsidian",
                path="/vault/Ingested/test_doc.md",
                redacted=True,
            )
        )

        exports = catalog.get_exports(doc_id)
        assert len(exports) == 2

        destinations = {e.destination for e in exports}
        assert destinations == {"main_rag", "obsidian"}

        obsidian_export = next(e for e in exports if e.destination == "obsidian")
        assert obsidian_export.redacted is True
        assert obsidian_export.path == "/vault/Ingested/test_doc.md"
        assert obsidian_export.exported_at is not None

    def test_get_exports_empty(self, catalog: CatalogManager) -> None:
        """get_exports returns empty list for doc with no exports."""
        record = _make_record()
        doc_id = catalog.register(record)

        exports = catalog.get_exports(doc_id)
        assert exports == []


class TestDelete:
    """Test soft-delete operations."""

    def test_delete_soft(self, catalog: CatalogManager) -> None:
        """Delete sets status to 'deleted' but document remains in DB."""
        record = _make_record()
        doc_id = catalog.register(record)

        result = catalog.delete(doc_id)
        assert result is True

        # Document is still in the DB
        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.status == "deleted"

    def test_delete_nonexistent(self, catalog: CatalogManager) -> None:
        """Deleting a nonexistent document returns False."""
        result = catalog.delete("nonexistent-id")
        assert result is False


class TestGetStats:
    """Test aggregate statistics."""

    def test_get_stats(self, catalog: CatalogManager) -> None:
        """get_stats returns counts by category, tag, and sensitivity."""
        catalog.register(_make_record(category="notes", tags=",study,", is_sensitive=False))
        catalog.register(
            _make_record(category="notes", tags=",study,cert-prep,", is_sensitive=True)
        )
        catalog.register(_make_record(category="reference", tags=",cert-prep,", is_sensitive=True))

        # Soft-delete one — should be excluded from active counts
        deleted_rec = _make_record(category="notes", tags=",study,")
        deleted_id = catalog.register(deleted_rec)
        catalog.delete(deleted_id)

        stats = catalog.get_stats()

        assert stats["total_documents"] == 3
        assert stats["by_category"]["notes"] == 2
        assert stats["by_category"]["reference"] == 1
        assert stats["sensitive_count"] == 2
        assert stats["by_tag"]["study"] == 2
        assert stats["by_tag"]["cert-prep"] == 2
        assert stats["by_status"]["active"] == 3
        assert stats["by_status"]["deleted"] == 1
        assert stats["total_exports"] == 0

    def test_get_stats_empty(self, catalog: CatalogManager) -> None:
        """get_stats on empty catalog returns zeroes."""
        stats = catalog.get_stats()
        assert stats["total_documents"] == 0
        assert stats["by_category"] == {}
        assert stats["by_tag"] == {}
        assert stats["sensitive_count"] == 0
        assert stats["total_exports"] == 0


class TestStorageLocationFields:
    """Test storage location, device, and accessibility fields."""

    def test_storage_location_fields(self, catalog: CatalogManager) -> None:
        """Verify storage_location, storage_device, storage_accessible round-trip."""
        record = _make_record(
            storage_location="external_hd",
            storage_device="WD_Passport_2TB",
            storage_accessible=False,
        )
        doc_id = catalog.register(record)

        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.storage_location == "external_hd"
        assert retrieved.storage_device == "WD_Passport_2TB"
        assert retrieved.storage_accessible is False

    def test_storage_defaults(self, catalog: CatalogManager) -> None:
        """Default storage fields are local, no device, accessible."""
        record = _make_record()
        doc_id = catalog.register(record)

        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.storage_location == "local"
        assert retrieved.storage_device is None
        assert retrieved.storage_accessible is True

    def test_update_storage_fields(self, catalog: CatalogManager) -> None:
        """Update storage fields after registration."""
        record = _make_record()
        doc_id = catalog.register(record)

        catalog.update(
            doc_id,
            storage_location="cloud",
            storage_device="iCloud",
            storage_accessible=True,
        )

        retrieved = catalog.get(doc_id)
        assert retrieved is not None
        assert retrieved.storage_location == "cloud"
        assert retrieved.storage_device == "iCloud"
        assert retrieved.storage_accessible is True


class TestFolderTreeAndDevices:
    """Test get_folder_tree() and get_devices() methods."""

    def test_get_folder_tree(self, catalog: CatalogManager) -> None:
        """Folder tree returns category counts and totals."""
        catalog.register(_make_record(category="Work"))
        catalog.register(_make_record(category="Work"))
        catalog.register(_make_record(category="Personal"))
        tree = catalog.get_folder_tree()
        assert tree["total"] == 3
        cats = {c["name"]: c["count"] for c in tree["categories"]}
        assert cats["Work"] == 2
        assert cats["Personal"] == 1

    def test_get_folder_tree_empty(self, catalog: CatalogManager) -> None:
        """Folder tree on empty catalog returns zeroes."""
        tree = catalog.get_folder_tree()
        assert tree["total"] == 0
        assert tree["categories"] == []
        assert tree["no_archive_path"] == 0
        assert tree["offline"] == 0

    def test_get_folder_tree_no_archive(self, catalog: CatalogManager) -> None:
        """Folder tree counts documents with no archive path."""
        catalog.register(_make_record(archive_path=""))
        catalog.register(_make_record(archive_path="/some/path"))
        tree = catalog.get_folder_tree()
        assert tree["no_archive_path"] == 1

    def test_get_devices(self, catalog: CatalogManager) -> None:
        """get_devices groups by device and location with file counts."""
        catalog.register(_make_record(storage_device="WD_Passport", storage_location="external_hd"))
        catalog.register(_make_record(storage_device="WD_Passport", storage_location="external_hd"))
        catalog.register(_make_record(storage_device="NAS_01", storage_location="cloud"))
        devices = catalog.get_devices()
        assert len(devices) == 2
        wd = next(d for d in devices if d["device"] == "WD_Passport")
        assert wd["file_count"] == 2

    def test_get_devices_empty(self, catalog: CatalogManager) -> None:
        """get_devices returns empty list when no devices are set."""
        catalog.register(_make_record())  # no storage_device set
        devices = catalog.get_devices()
        assert devices == []


class TestMigrateToCold:
    """Test migrate_to_cold() cold storage migration."""

    def test_migrate_success(self, catalog: CatalogManager, tmp_path: Path) -> None:
        """Successful migration moves file, updates catalog entry."""
        # Create source file
        archive_dir = tmp_path / "archive" / "Certs"
        archive_dir.mkdir(parents=True)
        src_file = archive_dir / "test.pdf"
        src_file.write_text("content")

        doc_id = catalog.register(_make_record(archive_path=str(src_file)))
        cold_dest = tmp_path / "cold_storage"

        with patch("src.catalog.catalog_manager.ARCHIVE_PATH", tmp_path / "archive"):
            result = catalog.migrate_to_cold([doc_id], "WD_Passport", str(cold_dest))

        assert result["succeeded"] == [doc_id]
        assert result["failed"] == []
        assert (cold_dest / "PKM" / "Certs" / "test.pdf").exists()
        assert not src_file.exists()

        updated = catalog.get(doc_id)
        assert updated is not None
        assert updated.storage_device == "WD_Passport"
        assert updated.storage_location == "external_hd"
        assert not updated.storage_accessible

    def test_migrate_partial_failure(self, catalog: CatalogManager, tmp_path: Path) -> None:
        """Partial failure: successful moves persist, failures are reported."""
        # One file exists, one doesn't
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        src_file = archive_dir / "exists.pdf"
        src_file.write_text("content")

        id1 = catalog.register(_make_record(archive_path=str(src_file)))
        id2 = catalog.register(_make_record(archive_path="/nonexistent/missing.pdf"))
        cold_dest = tmp_path / "cold_storage"

        with patch("src.catalog.catalog_manager.ARCHIVE_PATH", archive_dir):
            result = catalog.migrate_to_cold([id1, id2], "WD_Passport", str(cold_dest))

        assert id1 in result["succeeded"]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == id2
