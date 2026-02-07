"""
Tests for sorting rules (user-defined overrides of AI classification).

When a file matches a sorting rule, the rule's target folder takes precedence
over the AI-suggested category/year path.

Run with: pytest tests/test_rules.py -v
"""

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Setup dummy env vars BEFORE importing src modules
os.environ.setdefault("INBOX_PATH", "/dummy/inbox")
os.environ.setdefault("VAULT_PATH", "/dummy/vault")
os.environ.setdefault("ARCHIVE_PATH", "/dummy/archive")
os.environ.setdefault("GOOGLE_API_KEY", "dummy_key")

sys.path.append(os.getcwd())

TEMP_ROOT = Path("temp_test_rules")
ARCHIVE = TEMP_ROOT / "Archive"
INBOX = TEMP_ROOT / "Inbox"
RULES_FILE = TEMP_ROOT / "sorting_rules.yaml"


@pytest.fixture(autouse=True)
def test_env():
    """Create and clean up temp directories and rules file for each test."""
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    INBOX.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)

    # Create a sorting rules file
    rules = {
        "rules": [
            {
                "name": "Special Documents",
                "condition": {"type": "filename", "pattern": "special"},
                "target": "Special/Folder",
            }
        ]
    }
    with open(RULES_FILE, "w") as f:
        yaml.dump(rules, f)

    yield

    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)


class TestSortingRules:
    """Tests for user-defined sorting rules overriding AI classification."""

    def test_matching_file_uses_rule_target(self):
        """File matching a rule pattern should be archived to the rule's target folder."""
        import src.archiver

        file1 = INBOX / "special_doc.txt"
        file1.write_text("Special document content.")

        with (
            patch("src.archiver.ARCHIVE_PATH", ARCHIVE),
            patch("src.archiver.SORTING_RULES_PATH", RULES_FILE),
        ):

            metadata = {"category": "General", "year": "2024"}
            src.archiver.archive_original(file1, metadata)

        expected = ARCHIVE / "Special" / "Folder" / "special_doc.txt"
        assert expected.exists(), (
            f"Rule should override AI classification. "
            f"Expected {expected}, found: {list(ARCHIVE.rglob('*'))}"
        )

    def test_non_matching_file_uses_ai_classification(self):
        """File NOT matching any rule should use AI-suggested category/year."""
        import src.archiver

        file2 = INBOX / "normal.txt"
        file2.write_text("Normal document content.")

        with (
            patch("src.archiver.ARCHIVE_PATH", ARCHIVE),
            patch("src.archiver.SORTING_RULES_PATH", RULES_FILE),
        ):

            metadata = {"category": "General", "year": "2024"}
            src.archiver.archive_original(file2, metadata)

        expected = ARCHIVE / "General" / "2024" / "normal.txt"
        assert expected.exists(), (
            f"AI classification should be used for non-matching files. "
            f"Expected {expected}, found: {list(ARCHIVE.rglob('*'))}"
        )

    def test_no_rules_file_uses_ai(self):
        """When no rules file exists, should fall back to AI classification."""
        import src.archiver

        file3 = INBOX / "any_file.txt"
        file3.write_text("Content without rules.")

        nonexistent_rules = TEMP_ROOT / "nonexistent_rules.yaml"

        with (
            patch("src.archiver.ARCHIVE_PATH", ARCHIVE),
            patch("src.archiver.SORTING_RULES_PATH", nonexistent_rules),
        ):

            metadata = {"category": "Work", "year": "2025"}
            src.archiver.archive_original(file3, metadata)

        expected = ARCHIVE / "Work" / "2025" / "any_file.txt"
        assert expected.exists(), (
            f"Should use AI classification when no rules file exists. "
            f"Expected {expected}, found: {list(ARCHIVE.rglob('*'))}"
        )
