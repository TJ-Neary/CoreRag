"""Tests for dashboard bulk operations endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_manifest():
    """Create a mock staging manifest with pending items."""
    manifest = {
        "item1": {
            "status": "pending",
            "original_path": "/tmp/file1.pdf",
            "proposed": {"filename": "file1", "category": "Medical", "target_folder": "Medical"},
            "metadata": {},
        },
        "item2": {
            "status": "pending",
            "original_path": "/tmp/file2.pdf",
            "proposed": {"filename": "file2", "category": "Medical", "target_folder": "Medical"},
            "metadata": {},
        },
        "item3": {
            "status": "pending",
            "original_path": "/tmp/file3.pdf",
            "proposed": {
                "filename": "file3",
                "category": "Financial",
                "target_folder": "Financial",
            },
            "metadata": {},
        },
        "item4": {
            "status": "completed",
            "original_path": "/tmp/file4.pdf",
            "proposed": {"filename": "file4", "category": "Medical", "target_folder": "Medical"},
            "metadata": {},
        },
    }
    return manifest


class TestBulkApprove:
    def test_bulk_approve_empty_list(self, client):
        response = client.post("/api/bulk-approve", json={"item_ids": []})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    def test_bulk_approve_approves_pending_items(self, client, mock_manifest):
        with (
            patch("src.api.dashboard_routes.get_item") as mock_get,
            patch("src.api.dashboard_routes.update_item"),
            patch("src.api.dashboard_routes.ensure_folder_in_structure"),
            patch("src.api.dashboard_routes.execute_approved_item"),
        ):
            mock_get.side_effect = lambda item_id: mock_manifest.get(item_id)
            response = client.post("/api/bulk-approve", json={"item_ids": ["item1", "item2"]})
            assert response.status_code == 200
            data = response.json()
            assert data["approved"] == 2
            assert len(data["items"]) == 2

    def test_bulk_approve_skips_completed_items(self, client, mock_manifest):
        with (
            patch("src.api.dashboard_routes.get_item") as mock_get,
            patch("src.api.dashboard_routes.update_item"),
            patch("src.api.dashboard_routes.ensure_folder_in_structure"),
            patch("src.api.dashboard_routes.execute_approved_item"),
        ):
            mock_get.side_effect = lambda item_id: mock_manifest.get(item_id)
            response = client.post("/api/bulk-approve", json={"item_ids": ["item1", "item4"]})
            data = response.json()
            # item4 is completed, should be skipped
            assert data["approved"] == 1
            assert "item4" not in data["items"]


class TestApplyToSimilar:
    def test_apply_to_similar_updates_pending(self, client, mock_manifest):
        with (
            patch("src.api.dashboard_routes.load_manifest", return_value=mock_manifest),
            patch("src.api.dashboard_routes.update_item"),
        ):
            response = client.post(
                "/api/apply-to-similar",
                json={"target_folder": "Medical/Insurance", "category": "Medical"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["updated"] == 2  # item1 and item2 are Medical+pending

    def test_apply_to_similar_skips_completed(self, client, mock_manifest):
        with (
            patch("src.api.dashboard_routes.load_manifest", return_value=mock_manifest),
            patch("src.api.dashboard_routes.update_item"),
        ):
            response = client.post(
                "/api/apply-to-similar",
                json={"target_folder": "Medical/New", "category": "Medical"},
            )
            data = response.json()
            # item4 is completed, should not be updated
            assert data["updated"] == 2

    def test_apply_to_similar_all_categories(self, client, mock_manifest):
        with (
            patch("src.api.dashboard_routes.load_manifest", return_value=mock_manifest),
            patch("src.api.dashboard_routes.update_item"),
        ):
            response = client.post(
                "/api/apply-to-similar",
                json={"target_folder": "Everything"},
            )
            data = response.json()
            # All 3 pending items (no category filter)
            assert data["updated"] == 3

    def test_apply_to_similar_missing_folder(self, client):
        response = client.post("/api/apply-to-similar", json={})
        data = response.json()
        assert data["status"] == "error"
