"""Tests for P8 SP2 dashboard endpoints: skip, restore, move-errors."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_inbox(tmp_path: Path) -> Path:
    """Create a temporary inbox with test files."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "test_doc.pdf").write_text("test content")
    (inbox / "test_doc2.pdf").write_text("test content 2")
    return inbox


@pytest.fixture
def manifest_store() -> dict:
    """Shared mutable manifest backing store for get_item/update_item/load_manifest mocks."""
    return {}


@pytest.fixture
def client(tmp_inbox: Path, manifest_store: dict) -> TestClient:
    """Test client with mocked INBOX_PATH and staging functions."""
    from src.server import app

    def _get_item(item_id: str) -> dict | None:
        return manifest_store.get(item_id)

    def _update_item(item_id: str, updates: dict) -> bool:
        if item_id not in manifest_store:
            return False
        item = manifest_store[item_id]
        if "proposed" in updates:
            item.setdefault("proposed", {}).update(updates["proposed"])
            remaining = {k: v for k, v in updates.items() if k != "proposed"}
            item.update(remaining)
        else:
            item.update(updates)
        return True

    def _load_manifest() -> dict:
        return dict(manifest_store)

    with (
        patch("src.api.dashboard_routes.config") as mock_config,
        patch("src.api.dashboard_routes.get_item", side_effect=_get_item),
        patch("src.api.dashboard_routes.update_item", side_effect=_update_item),
        patch("src.api.dashboard_routes.load_manifest", side_effect=_load_manifest),
    ):
        mock_config.INBOX_PATH = tmp_inbox
        # Forward other config attributes that the module may reference
        mock_config.STATE_DIR = Path("/tmp/corerag_test_state")
        mock_config.BACKUP_ENABLED = False
        mock_config.DB_PATH = Path("/tmp/corerag_test_db")
        yield TestClient(app)


# ── Skip Tests ────────────────────────────────────────────────────────────────


class TestSkipFile:
    """POST /api/update/{item_id} with action=skip."""

    def test_skip_file(self, client: TestClient, tmp_inbox: Path, manifest_store: dict) -> None:
        """Skip moves the file to _Skipped/ and sets status to 'skipped'."""
        file_path = tmp_inbox / "test_doc.pdf"
        assert file_path.exists()

        manifest_store["item-1"] = {
            "original_path": str(file_path),
            "status": "pending",
            "proposed": {"filename": "test_doc.pdf"},
        }

        resp = client.post("/api/update/item-1", json={"action": "skip"})
        data = resp.json()

        assert resp.status_code == 200
        assert data["status"] == "skipped"
        assert "_Skipped" in data["moved_to"]
        # File moved out of inbox into _Skipped/
        assert not file_path.exists()
        assert (tmp_inbox / "_Skipped" / "test_doc.pdf").exists()
        # Manifest status updated
        assert manifest_store["item-1"]["status"] == "skipped"

    def test_skip_nonexistent_item(self, client: TestClient) -> None:
        """Skip on unknown item_id returns error."""
        resp = client.post("/api/update/no-such-id", json={"action": "skip"})
        assert resp.json()["error"] == "Item not found"

    def test_skip_missing_file(
        self, client: TestClient, tmp_inbox: Path, manifest_store: dict
    ) -> None:
        """Skip succeeds (status update) even if the original file is already gone."""
        manifest_store["item-2"] = {
            "original_path": str(tmp_inbox / "vanished.pdf"),
            "status": "pending",
            "proposed": {"filename": "vanished.pdf"},
        }

        resp = client.post("/api/update/item-2", json={"action": "skip"})
        data = resp.json()

        assert data["status"] == "skipped"
        # Status still flipped despite missing source file
        assert manifest_store["item-2"]["status"] == "skipped"


# ── Restore Tests ─────────────────────────────────────────────────────────────


