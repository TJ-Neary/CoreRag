"""
Tests for the Obsidian vault exporter.

Run with: pytest tests/test_exporter.py -v
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


TEMP_ROOT = Path("temp_test_exporter")


@pytest.fixture(autouse=True)
def test_env():
    """Create and clean up temp directories for each test."""
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    TEMP_ROOT.mkdir(parents=True)
    yield
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)


class TestExporter:
    """Tests for export_to_vault function."""

    def test_export_creates_markdown(self):
        vault = TEMP_ROOT / "vault"
        vault.mkdir()
        with patch("src.exporter.VAULT_PATH", vault):
            from src.exporter import export_to_vault
            export_to_vault(
                "Test content for the document body.",
                {"year": "2025", "type": "Report", "category": "Finance", "summary": "A test doc."},
                "test_file.pdf",
            )
        ingested = vault / "Ingested"
        assert ingested.exists()
        md_files = list(ingested.glob("*.md"))
        assert len(md_files) == 1

    def test_export_has_frontmatter(self):
        vault = TEMP_ROOT / "vault"
        vault.mkdir()
        with patch("src.exporter.VAULT_PATH", vault):
            from src.exporter import export_to_vault
            export_to_vault(
                "Body text here.",
                {"year": "2024", "type": "Doc", "category": "HR", "summary": "Summary."},
                "readme.txt",
            )
        md_files = list((vault / "Ingested").glob("*.md"))
        content = md_files[0].read_text()
        assert content.startswith("---")
        assert "category:" in content
        assert "year:" in content

    def test_export_includes_content(self):
        vault = TEMP_ROOT / "vault"
        vault.mkdir()
        with patch("src.exporter.VAULT_PATH", vault):
            from src.exporter import export_to_vault
            export_to_vault(
                "Unique searchable text XYZ123.",
                {"year": "2023", "type": "Note", "category": "Tech", "summary": "Test."},
                "note.md",
            )
        md_files = list((vault / "Ingested").glob("*.md"))
        content = md_files[0].read_text()
        assert "Unique searchable text XYZ123." in content

    def test_export_missing_vault_path(self):
        nonexistent = TEMP_ROOT / "nonexistent_vault"
        with patch("src.exporter.VAULT_PATH", nonexistent):
            from src.exporter import export_to_vault
            # Should not raise, just log error
            export_to_vault(
                "Content.",
                {"year": "2025", "type": "Doc", "category": "Test", "summary": "Test."},
                "file.pdf",
            )
        # No file should be created
        assert not nonexistent.exists()


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_strips_special_chars(self):
        from src.exporter import _sanitize_filename
        assert _sanitize_filename('file<>:"/\\|?*name') == "filename"

    def test_preserves_normal_chars(self):
        from src.exporter import _sanitize_filename
        assert _sanitize_filename("2025 - Report - Budget") == "2025 - Report - Budget"

    def test_strips_leading_trailing_spaces(self):
        from src.exporter import _sanitize_filename
        assert _sanitize_filename("  test  ") == "test"
