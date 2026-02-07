"""
Tests for src/executor.py

Tests the execution phase (archiving, RAG indexing, entity extraction).
"""

from unittest.mock import MagicMock, patch

import pytest


class TestRedactPII:
    """Tests for _redact_pii function."""

    # Note: _redact_pii imports from src.utils.privacy_audit inside the function,
    # so we patch at the source module
    @patch("src.utils.privacy_audit.PrivacyScanner")
    @patch("src.utils.privacy_audit.load_custom_pii_terms")
    @patch("src.utils.privacy_audit.scan_custom_terms")
    def test_redacts_high_confidence_matches(
        self, mock_custom_scan, mock_load_terms, mock_scanner_class
    ):
        """Test that high confidence matches are redacted."""
        from src.executor import _redact_pii

        # Setup mock scanner
        mock_scanner = MagicMock()
        mock_match = MagicMock()
        mock_match.confidence = 0.95
        mock_match.start_pos = 5
        mock_match.end_pos = 16
        mock_match.data_type = MagicMock()
        mock_match.data_type.value = "SSN"

        mock_result = MagicMock()
        mock_result.matches = [mock_match]
        mock_result.privacy_tier = MagicMock()
        mock_result.privacy_tier.value = "SENSITIVE"
        mock_scanner.scan.return_value = mock_result
        mock_scanner_class.return_value = mock_scanner

        mock_load_terms.return_value = []
        mock_custom_scan.return_value = []

        text = "SSN: 123-45-6789 is here"
        result = _redact_pii(text, "test.txt")

        assert "[REDACTED-SSN]" in result
        assert "123-45-6789" not in result

    @patch("src.utils.privacy_audit.PrivacyScanner")
    @patch("src.utils.privacy_audit.load_custom_pii_terms")
    @patch("src.utils.privacy_audit.scan_custom_terms")
    def test_skips_low_confidence_matches(
        self, mock_custom_scan, mock_load_terms, mock_scanner_class
    ):
        """Test that low confidence matches are not redacted."""
        from src.executor import _redact_pii

        mock_scanner = MagicMock()
        mock_match = MagicMock()
        mock_match.confidence = 0.3  # Below threshold
        mock_match.start_pos = 0
        mock_match.end_pos = 10

        mock_result = MagicMock()
        mock_result.matches = [mock_match]
        mock_result.privacy_tier = MagicMock()
        mock_result.privacy_tier.value = "PUBLIC"
        mock_scanner.scan.return_value = mock_result
        mock_scanner_class.return_value = mock_scanner

        mock_load_terms.return_value = []
        mock_custom_scan.return_value = []

        text = "Some text here"
        result = _redact_pii(text, "test.txt")

        # Should return original text (nothing to redact)
        assert result == text

    @patch("src.utils.privacy_audit.PrivacyScanner")
    @patch("src.utils.privacy_audit.load_custom_pii_terms")
    @patch("src.utils.privacy_audit.scan_custom_terms")
    def test_returns_original_on_error(self, mock_custom_scan, mock_load_terms, mock_scanner_class):
        """Test that errors fall back to original text."""
        from src.executor import _redact_pii

        mock_scanner_class.side_effect = Exception("Scanner failed")

        text = "Original text"
        result = _redact_pii(text, "test.txt")

        assert result == text


