"""Sorting Rules Pattern Learning — derive rules from user corrections.

Analyzes the correction log to identify consistent patterns in how
users override AI folder suggestions, category assignments, and
sensitivity flags. Learned rules are applied to future documents.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from src.config import STATE_DIR

logger = logging.getLogger(__name__)

MIN_FREQUENCY = 2  # Minimum corrections before a rule is learned
FOLDER_CONFIDENCE_THRESHOLD = 0.5
SENSITIVITY_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class LearnedRule:
    """A rule derived from user correction patterns."""

    rule_type: str  # "folder_redirect", "category_default", "sensitivity_pattern"
    pattern: str  # Source pattern (e.g., category name)
    suggestion: str  # Target (e.g., folder path)
    frequency: int
    confidence: float
    last_seen: str = ""


class LearnedRulesManager:
    """Learn organization patterns from user corrections."""

    def __init__(
        self,
        corrections_path: Optional[Path] = None,
        learned_rules_path: Optional[Path] = None,
    ):
        self.corrections_path = corrections_path or Path("corrections_log.json")
        self.learned_rules_path = learned_rules_path or STATE_DIR / "learned_rules.yaml"
        self._rules: list[LearnedRule] = []
        self._load_rules()

    def _load_rules(self) -> None:
        """Load previously generated rules."""
        if not self.learned_rules_path.exists():
            return
        try:
            with open(self.learned_rules_path) as f:
                data = yaml.safe_load(f) or {}
            for rule_data in data.get("rules", []):
                self._rules.append(
                    LearnedRule(
                        rule_type=rule_data["rule_type"],
                        pattern=rule_data["pattern"],
                        suggestion=rule_data["suggestion"],
                        frequency=rule_data["frequency"],
                        confidence=rule_data["confidence"],
                        last_seen=rule_data.get("last_seen", ""),
                    )
                )
        except Exception as e:
            logger.debug(f"Could not load learned rules: {e}")

    def _save_rules(self) -> None:
        """Persist rules to YAML."""
        self.learned_rules_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": datetime.now().isoformat(),
            "rules": [
                {
                    "rule_type": r.rule_type,
                    "pattern": r.pattern,
                    "suggestion": r.suggestion,
                    "frequency": r.frequency,
                    "confidence": r.confidence,
                    "last_seen": r.last_seen,
                }
                for r in self._rules
            ],
        }
        with open(self.learned_rules_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _load_corrections(self) -> list[dict]:
        """Load corrections from the correction log."""
        if not self.corrections_path.exists():
            return []
        try:
            with open(self.corrections_path) as f:
                return json.load(f)
        except Exception:
            return []

    def analyze_corrections(self) -> dict[str, dict]:
        """Analyze correction log to find patterns.

        Returns dict with keys: folder_redirects, category_corrections, sensitivity_patterns
        """
        corrections = self._load_corrections()
        if not corrections:
            return {"folder_redirects": {}, "category_corrections": {}, "sensitivity_patterns": {}}

        folder_redirects: dict[str, dict] = {}
        category_corrections: dict[str, dict] = {}
        sensitivity_patterns: dict[str, dict] = {}

        for entry in corrections:
            corr = entry.get("corrections", {})
            timestamp = entry.get("timestamp", "")

            # Folder redirects: AI folder → human folder
            if "target_folder" in corr:
                ai = corr["target_folder"].get("ai", "")
                human = corr["target_folder"].get("human", "")
                if ai and human and ai != human:
                    key = f"{ai}->{human}"
                    if key not in folder_redirects:
                        folder_redirects[key] = {
                            "ai": ai,
                            "human": human,
                            "count": 0,
                            "last_seen": "",
                        }
                    folder_redirects[key]["count"] += 1
                    folder_redirects[key]["last_seen"] = timestamp

            # Category corrections: AI category → human category
            if "category" in corr:
                ai = corr["category"].get("ai", "")
                human = corr["category"].get("human", "")
                if ai and human and ai != human:
                    key = f"{ai}->{human}"
                    if key not in category_corrections:
                        category_corrections[key] = {
                            "ai": ai,
                            "human": human,
                            "count": 0,
                            "last_seen": "",
                        }
                    category_corrections[key]["count"] += 1
                    category_corrections[key]["last_seen"] = timestamp

            # Sensitivity overrides
            if "pii_override" in corr:
                ai_val = corr["pii_override"].get("ai", "")
                human_val = corr["pii_override"].get("human", "")
                if ai_val and human_val and ai_val != human_val:
                    # Track by category if available
                    category = corr.get("category", {}).get("human", "unknown")
                    if isinstance(category, dict):
                        category = category.get("human", "unknown")
                    key = f"{category}:{human_val}"
                    if key not in sensitivity_patterns:
                        sensitivity_patterns[key] = {
                            "category": category,
                            "sensitivity": human_val,
                            "count": 0,
                            "last_seen": "",
                        }
                    sensitivity_patterns[key]["count"] += 1
                    sensitivity_patterns[key]["last_seen"] = timestamp

        return {
            "folder_redirects": folder_redirects,
            "category_corrections": category_corrections,
            "sensitivity_patterns": sensitivity_patterns,
        }

    def generate_rules(self) -> list[LearnedRule]:
        """Generate rules from patterns meeting MIN_FREQUENCY threshold."""
        patterns = self.analyze_corrections()
        rules: list[LearnedRule] = []

        total_folder = sum(p["count"] for p in patterns["folder_redirects"].values()) or 1
        for _key, p in patterns["folder_redirects"].items():
            if p["count"] >= MIN_FREQUENCY:
                rules.append(
                    LearnedRule(
                        rule_type="folder_redirect",
                        pattern=p["ai"],
                        suggestion=p["human"],
                        frequency=p["count"],
                        confidence=p["count"] / total_folder,
                        last_seen=p["last_seen"],
                    )
                )

        total_cat = sum(p["count"] for p in patterns["category_corrections"].values()) or 1
        for _key, p in patterns["category_corrections"].items():
            if p["count"] >= MIN_FREQUENCY:
                rules.append(
                    LearnedRule(
                        rule_type="category_default",
                        pattern=p["ai"],
                        suggestion=p["human"],
                        frequency=p["count"],
                        confidence=p["count"] / total_cat,
                        last_seen=p["last_seen"],
                    )
                )

        total_sens = sum(p["count"] for p in patterns["sensitivity_patterns"].values()) or 1
        for _key, p in patterns["sensitivity_patterns"].items():
            if p["count"] >= MIN_FREQUENCY:
                rules.append(
                    LearnedRule(
                        rule_type="sensitivity_pattern",
                        pattern=p["category"],
                        suggestion=p["sensitivity"],
                        frequency=p["count"],
                        confidence=p["count"] / total_sens,
                        last_seen=p["last_seen"],
                    )
                )

        self._rules = rules
        self._save_rules()
        return rules

    def get_folder_suggestion(self, ai_folder: str, category: str) -> Optional[str]:
        """Get a learned folder override for an AI suggestion."""
        for rule in self._rules:
            if (
                rule.rule_type == "folder_redirect"
                and rule.confidence >= FOLDER_CONFIDENCE_THRESHOLD
            ):
                if rule.pattern == ai_folder:
                    return rule.suggestion
            if (
                rule.rule_type == "category_default"
                and rule.confidence >= FOLDER_CONFIDENCE_THRESHOLD
            ):
                if rule.pattern == category:
                    return rule.suggestion
        return None

    def should_mark_sensitive(self, category: str, doc_type: str) -> Optional[bool]:
        """Check if documents of this category are typically marked sensitive."""
        for rule in self._rules:
            if (
                rule.rule_type == "sensitivity_pattern"
                and rule.confidence >= SENSITIVITY_CONFIDENCE_THRESHOLD
            ):
                if rule.pattern == category:
                    return rule.suggestion == "sensitive"
        return None
