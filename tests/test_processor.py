"""
Tests for src/processor.py

Tests the document processing pipeline (text extraction -> AI analysis -> staging).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProcessDocument:
    """Tests for process_document function."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        # Note: add_to_staging and update_item are imported inside process_document(),
        # so we patch them at the source module (src.staging)
        with (
            patch("src.processor.extract_text") as mock_extract,
            patch("src.processor.analyze_document", new_callable=AsyncMock) as mock_analyze,
            patch("src.staging.add_to_staging") as mock_add,
            patch("src.staging.update_item") as mock_update,
            patch("src.processor._pii_scanner") as mock_scanner,
            patch("src.processor._dedup") as mock_dedup,
        ):

            # Configure mocks
            mock_extract.return_value = "This is sample document text for testing."
            mock_analyze.return_value = (
                {
                    "category": "Technology",
                    "year": "2024",
                    "type": "Report",
                    "summary": "A test document about technology.",
                    "suggested_name": "tech_report",
                    "pii_observations": "",
                    "tags": ["tech"],
                },
                "This is sample document text for testing.",
            )
            mock_add.return_value = "test-item-id-123"

            # PII scanner mock
            mock_scan_result = MagicMock()
            mock_scan_result.matches = []
            mock_scanner.scan.return_value = mock_scan_result

            # Dedup mock
            mock_dedup.check_file.return_value = []

            yield {
                "extract": mock_extract,
                "analyze": mock_analyze,
                "add": mock_add,
                "update": mock_update,
                "scanner": mock_scanner,
                "dedup": mock_dedup,
            }

    async def test_successful_processing(self, mock_dependencies, tmp_path):
        """Test successful document processing flow."""
        from src.processor import process_document

        test_file = tmp_path / "test_doc.txt"
        test_file.write_text("Test content")

        await process_document(test_file)

        # Verify staging was created
        mock_dependencies["add"].assert_called_once()

        # Verify status updates
        calls = mock_dependencies["update"].call_args_list
        assert len(calls) >= 2

        # First call should set 'processing'
        assert calls[0][0][1]["status"] == "processing"

        # Last call should set 'pending' with metadata
        final_call = calls[-1][0][1]
        assert final_call["status"] == "pending"
        assert "metadata" in final_call
        assert "proposed" in final_call

    async def test_processing_stages_file_immediately(self, mock_dependencies, tmp_path):
        """Test that file is staged as 'processing' before extraction."""
        from src.processor import process_document

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        await process_document(test_file)

        # add_to_staging should be called before extract_text completes
        mock_dependencies["add"].assert_called_once()

    async def test_extraction_failure_sets_error_status(self, mock_dependencies, tmp_path):
        """Test that extraction failure updates status to error."""
        from src.processor import process_document

        mock_dependencies["extract"].return_value = ""  # Empty = failure

        test_file = tmp_path / "bad_file.txt"
        test_file.write_text("content")

        await process_document(test_file)

        # Should update with error status
        update_calls = mock_dependencies["update"].call_args_list
        error_call = [c for c in update_calls if c[0][1].get("status") == "error"]
        assert len(error_call) > 0

    async def test_pii_detection_sets_is_sensitive(self, mock_dependencies, tmp_path):
        """Test that PII detection sets is_sensitive flag."""
        from src.processor import process_document
        from src.utils.privacy_audit import SensitiveMatch

        # Configure scanner to find PII
        mock_match = MagicMock(spec=SensitiveMatch)
        mock_match.confidence = 0.95
        mock_match.data_type = MagicMock()
        mock_match.data_type.value = "SSN"
        mock_match.context = "SSN: [REDACTED]"

        mock_scan_result = MagicMock()
        mock_scan_result.matches = [mock_match]
        mock_dependencies["scanner"].scan.return_value = mock_scan_result

        test_file = tmp_path / "sensitive_doc.txt"
        test_file.write_text("content with SSN")

        await process_document(test_file)

        # Check final update includes is_sensitive
        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert final_call["metadata"]["is_sensitive"] is True
        assert len(final_call["metadata"]["pii_detections"]) > 0

    async def test_cui_prefix_added_for_sensitive_files(self, mock_dependencies, tmp_path):
        """Test that CUI_ prefix is added to sensitive file names."""
        from src.processor import process_document
        from src.utils.privacy_audit import SensitiveMatch

        # Configure scanner to find PII (SSN triggers is_sensitive)
        mock_match = MagicMock(spec=SensitiveMatch)
        mock_match.confidence = 0.95
        mock_match.data_type = MagicMock()
        mock_match.data_type.value = "SSN"
        mock_match.context = "SSN: [REDACTED]"

        mock_scan_result = MagicMock()
        mock_scan_result.matches = [mock_match]
        mock_dependencies["scanner"].scan.return_value = mock_scan_result

        mock_dependencies["analyze"].return_value = (
            {
                "suggested_name": "employee_list",
                "category": "HR",
                "year": "2024",
                "type": "List",
                "summary": "",
            },
            "text",
        )

        test_file = tmp_path / "employees.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert final_call["proposed"]["filename"].startswith("CUI_")

    async def test_duplicate_detection_adds_info(self, mock_dependencies, tmp_path):
        """Test that duplicate detection info is added to staging."""
        from src.processor import process_document

        # Configure dedup to find match
        mock_match = MagicMock()
        mock_match.match_type = "exact"
        mock_match.similarity = 1.0
        mock_match.file1 = "/path/to/original.txt"
        mock_dependencies["dedup"].check_file.return_value = [mock_match]

        test_file = tmp_path / "duplicate.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert "duplicate" in final_call
        assert final_call["duplicate"]["is_duplicate"] is True

    async def test_llm_tagging_assigns_tags_with_year(self, mock_dependencies, tmp_path):
        """Test that LLM tags are used and year is appended as a tag."""
        from src.processor import process_document

        test_file = tmp_path / "document.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert "tags" in final_call["metadata"]
        assert "tech" in final_call["metadata"]["tags"]
        # Year should be appended as a tag
        assert "2024" in final_call["metadata"]["tags"]

    async def test_llm_tags_string_parsed(self, mock_dependencies, tmp_path):
        """Test that comma-separated tag strings from LLM are parsed to list."""
        from src.processor import process_document

        # Override analyze_document to return tags as a string
        mock_dependencies["analyze"].return_value = (
            {
                "category": "Work",
                "year": "2023",
                "type": "Report",
                "summary": "Test.",
                "suggested_name": "test",
                "pii_observations": "",
                "tags": "hr-training, compliance",
            },
            "text",
        )

        test_file = tmp_path / "doc.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        tags = final_call["metadata"]["tags"]
        assert "hr-training" in tags
        assert "compliance" in tags
        assert "2023" in tags

    async def test_llm_tags_capped_at_five(self, mock_dependencies, tmp_path):
        """Test that tags are capped at 5 total."""
        from src.processor import process_document

        mock_dependencies["analyze"].return_value = (
            {
                "category": "Work",
                "year": "2024",
                "type": "Report",
                "summary": "Test.",
                "suggested_name": "test",
                "pii_observations": "",
                "tags": ["a", "b", "c", "d", "e", "f"],
            },
            "text",
        )

        test_file = tmp_path / "doc.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert len(final_call["metadata"]["tags"]) <= 5

    async def test_low_confidence_pii_not_flagged(self, mock_dependencies, tmp_path):
        """Test that low confidence PII matches don't set is_sensitive."""
        from src.processor import process_document

        # Configure scanner with low confidence match
        mock_match = MagicMock()
        mock_match.confidence = 0.3  # Below 0.70 threshold
        mock_match.data_type = MagicMock()
        mock_match.data_type.value = "NAME"

        mock_scan_result = MagicMock()
        mock_scan_result.matches = [mock_match]
        mock_dependencies["scanner"].scan.return_value = mock_scan_result

        test_file = tmp_path / "doc.txt"
        test_file.write_text("content")

        await process_document(test_file)

        final_call = mock_dependencies["update"].call_args_list[-1][0][1]
        assert final_call["metadata"]["is_sensitive"] is False


