"""Golden Set Manager — auto-populate and manage golden set test cases.

Uses QueryAnalytics suggestions to semi-automatically grow the golden set
regression suite. Supports approve/reject workflow and manual entries.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from src.config import STATE_DIR

logger = logging.getLogger(__name__)

# Rejection list persisted to avoid re-suggesting rejected queries
_REJECTIONS_PATH = STATE_DIR / "golden_set_rejections.yaml"


@dataclass
class GoldenSetEntry:
    """A single golden set test case."""

    query: str
    expected_file: str
    expected_in_top: int = 3
    tags: list[str] = field(default_factory=list)
    added_date: str = ""
    source: str = "manual"  # "manual", "auto-suggested", "auto-approved"


class GoldenSetManager:
    """Manages golden set entries with analytics-driven suggestions."""

    def __init__(
        self,
        golden_set_path: Optional[Path] = None,
        analytics=None,
    ):
        self.golden_set_path = golden_set_path or Path("tests/golden_set.yaml")
        self.analytics = analytics
        self._entries: list[GoldenSetEntry] = []
        self._config: dict = {}
        self._rejections: set[str] = set()
        self._load()
        self._load_rejections()

    def _load(self) -> None:
        """Load golden set entries from YAML file."""
        if not self.golden_set_path.exists():
            self._config = {"top_k": 5, "required_rank": 3, "similarity_threshold": 0.7}
            return

        with open(self.golden_set_path) as f:
            data = yaml.safe_load(f) or {}

        self._config = data.get("config", {})

        for q in data.get("queries", []):
            self._entries.append(
                GoldenSetEntry(
                    query=q["query"],
                    expected_file=q["expected_file"],
                    expected_in_top=q.get("expected_in_top", self._config.get("required_rank", 3)),
                    tags=q.get("tags", []),
                    added_date=q.get("added_date", ""),
                    source=q.get("source", "manual"),
                )
            )

    def _save(self) -> None:
        """Write golden set back to YAML file."""
        data = {
            "metadata": {
                "version": "1.0",
                "created": "2026-01-31",
                "description": "Regression test suite for CoreRag retrieval quality",
            },
            "config": self._config,
            "queries": [],
        }

        for entry in self._entries:
            q: dict = {
                "query": entry.query,
                "expected_file": entry.expected_file,
                "expected_in_top": entry.expected_in_top,
                "tags": entry.tags,
            }
            if entry.added_date:
                q["added_date"] = entry.added_date
            if entry.source != "manual":
                q["source"] = entry.source
            data["queries"].append(q)

        self.golden_set_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.golden_set_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        logger.info(f"Golden set saved: {len(self._entries)} entries")

    def _load_rejections(self) -> None:
        """Load rejection list."""
        if _REJECTIONS_PATH.exists():
            with open(_REJECTIONS_PATH) as f:
                data = yaml.safe_load(f) or {}
            self._rejections = set(data.get("rejected_queries", []))

    def _save_rejections(self) -> None:
        """Save rejection list."""
        _REJECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REJECTIONS_PATH, "w") as f:
            yaml.dump(
                {"rejected_queries": sorted(self._rejections)},
                f,
                default_flow_style=False,
            )

    def get_suggestions(self, limit: int = 10) -> list[dict]:
        """Get analytics-based suggestions, filtered against existing entries and rejections."""
        if not self.analytics:
            return []

        suggestions = self.analytics.get_golden_set_suggestions(limit=limit * 2)
        existing_queries = {e.query.lower() for e in self._entries}

        filtered = []
        for s in suggestions:
            query_lower = s["query"].lower()
            if query_lower not in existing_queries and query_lower not in self._rejections:
                filtered.append(s)

        return filtered[:limit]

    def approve_suggestion(self, query: str) -> bool:
        """Approve a suggestion and add it to the golden set."""
        if not self.analytics:
            return False

        suggestions = self.analytics.get_golden_set_suggestions(limit=50)
        for s in suggestions:
            if s["query"].lower() == query.lower():
                return self.add_entry(
                    query=s["query"],
                    expected_file=s["expected_file"],
                    source="auto-approved",
                )
        return False

    def reject_suggestion(self, query: str) -> bool:
        """Reject a suggestion so it won't be suggested again."""
        query_lower = query.lower()
        if query_lower in self._rejections:
            return False
        self._rejections.add(query_lower)
        self._save_rejections()
        return True

    def add_entry(
        self,
        query: str,
        expected_file: str,
        expected_in_top: int = 3,
        tags: Optional[list[str]] = None,
        source: str = "manual",
    ) -> bool:
        """Add a new entry to the golden set. Returns False if duplicate."""
        if any(e.query.lower() == query.lower() for e in self._entries):
            return False

        self._entries.append(
            GoldenSetEntry(
                query=query,
                expected_file=expected_file,
                expected_in_top=expected_in_top,
                tags=tags or [],
                added_date=datetime.now().strftime("%Y-%m-%d"),
                source=source,
            )
        )
        self._save()
        return True

    def remove_entry(self, query: str) -> bool:
        """Remove an entry by query text."""
        for i, entry in enumerate(self._entries):
            if entry.query.lower() == query.lower():
                self._entries.pop(i)
                self._save()
                return True
        return False

    def list_entries(self, source_filter: Optional[str] = None, limit: int = 50) -> list[dict]:
        """List entries, optionally filtered by source."""
        entries = self._entries
        if source_filter:
            entries = [e for e in entries if e.source == source_filter]

        return [
            {
                "query": e.query,
                "expected_file": e.expected_file,
                "expected_in_top": e.expected_in_top,
                "tags": e.tags,
                "added_date": e.added_date,
                "source": e.source,
            }
            for e in entries[:limit]
        ]

    @property
    def entry_count(self) -> int:
        return len(self._entries)
