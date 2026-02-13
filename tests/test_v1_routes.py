"""Comprehensive tests for Core Memory API v1 routes.

Covers all 7 endpoints: manifest, stats, search, ingest, delete, vaults, quick-capture.
Tests auth, validation, error responses, and happy paths.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.server import app

client = TestClient(app)

API_KEY = {"X-API-Key": "test_api_key_not_real"}


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Test API key authentication across all protected endpoints."""

    def test_manifest_no_auth_required(self):
        """Manifest endpoint should be public."""
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client.get("/api/v1/manifest")
        assert response.status_code == 200

    def test_stats_requires_auth(self):
        response = client.get("/api/v1/stats")
        assert response.status_code == 401

    def test_search_requires_auth(self):
        response = client.post("/api/v1/search", json={"query": "test"})
        assert response.status_code == 401

    def test_ingest_requires_auth(self):
        response = client.post("/api/v1/ingest", json={"content": "test content"})
        assert response.status_code == 401

    def test_delete_requires_auth(self):
        response = client.delete("/api/v1/documents/abc123")
        assert response.status_code == 401

    def test_quick_capture_requires_auth(self):
        response = client.post("/api/v1/quick-capture", json={"text": "test"})
        assert response.status_code == 401

    def test_invalid_api_key(self):
        response = client.get("/api/v1/stats", headers={"X-API-Key": "wrong_key"})
        assert response.status_code == 403

    def test_valid_api_key(self):
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client.get("/api/v1/stats", headers=API_KEY)
        assert response.status_code == 200


# =============================================================================
# Manifest Endpoint
# =============================================================================


class TestManifestEndpoint:
    """Test GET /api/v1/manifest."""

    def test_manifest_returns_schema(self):
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client.get("/api/v1/manifest")

        data = response.json()
        assert data["name"] == "Core Memory"
        assert data["version"] == "1.0"
        assert "capabilities" in data
        assert "schema" in data
        assert "authentication" in data
        assert "stats" in data

    def test_manifest_capabilities_list(self):
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client.get("/api/v1/manifest")

        caps = response.json()["capabilities"]
        assert "search" in caps
        assert "ingest" in caps
        assert "delete" in caps
        assert "stats" in caps
        assert "manifest" in caps

    def test_manifest_with_populated_db(self):
        mock_parent_table = MagicMock()
        mock_child_table = MagicMock()
        mock_child_table.count_rows.return_value = 100

        mock_arrow = MagicMock()
        mock_arrow.column.return_value.to_pylist.return_value = [
            "/doc1.md",
            "/doc2.md",
            "/doc1.md",
        ]
        mock_parent_table.to_arrow.return_value = mock_arrow

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.get("/api/v1/manifest")

        stats = response.json()["stats"]
        assert stats["documents"] == 2  # 2 unique source paths
        assert stats["chunks"] == 100


# =============================================================================
# Stats Endpoint
# =============================================================================