class TestIndexInRAG:
    """Tests for _index_in_rag function."""

    # Note: _index_in_rag imports these inside the function, so patch at source modules
    @patch("lancedb.connect")
    @patch("src.chunking.parent_child.ParentChildChunker")
    @patch("src.embeddings.embedding_service.create_embedding_service")
    def test_indexes_document_successfully(
        self, mock_embedder_factory, mock_chunker_class, mock_lancedb_connect
    ):
        """Test successful RAG indexing."""
        from src.executor import _index_in_rag

        # Setup mocks
        mock_db = MagicMock()
        mock_lancedb_connect.return_value = mock_db

        mock_chunker = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "parent-1"
        mock_parent.document_id = "doc-1"
        mock_parent.content = "Parent content"
        mock_parent.section_title = "Section 1"
        mock_parent.token_count = 100

        mock_child = MagicMock()
        mock_child.id = "child-1"
        mock_child.parent_id = "parent-1"
        mock_child.document_id = "doc-1"
        mock_child.content = "Child content"
        mock_child.chunk_index = 0

        mock_chunker.chunk_document.return_value = ([mock_parent], [mock_child])
        mock_chunker_class.return_value = mock_chunker

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384]
        mock_embedder_factory.return_value = mock_embedder

        mock_table = MagicMock()
        mock_db.open_table.return_value = mock_table

        _index_in_rag("Test document text", "test.txt", {"category": "Test", "year": "2024"})

        # Verify table operations
        mock_table.add.assert_called()

    @patch("lancedb.connect")
    @patch("src.chunking.parent_child.ParentChildChunker")
    @patch("src.embeddings.embedding_service.create_embedding_service")
    def test_creates_tables_if_not_exist(
        self, mock_embedder_factory, mock_chunker_class, mock_lancedb_connect
    ):
        """Test that tables are created if they don't exist."""
        from src.executor import _index_in_rag

        mock_db = MagicMock()
        mock_lancedb_connect.return_value = mock_db

        # First open_table call fails (table doesn't exist)
        mock_db.open_table.side_effect = [Exception("Table not found"), MagicMock()]

        mock_chunker = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "p1"
        mock_parent.document_id = "d1"
        mock_parent.content = "content"
        mock_parent.section_title = ""
        mock_parent.token_count = 10

        mock_child = MagicMock()
        mock_child.id = "c1"
        mock_child.parent_id = "p1"
        mock_child.document_id = "d1"
        mock_child.content = "content"
        mock_child.chunk_index = 0

        mock_chunker.chunk_document.return_value = ([mock_parent], [mock_child])
        mock_chunker_class.return_value = mock_chunker

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384]
        mock_embedder_factory.return_value = mock_embedder

        _index_in_rag("text", "file.txt", {})

        # Should have tried to create table
        mock_db.create_table.assert_called()

    @patch("lancedb.connect")
    @patch("src.chunking.parent_child.ParentChildChunker")
    @patch("src.embeddings.embedding_service.create_embedding_service")
    def test_handles_empty_chunks(
        self, mock_embedder_factory, mock_chunker_class, mock_lancedb_connect
    ):
        """Test handling when no chunks are created."""
        from src.executor import _index_in_rag

        mock_chunker = MagicMock()
        mock_chunker.chunk_document.return_value = ([], [])
        mock_chunker_class.return_value = mock_chunker

        # Should not raise
        _index_in_rag("short", "file.txt", {})

    @patch("lancedb.connect")
    @patch("src.chunking.parent_child.ParentChildChunker")
    @patch("src.embeddings.embedding_service.create_embedding_service")
    def test_tags_stored_as_comma_delimited(
        self, mock_embedder_factory, mock_chunker_class, mock_lancedb_connect
    ):
        """Test that tags are stored in comma-delimited format."""
        from src.executor import _index_in_rag

        mock_db = MagicMock()
        mock_lancedb_connect.return_value = mock_db

        mock_chunker = MagicMock()
        mock_parent = MagicMock()
        mock_parent.id = "p1"
        mock_parent.document_id = "d1"
        mock_parent.content = "content"
        mock_parent.section_title = ""
        mock_parent.token_count = 10

        mock_child = MagicMock()
        mock_child.id = "c1"
        mock_child.parent_id = "p1"
        mock_child.document_id = "d1"
        mock_child.content = "content"
        mock_child.chunk_index = 0

        mock_chunker.chunk_document.return_value = ([mock_parent], [mock_child])
        mock_chunker_class.return_value = mock_chunker

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1] * 384]
        mock_embedder_factory.return_value = mock_embedder

        mock_table = MagicMock()
        mock_db.open_table.return_value = mock_table

        _index_in_rag("text", "file.txt", {"tags": ["tag1", "tag2"]})

        # Check tags format in add call
        add_call = mock_table.add.call_args[0][0]
        if add_call:  # Parent data
            assert add_call[0]["tags"] == ",tag1,tag2,"


