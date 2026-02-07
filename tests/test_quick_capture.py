"""Tests for the quick-capture REST endpoint."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.server import app

client = TestClient(app)

API_KEY = {"X-API-Key": "test_api_key_not_real"}


class TestQuickCapture:
    def test_quick_capture_missing_text(self):
        response = client.post(
            "/api/v1/quick-capture",
            json={"text": ""},
            headers=API_KEY,
        )
        # Pydantic validation — empty text fails min_length=1
        assert response.status_code == 422

    def test_quick_capture_success(self):
        mock_table = MagicMock()
        mock_db = MagicMock()
        mock_db.open_table.return_value = mock_table

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384]

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client.post(
                "/api/v1/quick-capture",
                json={"text": "Quick note from phone", "tags": ["mobile"]},
                headers=API_KEY,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "captured"
            assert data["document_id"] != ""

    def test_vaults_endpoint(self):
        response = client.get("/api/v1/vaults", headers=API_KEY)
        assert response.status_code == 200
        data = response.json()
        assert "vaults" in data
        assert "default" in data["vaults"]
