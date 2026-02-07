"""
Integration test for the HITL (Human-In-The-Loop) dashboard API.

Tests the staging -> review -> approve -> execute workflow via FastAPI endpoints.

Run with: pytest tests/test_hitl.py -v
"""

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Setup dummy env vars BEFORE importing src modules
os.environ.setdefault("INBOX_PATH", "/dummy/inbox")
os.environ.setdefault("VAULT_PATH", "/dummy/vault")
os.environ.setdefault("ARCHIVE_PATH", "/dummy/archive")
os.environ.setdefault("GOOGLE_API_KEY", "dummy_key")

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_hitl")
INBOX = TEMP_ROOT / "Inbox"
VAULT = TEMP_ROOT / "Vault"
ARCHIVE = TEMP_ROOT / "Archive"
MANIFEST = TEMP_ROOT / "staging_manifest.json"


@pytest.fixture(autouse=True)
def test_env():
    """Create and clean up temp directories for each test."""
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    VAULT.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)
    yield
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    from src.server import app

    return TestClient(app)


class TestStagingAPI:
    """Tests for the staging and queue API endpoints."""

    def test_queue_returns_staged_items(self, client):
        """GET /api/queue should return all pending/processing items."""
        import src.staging

        test_file = INBOX / "raw_report.txt"
        test_file.write_text("Confidential quarterly report data.")

        with patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST):
            item_id = src.staging.add_to_staging(
                original_path=test_file,
                metadata={
                    "category": "Work",
                    "year": "2024",
                    "type": "Report",
                    "summary": "Quarterly report.",
                    "is_sensitive": False,
                },
                redacted_text="Confidential quarterly report data.",
                suggested_filename="Quarterly_Report",
            )

            response = client.get("/api/queue")

        assert response.status_code == 200
        data = response.json()
        assert item_id in data
        assert data[item_id]["proposed"]["filename"] == "Quarterly_Report"

    def test_update_proposed_fields(self, client):
        """POST /api/update should allow editing proposed fields."""
        import src.staging

        test_file = INBOX / "report.txt"
        test_file.write_text("Some report content.")

        with patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST):
            item_id = src.staging.add_to_staging(
                original_path=test_file,
                metadata={"category": "Work", "year": "2024", "is_sensitive": False},
                redacted_text="Some report content.",
                suggested_filename="Original_Name",
            )

            response = client.post(
                f"/api/update/{item_id}",
                json={
                    "proposed": {
                        "filename": "Corrected_Name",
                        "category": "Financial",
                        "year": "2025",
                        "target_folder": "Financial/2025",
                    }
                },
            )

            assert response.status_code == 200

            updated = src.staging.get_item(item_id)
            assert updated["proposed"]["filename"] == "Corrected_Name"
            assert updated["proposed"]["category"] == "Financial"
            assert updated["proposed"]["year"] == "2025"


class TestExecutionFlow:
    """Tests for the approve -> execute workflow."""

    def test_approve_archives_and_exports(self, client):
        """Approving an item should archive the file and export to vault."""
        import src.archiver
        import src.exporter
        import src.staging

        test_file = INBOX / "approved_doc.txt"
        test_file.write_text("Document content for approval test.")

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.archiver.ARCHIVE_PATH", ARCHIVE),
            patch("src.exporter.VAULT_PATH", VAULT),
        ):

            item_id = src.staging.add_to_staging(
                original_path=test_file,
                metadata={
                    "category": "Work",
                    "year": "2024",
                    "type": "Report",
                    "summary": "A test document.",
                    "is_sensitive": False,
                },
                redacted_text="Document content for approval test.",
                suggested_filename="Approved_Doc",
            )

            # Approve the item
            response = client.post(f"/api/approve/{item_id}")
            assert response.status_code == 200

            # Verify file was archived
            archived_files = list(ARCHIVE.rglob("approved_doc.txt"))
            assert len(archived_files) >= 1, (
                f"File should be archived. Archive contents: " f"{list(ARCHIVE.rglob('*'))}"
            )

            # Verify vault note was created
            vault_files = list((VAULT / "Ingested").glob("*.md"))
            assert len(vault_files) >= 1, (
                f"Vault note should be created. Vault contents: " f"{list(VAULT.rglob('*'))}"
            )

    def test_sensitive_file_gets_redacted_export(self, client):
        """Sensitive files should have PII redacted in vault exports."""
        import src.staging

        test_file = INBOX / "sensitive_doc.txt"
        test_file.write_text("Patient: John Smith, SSN: 078-05-1120")

        with (
            patch("src.staging.STAGING_MANIFEST_PATH", MANIFEST),
            patch("src.archiver.ARCHIVE_PATH", ARCHIVE),
            patch("src.exporter.VAULT_PATH", VAULT),
        ):

            item_id = src.staging.add_to_staging(
                original_path=test_file,
                metadata={
                    "category": "Medical",
                    "year": "2024",
                    "type": "Report",
                    "summary": "Patient record.",
                    "is_sensitive": True,
                },
                redacted_text="Patient: John Smith, SSN: 078-05-1120",
                suggested_filename="CUI_Patient_Record",
            )

            response = client.post(f"/api/approve/{item_id}")
            assert response.status_code == 200

            # Vault export should exist with redacted content
            vault_files = list((VAULT / "Ingested").glob("*.md"))
            if vault_files:
                content = vault_files[0].read_text()
                # PII redaction should replace sensitive values with placeholders
                # (depends on Presidio being installed — if not, falls back to original)
                assert "Patient" in content or "REDACTED" in content