class TestStatsEndpoint:
    """Test GET /api/v1/stats."""

    def test_stats_empty_db(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []

        with patch("lancedb.connect", return_value=mock_db):
            response = client.get("/api/v1/stats", headers=API_KEY)

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 0
        assert data["parent_chunks"] == 0
        assert data["child_chunks"] == 0

    def test_stats_with_data(self):
        mock_parent_table = MagicMock()
        mock_parent_table.count_rows.return_value = 10
        mock_arrow = MagicMock()
        mock_arrow.column.return_value.to_pylist.return_value = [
            "/a.md",
            "/b.md",
            "/a.md",
        ]
        mock_parent_table.to_arrow.return_value = mock_arrow

        mock_child_table = MagicMock()
        mock_child_table.count_rows.return_value = 50

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.get("/api/v1/stats", headers=API_KEY)

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 2
        assert data["parent_chunks"] == 10
        assert data["child_chunks"] == 50

    def test_stats_db_error_graceful(self):
        """Stats should return partial data even if DB queries fail."""
        with patch("lancedb.connect", side_effect=Exception("Connection failed")):
            response = client.get("/api/v1/stats", headers=API_KEY)

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 0


# =============================================================================
# Search Endpoint
# =============================================================================


class TestSearchEndpoint:
    """Test POST /api/v1/search."""

    def test_search_empty_query_validation(self):
        """Pydantic min_length=1 should reject empty query."""
        response = client.post(
            "/api/v1/search",
            json={"query": ""},
            headers=API_KEY,
        )
        assert response.status_code == 422

    def test_search_no_data_indexed(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch("src.embeddings.embedding_service.create_embedding_service"),
        ):
            response = client.post(
                "/api/v1/search",
                json={"query": "test query"},
                headers=API_KEY,
            )

        assert response.status_code == 404
        data = response.json()
        assert "No data indexed" in data["error"]

    def test_search_success(self):
        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = [
            {
                "content": "Found result",
                "source_path": "/docs/test.md",
                "document_id": "abc123",
                "parent_id": "parent1",
                "chunk_index": 0,
                "_distance": 0.25,
                "tags": ",python,test,",
            }
        ]

        mock_child_table = MagicMock()
        mock_child_table.search.return_value = mock_search

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks"]
        mock_db.open_table.return_value = mock_child_table

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 384

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client.post(
                "/api/v1/search",
                json={"query": "test query", "k": 5},
                headers=API_KEY,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["query"] == "test query"
        assert data["results"][0]["content"] == "Found result"
        assert data["results"][0]["score"] == 0.25
        assert "python" in data["results"][0]["tags"]

    def test_search_with_tags(self):
        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.where.return_value = mock_search
        mock_search.to_list.return_value = []

        mock_child_table = MagicMock()
        mock_child_table.search.return_value = mock_search

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks"]
        mock_db.open_table.return_value = mock_child_table

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 384

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client.post(
                "/api/v1/search",
                json={"query": "test", "tags": ["python"]},
                headers=API_KEY,
            )

        assert response.status_code == 200
        # Verify where() was called for tag filtering
        mock_search.where.assert_called_once()

    def test_search_with_hyde(self):
        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []

        mock_child_table = MagicMock()
        mock_child_table.search.return_value = mock_search

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks"]
        mock_db.open_table.return_value = mock_child_table

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 384

        mock_hyde = MagicMock()
        mock_hyde_result = MagicMock()
        mock_hyde_result.hypothetical_document = "expanded query about test"
        mock_hyde.expand.return_value = mock_hyde_result

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
            patch("src.search.hyde.create_hyde_expander", return_value=mock_hyde),
        ):
            response = client.post(
                "/api/v1/search",
                json={"query": "test", "use_hyde": True},
                headers=API_KEY,
            )

        assert response.status_code == 200
        # Embedder should receive the expanded text
        mock_embedder.embed_query.assert_called_once_with("expanded query about test")

    def test_search_k_validation(self):
        """k must be between 1 and 100."""
        response = client.post(
            "/api/v1/search",
            json={"query": "test", "k": 0},
            headers=API_KEY,
        )
        assert response.status_code == 422

        response = client.post(
            "/api/v1/search",
            json={"query": "test", "k": 101},
            headers=API_KEY,
        )
        assert response.status_code == 422

    def test_search_server_error(self):
        """Server errors should return 500."""
        with patch("lancedb.connect", side_effect=Exception("DB crashed")):
            response = client.post(
                "/api/v1/search",
                json={"query": "test"},
                headers=API_KEY,
            )

        assert response.status_code == 500
        data = response.json()
        assert "error" in data


# =============================================================================
# Ingest Endpoint
# =============================================================================


class TestIngestEndpoint:
    """Test POST /api/v1/ingest."""

    def test_ingest_empty_content_validation(self):
        """Pydantic min_length=1 should reject empty content."""
        response = client.post(
            "/api/v1/ingest",
            json={"content": ""},
            headers=API_KEY,
        )
        assert response.status_code == 422

    def test_ingest_success(self):
        mock_table = MagicMock()
        mock_db = MagicMock()
        mock_db.open_table.return_value = mock_table
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384] * 3

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client.post(
                "/api/v1/ingest",
                json={
                    "content": "A sufficiently long document for chunking. " * 50,
                    "source": "test-source",
                    "metadata": {"category": "test", "tags": ["unit-test"]},
                },
                headers=API_KEY,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] != ""
        assert data["source"] == "test-source"
        assert data["chunks_created"] > 0
        assert data["error"] is None

    def test_ingest_content_too_short(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []

        mock_embedder = MagicMock()

        mock_chunker = MagicMock()
        mock_chunker.chunk_document.return_value = ([], [])  # No chunks produced

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
            patch(
                "src.chunking.parent_child.ParentChildChunker",
                return_value=mock_chunker,
            ),
        ):
            response = client.post(
                "/api/v1/ingest",
                json={"content": "tiny"},
                headers=API_KEY,
            )

        assert response.status_code == 422
        data = response.json()
        assert "too short" in data["error"]

    def test_ingest_server_error(self):
        with patch("lancedb.connect", side_effect=Exception("Connection failed")):
            response = client.post(
                "/api/v1/ingest",
                json={"content": "Some content that is long enough. " * 50},
                headers=API_KEY,
            )

        assert response.status_code == 500
        data = response.json()
        assert "error" in data

    def test_ingest_with_metadata(self):
        mock_table = MagicMock()
        mock_db = MagicMock()
        mock_db.open_table.return_value = mock_table
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384] * 3

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client.post(
                "/api/v1/ingest",
                json={
                    "content": "Document with rich metadata. " * 50,
                    "source": "test-app",
                    "metadata": {
                        "category": "notes",
                        "year": "2026",
                        "tags": ["project", "test"],
                        "source_type": "chat",
                    },
                },
                headers=API_KEY,
            )

        assert response.status_code == 200