class TestIntelligenceHelpers:
    """Tests for intelligence.py context helper functions."""

    @patch("src.intelligence._get_existing_tags", return_value="none yet")
    @patch("src.intelligence._get_archive_folder_tree", return_value="No archive folders yet.")
    async def test_analyze_document_includes_tags_in_response(self, _mock_tree, _mock_tags):
        """Test that analyze_document returns tags from LLM."""
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "Work", "year": "2024", "type": "Guide", '
            '"summary": "Test", "suggested_name": "test", '
            '"pii_observations": "", "tags": ["fitness"]}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Some content")

        assert metadata["tags"] == ["fitness"]

    @patch("src.intelligence._get_existing_tags", return_value="none yet")
    @patch("src.intelligence._get_archive_folder_tree", return_value="No archive folders yet.")
    async def test_analyze_document_defaults_tags_to_empty_list(self, _mock_tree, _mock_tags):
        """Test that tags default to empty list when LLM omits them."""
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "Work", "year": "2024", "type": "Guide", '
            '"summary": "Test", "suggested_name": "test", "pii_observations": ""}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Some content")

        assert metadata["tags"] == []

    def test_get_existing_tags_graceful_fallback(self):
        """Test _get_existing_tags returns 'none yet' on failure."""
        from src.intelligence import _get_existing_tags

        with patch("src.catalog.catalog_manager.CatalogManager", side_effect=Exception("no db")):
            result = _get_existing_tags()
        assert result == "none yet"

    def test_get_archive_folder_tree_graceful_fallback(self):
        """Test _get_archive_folder_tree returns fallback on failure."""
        from src.intelligence import _get_archive_folder_tree

        with patch("src.config.ARCHIVE_PATH") as mock_path:
            mock_path.exists.return_value = False
            result = _get_archive_folder_tree()
        assert result == "No archive folders yet."
