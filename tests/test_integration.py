"""
Integration test for the ingestion pipeline.

Tests process_document() which orchestrates:
  extract_text -> duplicate_check -> analyze_document -> staging

Run with: pytest tests/test_integration.py -v
"""

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Setup dummy env vars BEFORE importing src modules
os.environ.setdefault("INBOX_PATH", "/dummy/inbox")
os.environ.setdefault("VAULT_PATH", "/dummy/vault")
os.environ.setdefault("ARCHIVE_PATH", "/dummy/archive")
os.environ.setdefault("GOOGLE_API_KEY", "dummy_key")

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_integration")
INBOX = TEMP_ROOT / "Inbox"
MANIFEST = TEMP_ROOT / "staging_manifest.json"


@pytest.fixture(autouse=True)
def test_env():
    """Create and clean up temp directories for each test."""
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    yield
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)


@pytest.mark.integration
class TestProcessDocument:
    """Tests for the process_document pipeline."""

    async def test_stages_file_with_ai_metadata(self):
        """process_document should stage the file with AI-generated metadata."""
        test_file = INBOX / "invoice_2024.txt"
        test_file.write_text("Bill to: John Smith. Amount: $500.")

        mock_metadata = {
            "category": "Financial",
            "year": "2024",
            "type": "Invoice",
            "summary": "An invoice for $500 billed to John Smith.",
            "suggested_name": "Invoice_John_Smith_500",
            "is_sensitive": True,
        }

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.processor.analyze_document", new_callable=AsyncMock) as mock_ai,
            patch("src.processor._dedup") as mock_dedup,
        ):
            # analyze_document now returns (metadata, original_full_text)
            mock_ai.return_value = (mock_metadata, "Bill to: John Smith. Amount: $500.")
            mock_dedup.check_file.return_value = []

            import src.processor

            await src.processor.process_document(test_file)

        # Verify staging manifest was created with correct data
        assert MANIFEST.exists(), "Staging manifest should be created"
        manifest = json.loads(MANIFEST.read_text())
        assert len(manifest) == 1

        item = list(manifest.values())[0]
        assert item["status"] == "pending"
        assert item["metadata"]["category"] == "Financial"
        assert item["metadata"]["year"] == "2024"
        assert item["metadata"]["type"] == "Invoice"
        assert item["metadata"]["summary"] == "An invoice for $500 billed to John Smith."
        # is_sensitive is determined by Presidio PII detection, not LLM metadata.
        # "Bill to: John Smith. Amount: $500." does not trigger high-confidence Presidio detections.
        assert "is_sensitive" in item["metadata"]

        # proposed fields are human-editable copies
        assert item["proposed"]["category"] == "Financial"
        assert item["proposed"]["year"] == "2024"

        # Filename should be sanitized: suggested_name with special chars replaced
        assert "Invoice" in item["proposed"]["filename"]

        # redacted_text now holds the FULL extracted text (redaction happens at commit time)
        assert "John Smith" in item["redacted_text"]
        assert "$500" in item["redacted_text"]

    async def test_sensitive_file_gets_cui_prefix(self):
        """Files flagged as sensitive should get CUI_ prefix on suggested filename."""
        test_file = INBOX / "tax_return.txt"
        test_file.write_text("SSN: 078-05-1120. Income: $75,000.")

        mock_metadata = {
            "category": "Financial",
            "year": "2024",
            "type": "Statement",
            "summary": "A tax return document.",
            "suggested_name": "Tax_Return_2024",
            "is_sensitive": True,
        }

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.processor.analyze_document", new_callable=AsyncMock) as mock_ai,
            patch("src.processor._dedup") as mock_dedup,
        ):
            mock_ai.return_value = (mock_metadata, "SSN: 078-05-1120. Income: $75,000.")
            mock_dedup.check_file.return_value = []

            import src.processor

            await src.processor.process_document(test_file)

        manifest = json.loads(MANIFEST.read_text())
        item = list(manifest.values())[0]
        assert item["proposed"]["filename"].startswith("CUI_")

    async def test_non_sensitive_file_no_cui_prefix(self):
        """Non-sensitive files should NOT get CUI_ prefix."""
        test_file = INBOX / "meeting_notes.txt"
        test_file.write_text("Discussed Q4 roadmap priorities.")

        mock_metadata = {
            "category": "Work",
            "year": "2024",
            "type": "Correspondence",
            "summary": "Meeting notes about Q4 roadmap.",
            "suggested_name": "Q4_Roadmap_Meeting",
            "is_sensitive": False,
        }

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.processor.analyze_document", new_callable=AsyncMock) as mock_ai,
            patch("src.processor._dedup") as mock_dedup,
        ):
            mock_ai.return_value = (mock_metadata, "Discussed Q4 roadmap priorities.")
            mock_dedup.check_file.return_value = []

            import src.processor

            await src.processor.process_document(test_file)

        manifest = json.loads(MANIFEST.read_text())
        item = list(manifest.values())[0]
        assert not item["proposed"]["filename"].startswith("CUI_")

    async def test_empty_text_extraction_sets_error(self):
        """If text extraction returns empty, item should be marked as error."""
        test_file = INBOX / "empty.txt"
        test_file.write_text("")

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.processor.extract_text", return_value=""),
            patch("src.processor._dedup") as mock_dedup,
        ):
            mock_dedup.check_file.return_value = []

            import src.processor

            await src.processor.process_document(test_file)

        manifest = json.loads(MANIFEST.read_text())
        item = list(manifest.values())[0]
        assert item["status"] == "error"

    async def test_duplicate_detected(self):
        """Duplicate files should be flagged in staging metadata."""
        test_file = INBOX / "duplicate_doc.txt"
        test_file.write_text("Some content that already exists.")

        mock_metadata = {
            "category": "Work",
            "year": "2024",
            "type": "Report",
            "summary": "A duplicate document.",
            "suggested_name": "Duplicate_Doc",
            "is_sensitive": False,
        }

        mock_match = MagicMock()
        mock_match.match_type = "content_hash"
        mock_match.similarity = 1.0
        mock_match.file1 = "original_doc.txt"

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.processor.analyze_document", new_callable=AsyncMock) as mock_ai,
            patch("src.processor._dedup") as mock_dedup,
        ):
            mock_ai.return_value = (mock_metadata, "Some content that already exists.")
            mock_dedup.check_file.return_value = [mock_match]

            import src.processor

            await src.processor.process_document(test_file)

        manifest = json.loads(MANIFEST.read_text())
        item = list(manifest.values())[0]
        assert "duplicate" in item
        assert item["duplicate"]["is_duplicate"] is True
        assert item["duplicate"]["match_type"] == "content_hash"
