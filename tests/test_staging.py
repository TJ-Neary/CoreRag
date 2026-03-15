"""Tests for src/staging.py — manifest CRUD, batch updates, file locking."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.exceptions import DatabaseError


@pytest.fixture
def temp_manifest(tmp_path):
    """Provide a temporary manifest path and patch the module constant."""
    manifest_path = tmp_path / "staging_manifest.json"
    with patch("src.staging.STAGING_MANIFEST_PATH", manifest_path):
        yield manifest_path


class TestLoadManifest:
    def test_nonexistent_file_returns_empty(self, temp_manifest):
        from src.staging import load_manifest

        assert load_manifest() == {}

    def test_valid_json_loaded(self, temp_manifest):
        from src.staging import load_manifest

        temp_manifest.write_text(json.dumps({"item1": {"status": "pending"}}))
        result = load_manifest()
        assert "item1" in result

    def test_corrupted_json_raises(self, temp_manifest):
        from src.staging import load_manifest

        temp_manifest.write_text("not valid json {{{")
        with pytest.raises(DatabaseError):
            load_manifest()


class TestAddToStaging:
    def test_creates_item_with_pending_status(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("/tmp/test.pdf"),
            metadata={"category": "HR", "year": "2024", "type": "policy", "tags": ["hr"]},
            redacted_text="Document content",
            suggested_filename="2024_HR_Policy",
        )

        manifest = load_manifest()
        assert item_id in manifest
        assert manifest[item_id]["status"] == "pending"
        assert manifest[item_id]["proposed"]["category"] == "HR"

    def test_original_path_is_absolute(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("relative/path.txt"),
            metadata={"category": "Test", "tags": []},
            redacted_text="content",
            suggested_filename="test",
        )

        manifest = load_manifest()
        stored_path = manifest[item_id]["original_path"]
        assert Path(stored_path).is_absolute()

    def test_defaults_for_missing_metadata(self, temp_manifest):
        from src.staging import add_to_staging, load_manifest

        item_id = add_to_staging(
            original_path=Path("/tmp/test.txt"),
            metadata={},
            redacted_text="content",
            suggested_filename="test",
        )

        manifest = load_manifest()
        assert manifest[item_id]["proposed"]["category"] == "Unsorted"
        assert manifest[item_id]["proposed"]["year"] == "Unknown"


class TestUpdateItem:
    def test_update_flat_fields(self, temp_manifest):
        from src.staging import add_to_staging, get_item, update_item

        item_id = add_to_staging(Path("/tmp/t.txt"), {}, "text", "name")
        update_item(item_id, {"status": "approved"})
        assert get_item(item_id)["status"] == "approved"

    def test_update_proposed_deep_merges(self, temp_manifest):
        from src.staging import add_to_staging, get_item, update_item

        item_id = add_to_staging(
            Path("/tmp/t.txt"),
            {"category": "Old", "tags": []},
            "text",
            "name",
        )
        update_item(item_id, {"proposed": {"category": "New"}})
        item = get_item(item_id)
        assert item["proposed"]["category"] == "New"
        assert item["proposed"]["filename"] == "name"  # Not overwritten

    def test_update_nonexistent_returns_false(self, temp_manifest):
        from src.staging import update_item

        assert update_item("nonexistent-id", {"status": "x"}) is False


class TestBatchUpdateItems:
    def test_batch_updates_multiple(self, temp_manifest):
        from src.staging import add_to_staging, batch_update_items, get_item

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        id2 = add_to_staging(Path("/tmp/b.txt"), {}, "b", "b")

        count = batch_update_items(
            {
                id1: {"status": "approved"},
                id2: {"status": "approved"},
            }
        )

        assert count == 2
        assert get_item(id1)["status"] == "approved"
        assert get_item(id2)["status"] == "approved"

    def test_batch_skips_missing_ids(self, temp_manifest):
        from src.staging import add_to_staging, batch_update_items

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        count = batch_update_items(
            {
                id1: {"status": "approved"},
                "nonexistent": {"status": "approved"},
            }
        )
        assert count == 1


class TestGetPendingItems:
    def test_returns_pending_and_processing(self, temp_manifest):
        from src.staging import add_to_staging, get_pending_items, update_item

        id1 = add_to_staging(Path("/tmp/a.txt"), {}, "a", "a")
        id2 = add_to_staging(Path("/tmp/b.txt"), {}, "b", "b")
        id3 = add_to_staging(Path("/tmp/c.txt"), {}, "c", "c")

        update_item(id2, {"status": "processing"})
        update_item(id3, {"status": "completed"})

        pending = get_pending_items()
        assert id1 in pending
        assert id2 in pending
        assert id3 not in pending


class TestConcurrentAccess:
    def test_concurrent_adds_no_corruption(self, temp_manifest):
        """Multiple threads adding items should not corrupt the manifest."""
        from src.staging import add_to_staging, load_manifest

        errors = []

        def add_item(n):
            try:
                add_to_staging(Path(f"/tmp/file_{n}.txt"), {}, f"text_{n}", f"name_{n}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_item, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        manifest = load_manifest()
        assert len(manifest) == 10