class TestRestoreFile:
    """POST /api/update/{item_id} with action=restore."""

    def test_restore_file(self, client: TestClient, tmp_inbox: Path, manifest_store: dict) -> None:
        """Restore moves the file back from _Skipped/ to inbox and sets status to 'pending'."""
        file_path = tmp_inbox / "test_doc.pdf"
        assert file_path.exists()

        manifest_store["item-1"] = {
            "original_path": str(file_path),
            "status": "pending",
            "proposed": {"filename": "test_doc.pdf"},
        }

        # Skip first
        client.post("/api/update/item-1", json={"action": "skip"})
        assert not file_path.exists()
        assert (tmp_inbox / "_Skipped" / "test_doc.pdf").exists()

        # Then restore
        resp = client.post("/api/update/item-1", json={"action": "restore"})
        data = resp.json()

        assert resp.status_code == 200
        assert data["status"] == "restored"
        # File back in inbox
        assert file_path.exists()
        assert not (tmp_inbox / "_Skipped" / "test_doc.pdf").exists()
        assert manifest_store["item-1"]["status"] == "pending"

    def test_restore_nonexistent_item(self, client: TestClient) -> None:
        """Restore on unknown item_id returns error."""
        resp = client.post("/api/update/no-such-id", json={"action": "restore"})
        assert resp.json()["error"] == "Item not found"

    def test_restore_collision(
        self, client: TestClient, tmp_inbox: Path, manifest_store: dict
    ) -> None:
        """Restore with name collision adds a timestamp suffix."""
        file_path = tmp_inbox / "test_doc.pdf"
        manifest_store["item-1"] = {
            "original_path": str(file_path),
            "status": "pending",
            "proposed": {"filename": "test_doc.pdf"},
        }

        # Skip the file
        client.post("/api/update/item-1", json={"action": "skip"})
        assert not file_path.exists()

        # Create a NEW file with the same name in the inbox (collision)
        file_path.write_text("new version content")
        assert file_path.exists()

        # Restore — should get a timestamped name
        resp = client.post("/api/update/item-1", json={"action": "restore"})
        data = resp.json()

        assert data["status"] == "restored"
        restored_path = Path(data["path"])
        # Should NOT be the original name (collision avoidance)
        assert restored_path.name != "test_doc.pdf"
        assert restored_path.name.startswith("test_doc_")
        assert restored_path.name.endswith(".pdf")
        assert restored_path.exists()
        # Original collision file untouched
        assert file_path.exists()


# ── Move Errors Tests ─────────────────────────────────────────────────────────


class TestMoveErrors:
    """POST /api/queue/move-errors."""

    def test_move_errors(self, client: TestClient, tmp_inbox: Path, manifest_store: dict) -> None:
        """Error-status files are bulk-moved to _Error/ folder."""
        err_file1 = tmp_inbox / "bad1.pdf"
        err_file2 = tmp_inbox / "bad2.pdf"
        ok_file = tmp_inbox / "good.pdf"
        err_file1.write_text("bad content 1")
        err_file2.write_text("bad content 2")
        ok_file.write_text("good content")

        manifest_store["e1"] = {
            "original_path": str(err_file1),
            "status": "error",
        }
        manifest_store["e2"] = {
            "original_path": str(err_file2),
            "status": "error",
        }
        manifest_store["ok1"] = {
            "original_path": str(ok_file),
            "status": "pending",
        }

        resp = client.post("/api/queue/move-errors")
        data = resp.json()

        assert resp.status_code == 200
        assert data["moved"] == 2
        assert set(data["files"]) == {"bad1.pdf", "bad2.pdf"}
        assert "_Error" in data["destination"]
        # Error files moved
        assert not err_file1.exists()
        assert not err_file2.exists()
        assert (tmp_inbox / "_Error" / "bad1.pdf").exists()
        assert (tmp_inbox / "_Error" / "bad2.pdf").exists()
        # Non-error file untouched
        assert ok_file.exists()

    def test_move_errors_none(self, client: TestClient, manifest_store: dict) -> None:
        """No error files returns moved=0."""
        manifest_store["ok1"] = {
            "original_path": "/tmp/does_not_matter.pdf",
            "status": "pending",
        }

        resp = client.post("/api/queue/move-errors")
        data = resp.json()

        assert data["moved"] == 0
        assert data["files"] == []

    def test_move_errors_missing_file(
        self, client: TestClient, tmp_inbox: Path, manifest_store: dict
    ) -> None:
        """Error items whose source files are already gone are silently skipped."""
        manifest_store["e1"] = {
            "original_path": str(tmp_inbox / "already_gone.pdf"),
            "status": "error",
        }

        resp = client.post("/api/queue/move-errors")
        data = resp.json()

        assert data["moved"] == 0
        assert data["files"] == []


# ── Metadata Update (existing behavior preserved) ────────────────────────────


class TestMetadataUpdate:
    """POST /api/update/{item_id} without action field — legacy metadata update."""

    def test_metadata_update(self, client: TestClient, manifest_store: dict) -> None:
        """Update without action falls through to metadata update."""
        manifest_store["item-1"] = {
            "original_path": "/tmp/test.pdf",
            "status": "pending",
            "proposed": {"filename": "test.pdf", "category": "Unsorted"},
        }

        resp = client.post(
            "/api/update/item-1",
            json={"proposed": {"category": "Technology"}},
        )
        data = resp.json()

        assert data["status"] == "updated"
        assert manifest_store["item-1"]["proposed"]["category"] == "Technology"