# =============================================================================
# Delete Endpoint
# =============================================================================


class TestDeleteEndpoint:
    """Test DELETE /api/v1/documents/{document_id}."""

    def test_delete_success(self):
        mock_parent_table = MagicMock()
        mock_parent_table.count_rows.side_effect = [10, 9]  # before and after

        mock_child_table = MagicMock()
        mock_child_table.count_rows.side_effect = [50, 47]  # before and after

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.delete("/api/v1/documents/abc123", headers=API_KEY)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["document_id"] == "abc123"
        assert data["chunks_deleted"] == 4  # 1 parent + 3 children

    def test_delete_not_found(self):
        mock_parent_table = MagicMock()
        mock_parent_table.count_rows.side_effect = [10, 10]  # no change

        mock_child_table = MagicMock()
        mock_child_table.count_rows.side_effect = [50, 50]  # no change

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.delete("/api/v1/documents/nonexistent", headers=API_KEY)

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    def test_delete_server_error(self):
        with patch("lancedb.connect", side_effect=Exception("DB error")):
            response = client.delete("/api/v1/documents/abc123", headers=API_KEY)

        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False

    def test_delete_empty_tables(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []

        with patch("lancedb.connect", return_value=mock_db):
            response = client.delete("/api/v1/documents/abc123", headers=API_KEY)

        assert response.status_code == 404


# =============================================================================
# Document Retrieval Endpoint
# =============================================================================


class TestDocumentEndpoint:
    """Test GET /api/v1/documents/{document_id}."""

    def test_get_document_success(self):
        mock_parent_search = MagicMock()
        mock_parent_search.where.return_value = mock_parent_search
        mock_parent_search.limit.return_value = mock_parent_search
        mock_parent_search.to_list.return_value = [
            {
                "content": "Document content here",
                "source_path": "/docs/test.md",
                "created_at": "2026-01-15T10:00:00",
                "tags": ",python,test,",
            }
        ]

        mock_child_search = MagicMock()
        mock_child_search.where.return_value = mock_child_search
        mock_child_search.limit.return_value = mock_child_search
        mock_child_search.to_list.return_value = [
            {"id": "c1"},
            {"id": "c2"},
            {"id": "c3"},
        ]

        mock_parent_table = MagicMock()
        mock_parent_table.search.return_value = mock_parent_search

        mock_child_table = MagicMock()
        mock_child_table.search.return_value = mock_child_search

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.get("/api/v1/documents/abc123", headers=API_KEY)

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "abc123"
        assert data["source_path"] == "/docs/test.md"
        assert data["parent_chunks"] == 1
        assert data["child_chunks"] == 3
        assert "python" in data["tags"]
        assert data["content_preview"].startswith("Document content")

    def test_get_document_not_found(self):
        mock_search = MagicMock()
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []

        mock_table = MagicMock()
        mock_table.search.return_value = mock_search

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.return_value = mock_table

        with patch("lancedb.connect", return_value=mock_db):
            response = client.get("/api/v1/documents/nonexistent", headers=API_KEY)

        assert response.status_code == 404

    def test_get_document_requires_auth(self):
        response = client.get("/api/v1/documents/abc123")
        assert response.status_code == 401


# =============================================================================
# Bulk Delete Endpoint
# =============================================================================


class TestBulkDeleteEndpoint:
    """Test POST /api/v1/documents/bulk-delete."""

    def test_bulk_delete_success(self):
        mock_parent_table = MagicMock()
        mock_parent_table.count_rows.side_effect = [10, 9, 10, 9]  # 2 docs, before/after each

        mock_child_table = MagicMock()
        mock_child_table.count_rows.side_effect = [50, 47, 50, 48]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.post(
                "/api/v1/documents/bulk-delete",
                json={"document_ids": ["doc1", "doc2"]},
                headers=API_KEY,
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2
        assert data["total_deleted"] > 0

    def test_bulk_delete_empty_list(self):
        """Pydantic min_length=1 should reject empty list."""
        response = client.post(
            "/api/v1/documents/bulk-delete",
            json={"document_ids": []},
            headers=API_KEY,
        )
        assert response.status_code == 422

    def test_bulk_delete_requires_auth(self):
        response = client.post(
            "/api/v1/documents/bulk-delete",
            json={"document_ids": ["doc1"]},
        )
        assert response.status_code == 401

    def test_bulk_delete_partial_failure(self):
        """Some documents found, some not."""
        mock_parent_table = MagicMock()
        mock_parent_table.count_rows.side_effect = [10, 9, 10, 10]  # doc1 deleted, doc2 not found

        mock_child_table = MagicMock()
        mock_child_table.count_rows.side_effect = [50, 47, 50, 50]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]
        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent_table,
            "child_chunks": mock_child_table,
        }[name]

        with patch("lancedb.connect", return_value=mock_db):
            response = client.post(
                "/api/v1/documents/bulk-delete",
                json={"document_ids": ["doc1", "doc2"]},
                headers=API_KEY,
            )

        assert response.status_code == 200
        data = response.json()
        results = data["results"]
        assert results[0]["success"] is True
        assert results[1]["success"] is False


# =============================================================================
# Vaults Endpoint
# =============================================================================


class TestVaultsEndpoint:
    """Test GET /api/v1/vaults."""

    def test_vaults_list(self):
        response = client.get("/api/v1/vaults", headers=API_KEY)
        assert response.status_code == 200
        data = response.json()
        assert "vaults" in data
        assert "default" in data["vaults"]

    def test_vaults_structure(self):
        response = client.get("/api/v1/vaults", headers=API_KEY)
        data = response.json()
        for vault_name, vault_info in data["vaults"].items():
            assert "path" in vault_info
            assert "exists" in vault_info
            assert isinstance(vault_info["exists"], bool)
