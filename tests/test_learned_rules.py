"""Tests for LearnedRulesManager — pattern learning from user corrections."""

import json

import pytest
import yaml

from src.classification.learned_rules import LearnedRulesManager


@pytest.fixture
def corrections_file(tmp_path):
    """Create a corrections log with repeated patterns."""
    corrections = [
        {
            "timestamp": "2025-01-01T10:00:00",
            "corrections": {
                "target_folder": {"ai": "Medical", "human": "Medical/Insurance"},
                "category": {"ai": "Medical", "human": "Insurance"},
            },
        },
        {
            "timestamp": "2025-01-02T10:00:00",
            "corrections": {
                "target_folder": {"ai": "Medical", "human": "Medical/Insurance"},
                "category": {"ai": "Medical", "human": "Insurance"},
            },
        },
        {
            "timestamp": "2025-01-03T10:00:00",
            "corrections": {
                "target_folder": {"ai": "Work", "human": "Work/Projects"},
            },
        },
        {
            "timestamp": "2025-01-04T10:00:00",
            "corrections": {
                "pii_override": {"ai": "not_sensitive", "human": "sensitive"},
                "category": {"human": "Legal"},
            },
        },
        {
            "timestamp": "2025-01-05T10:00:00",
            "corrections": {
                "pii_override": {"ai": "not_sensitive", "human": "sensitive"},
                "category": {"human": "Legal"},
            },
        },
    ]
    path = tmp_path / "corrections_log.json"
    path.write_text(json.dumps(corrections))
    return path


@pytest.fixture
def manager(tmp_path, corrections_file):
    return LearnedRulesManager(
        corrections_path=corrections_file,
        learned_rules_path=tmp_path / "learned_rules.yaml",
    )


class TestAnalyzeCorrections:
    def test_finds_folder_redirects(self, manager):
        patterns = manager.analyze_corrections()
        redirects = patterns["folder_redirects"]
        assert len(redirects) >= 1
        key = "Medical->Medical/Insurance"
        assert key in redirects
        assert redirects[key]["count"] == 2

    def test_finds_category_corrections(self, manager):
        patterns = manager.analyze_corrections()
        cats = patterns["category_corrections"]
        key = "Medical->Insurance"
        assert key in cats
        assert cats[key]["count"] == 2

    def test_finds_sensitivity_patterns(self, manager):
        patterns = manager.analyze_corrections()
        sens = patterns["sensitivity_patterns"]
        assert len(sens) >= 1

    def test_empty_log_returns_empty(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("[]")
        mgr = LearnedRulesManager(
            corrections_path=empty, learned_rules_path=tmp_path / "rules.yaml"
        )
        patterns = mgr.analyze_corrections()
        assert patterns["folder_redirects"] == {}

    def test_missing_log_returns_empty(self, tmp_path):
        mgr = LearnedRulesManager(
            corrections_path=tmp_path / "missing.json",
            learned_rules_path=tmp_path / "rules.yaml",
        )
        patterns = mgr.analyze_corrections()
        assert patterns["folder_redirects"] == {}


class TestGenerateRules:
    def test_generates_rules_above_threshold(self, manager):
        rules = manager.generate_rules()
        assert len(rules) >= 2  # folder_redirect + category_default at minimum
        types = {r.rule_type for r in rules}
        assert "folder_redirect" in types
        assert "category_default" in types

    def test_ignores_single_occurrences(self, tmp_path):
        corrections = [
            {
                "timestamp": "2025-01-01",
                "corrections": {"target_folder": {"ai": "A", "human": "B"}},
            },
        ]
        path = tmp_path / "corrections.json"
        path.write_text(json.dumps(corrections))
        mgr = LearnedRulesManager(corrections_path=path, learned_rules_path=tmp_path / "rules.yaml")
        rules = mgr.generate_rules()
        assert len(rules) == 0  # Single occurrence below MIN_FREQUENCY

    def test_rules_persisted_to_yaml(self, manager, tmp_path):
        manager.generate_rules()
        rules_path = tmp_path / "learned_rules.yaml"
        assert rules_path.exists()
        data = yaml.safe_load(rules_path.read_text())
        assert "rules" in data
        assert len(data["rules"]) >= 2


class TestGetFolderSuggestion:
    def test_returns_learned_redirect(self, manager):
        manager.generate_rules()
        result = manager.get_folder_suggestion("Medical", "Insurance")
        assert result is not None
        assert result == "Medical/Insurance"

    def test_returns_none_for_unknown(self, manager):
        manager.generate_rules()
        result = manager.get_folder_suggestion("Unknown", "Unknown")
        assert result is None


class TestShouldMarkSensitive:
    def test_returns_true_for_learned_pattern(self, manager):
        manager.generate_rules()
        result = manager.should_mark_sensitive("Legal", "Report")
        assert result is True

    def test_returns_none_for_unknown(self, manager):
        manager.generate_rules()
        result = manager.should_mark_sensitive("Unknown", "Report")
        assert result is None


class TestRulePersistence:
    def test_rules_survive_reload(self, tmp_path, corrections_file):
        rules_path = tmp_path / "learned_rules.yaml"
        mgr1 = LearnedRulesManager(corrections_path=corrections_file, learned_rules_path=rules_path)
        mgr1.generate_rules()
        rule_count = len(mgr1._rules)

        mgr2 = LearnedRulesManager(corrections_path=corrections_file, learned_rules_path=rules_path)
        assert len(mgr2._rules) == rule_count