class TestExecuteApprovedItem:
    """Tests for execute_approved_item function."""

    @pytest.fixture
    def mock_item(self, tmp_path):
        """Create a mock approved item."""
        test_file = tmp_path / "test_doc.txt"
        test_file.write_text("Test document content for execution.")

        return {
            "status": "approved",
            "original_path": str(test_file),
            "proposed": {
                "filename": "final_doc.txt",
                "target_folder": "Documents/2024",
                "category": "General",
                "year": "2024",
                "type": "Document",
                "tags": ["test"],
            },
            "metadata": {
                "category": "General",
                "year": "2024",
                "is_sensitive": False,
            },
            "redacted_text": "Test document content for execution.",
        }

    # Note: VersionManager and TagManager are imported inside execute_approved_item(),
    # so we patch them at the source modules
    @patch("src.executor.get_item")
    @patch("src.executor.update_item")
    @patch("src.executor.extract_text")
    @patch("src.executor.archive_to_target")
    @patch("src.executor.export_to_vault")
    @patch("src.executor._index_in_rag")
    @patch("src.executor._extract_entities")
    @patch("src.executor.log_correction")
    @patch("src.utils.versioning.VersionManager")
    @patch("src.utils.tagging.TagManager")
    def test_successful_execution(
        self,
        mock_tm,
        mock_vm,
        mock_log,
        mock_entities,
        mock_rag,
        mock_export,
        mock_archive,
        mock_extract,
        mock_update,
        mock_get,
        mock_item,
    ):
        """Test successful item execution."""
        from src.executor import execute_approved_item

        mock_get.return_value = mock_item
        mock_extract.return_value = "Extracted text"

        result = execute_approved_item("item-123")

        assert result is True
        mock_archive.assert_called_once()
        mock_export.assert_called_once()
        mock_rag.assert_called_once()
        mock_update.assert_called_with("item-123", {"status": "completed"})

    @patch("src.executor.get_item")
    def test_item_not_found(self, mock_get):
        """Test handling when item is not found."""
        from src.executor import execute_approved_item

        mock_get.return_value = None

        result = execute_approved_item("nonexistent")

        assert result is False

    @patch("src.executor.get_item")
    def test_item_not_approved(self, mock_get, mock_item):
        """Test handling when item is not in approved status."""
        from src.executor import execute_approved_item

        mock_item["status"] = "pending"
        mock_get.return_value = mock_item

        result = execute_approved_item("item-123")

        assert result is False

    @patch("src.executor.get_item")
    @patch("src.executor.update_item")
    def test_missing_file_sets_error(self, mock_update, mock_get, mock_item):
        """Test handling when original file is missing."""
        from src.executor import execute_approved_item

        mock_item["original_path"] = "/nonexistent/file.txt"
        mock_get.return_value = mock_item

        result = execute_approved_item("item-123")

        assert result is False
        mock_update.assert_called()
        update_call = mock_update.call_args[0][1]
        assert update_call["status"] == "error"

    @patch("src.executor.get_item")
    @patch("src.executor.update_item")
    @patch("src.executor.extract_text")
    @patch("src.executor.archive_to_target")
    @patch("src.executor.export_to_vault")
    @patch("src.executor._index_in_rag")
    @patch("src.executor._extract_entities")
    @patch("src.executor._redact_pii")
    @patch("src.executor.log_correction")
    @patch("src.utils.versioning.VersionManager")
    @patch("src.utils.tagging.TagManager")
    def test_sensitive_files_get_redacted(
        self,
        mock_tm,
        mock_vm,
        mock_log,
        mock_redact,
        mock_entities,
        mock_rag,
        mock_export,
        mock_archive,
        mock_extract,
        mock_update,
        mock_get,
        mock_item,
    ):
        """Test that sensitive files have PII redacted for exports."""
        from src.executor import execute_approved_item

        mock_item["metadata"]["is_sensitive"] = True
        mock_get.return_value = mock_item
        mock_extract.return_value = "Text with SSN: 123-45-6789"
        mock_redact.return_value = "Text with SSN: [REDACTED-SSN]"

        result = execute_approved_item("item-123")

        assert result is True
        mock_redact.assert_called_once()

    @patch("src.executor.get_item")
    @patch("src.executor.update_item")
    @patch("src.executor.extract_text")
    @patch("src.executor.archive_to_target")
    @patch("src.executor.export_to_vault")
    @patch("src.executor._index_in_rag")
    @patch("src.executor._extract_entities")
    @patch("src.executor.log_correction")
    @patch("src.utils.versioning.VersionManager")
    @patch("src.utils.tagging.TagManager")
    def test_skip_obsidian_flag(
        self,
        mock_tm,
        mock_vm,
        mock_log,
        mock_entities,
        mock_rag,
        mock_export,
        mock_archive,
        mock_extract,
        mock_update,
        mock_get,
        mock_item,
    ):
        """Test that skip_obsidian flag prevents vault export."""
        from src.executor import execute_approved_item

        mock_item["skip_obsidian"] = True
        mock_get.return_value = mock_item
        mock_extract.return_value = "Text"

        execute_approved_item("item-123")

        mock_export.assert_not_called()

    @patch("src.executor.get_item")
    @patch("src.executor.update_item")
    @patch("src.executor.extract_text")
    @patch("src.executor.archive_to_target")
    @patch("src.executor.export_to_vault")
    @patch("src.executor._index_in_rag")
    @patch("src.executor._extract_entities")
    @patch("src.executor.log_correction")
    @patch("src.utils.versioning.VersionManager")
    @patch("src.utils.tagging.TagManager")
    def test_skip_rag_flag(
        self,
        mock_tm,
        mock_vm,
        mock_log,
        mock_entities,
        mock_rag,
        mock_export,
        mock_archive,
        mock_extract,
        mock_update,
        mock_get,
        mock_item,
    ):
        """Test that skip_rag flag prevents RAG indexing."""
        from src.executor import execute_approved_item

        mock_item["skip_rag"] = True
        mock_get.return_value = mock_item
        mock_extract.return_value = "Text"

        execute_approved_item("item-123")

        mock_rag.assert_not_called()
        mock_entities.assert_not_called()
