"""Tests for the GoldenSetManager — analytics-driven golden set management."""

from unittest.mock import MagicMock

import pytest
import yaml

from src.quality.golden_set_manager import GoldenSetManager


@pytest.fixture
def golden_set_path(tmp_path):
    """Create a minimal golden set YAML file."""
    gs_path = tmp_path / "golden_set.yaml"
    data = {
        "metadata": {"version": "1.0"},
        "config": {"top_k": 5, "required_rank": 3, "similarity_threshold": 0.7},
        "queries": [
            {
                "query": "What are the hardware limits?",
                "expected_file": "architecture/HARDWARE_SAFETY.md",
                "expected_in_top": 3,
                "tags": ["architecture"],
            },
            {
                "query": "How does PII detection work?",
                "expected_file": "architecture/PII_DETECTION.md",
                "expected_in_top": 3,
                "tags": ["privacy"],
            },
        ],
    }
    with open(gs_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return gs_path


@pytest.fixture
def mock_analytics():
    """Create mock QueryAnalytics with golden set suggestions."""
    analytics = MagicMock()
    analytics.get_golden_set_suggestions.return_value = [
        {
            "query": "How does chunking work?",
            "expected_file": "architecture/CHUNKING.md",
            "frequency": 5,
            "avg_score": 0.85,
        },
        {
            "query": "What is the search pipeline?",
            "expected_file": "architecture/SEARCH_STACK.md",
            "frequency": 3,
            "avg_score": 0.72,
        },
        {
            "query": "What are the hardware limits?",  # Already exists
            "expected_file": "architecture/HARDWARE_SAFETY.md",
            "frequency": 10,
            "avg_score": 0.90,
        },
    ]
    return analytics


class TestGoldenSetManagerLoad:
    def test_loads_existing_entries(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        assert mgr.entry_count == 2

    def test_handles_missing_file(self, tmp_path):
        mgr = GoldenSetManager(golden_set_path=tmp_path / "nonexistent.yaml")
        assert mgr.entry_count == 0

    def test_list_entries_returns_all(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        entries = mgr.list_entries()
        assert len(entries) == 2
        assert entries[0]["query"] == "What are the hardware limits?"


class TestGoldenSetManagerAddRemove:
    def test_add_entry(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result = mgr.add_entry("New test query", "docs/test.md")
        assert result is True
        assert mgr.entry_count == 3

    def test_add_entry_dedup(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result = mgr.add_entry("What are the hardware limits?", "some/file.md")
        assert result is False
        assert mgr.entry_count == 2

    def test_add_entry_case_insensitive_dedup(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result = mgr.add_entry("WHAT ARE THE HARDWARE LIMITS?", "some/file.md")
        assert result is False

    def test_remove_entry(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result = mgr.remove_entry("What are the hardware limits?")
        assert result is True
        assert mgr.entry_count == 1

    def test_remove_nonexistent(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result = mgr.remove_entry("Nonexistent query")
        assert result is False


class TestGoldenSetManagerSuggestions:
    def test_get_suggestions_filters_existing(self, golden_set_path, mock_analytics):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        suggestions = mgr.get_suggestions()
        # "What are the hardware limits?" already exists — should be filtered
        queries = [s["query"] for s in suggestions]
        assert "What are the hardware limits?" not in queries
        assert "How does chunking work?" in queries
        assert len(suggestions) == 2

    def test_get_suggestions_without_analytics(self, golden_set_path):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=None)
        suggestions = mgr.get_suggestions()
        assert suggestions == []

    def test_approve_suggestion(self, golden_set_path, mock_analytics):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        result = mgr.approve_suggestion("How does chunking work?")
        assert result is True
        assert mgr.entry_count == 3
        # Verify the source is set
        entries = mgr.list_entries(source_filter="auto-approved")
        assert len(entries) == 1
        assert entries[0]["query"] == "How does chunking work?"

    def test_approve_nonexistent_suggestion(self, golden_set_path, mock_analytics):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        result = mgr.approve_suggestion("This query doesn't exist in suggestions")
        assert result is False

    def test_reject_suggestion(self, golden_set_path, mock_analytics, monkeypatch):
        # Use tmp_path for rejections file
        import src.quality.golden_set_manager as gsm

        monkeypatch.setattr(gsm, "_REJECTIONS_PATH", golden_set_path.parent / "rejections.yaml")
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        mgr.reject_suggestion("How does chunking work?")
        # Now get_suggestions should exclude it
        suggestions = mgr.get_suggestions()
        queries = [s["query"] for s in suggestions]
        assert "How does chunking work?" not in queries

    def test_reject_idempotent(self, golden_set_path, monkeypatch):
        import src.quality.golden_set_manager as gsm

        monkeypatch.setattr(gsm, "_REJECTIONS_PATH", golden_set_path.parent / "rejections.yaml")
        mgr = GoldenSetManager(golden_set_path=golden_set_path)
        result1 = mgr.reject_suggestion("some query")
        result2 = mgr.reject_suggestion("some query")
        assert result1 is True
        assert result2 is False


class TestGoldenSetManagerSave:
    def test_save_round_trip(self, golden_set_path, mock_analytics):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        mgr.add_entry("New query", "docs/new.md", tags=["test"])

        # Reload from disk
        mgr2 = GoldenSetManager(golden_set_path=golden_set_path)
        assert mgr2.entry_count == 3
        entries = mgr2.list_entries()
        queries = [e["query"] for e in entries]
        assert "New query" in queries

    def test_list_entries_source_filter(self, golden_set_path, mock_analytics):
        mgr = GoldenSetManager(golden_set_path=golden_set_path, analytics=mock_analytics)
        mgr.approve_suggestion("How does chunking work?")
        manual = mgr.list_entries(source_filter="manual")
        auto = mgr.list_entries(source_filter="auto-approved")
        assert len(manual) == 2
        assert len(auto) == 1
