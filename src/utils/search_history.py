"""
Search history and saved queries for PKM.

Track past searches and enable query bookmarking.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class SearchEntry:
    """A single search history entry."""
    query: str
    timestamp: str
    result_count: int
    latency_ms: float
    filters: Dict = field(default_factory=dict)
    clicked_results: List[str] = field(default_factory=list)


@dataclass
class SavedQuery:
    """A bookmarked/saved query."""
    query_id: str
    name: str
    query: str
    filters: Dict
    created_at: str
    last_used: Optional[str] = None
    use_count: int = 0
    description: str = ""
    tags: List[str] = field(default_factory=list)


class SearchHistory:
    """
    Track search history and manage saved queries.

    Features:
    - Recent search history
    - Saved/bookmarked queries
    - Query suggestions based on history
    - Popular queries tracking
    """

    MAX_HISTORY = 1000

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize search history.

        Args:
            state_dir: Directory for history storage
        """
        self.state_dir = state_dir or Path.home() / ".pkm" / "search"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._history: List[SearchEntry] = []
        self._saved: Dict[str, SavedQuery] = {}

        self._load_state()

    def add_search(
        self,
        query: str,
        result_count: int,
        latency_ms: float,
        filters: Optional[Dict] = None
    ) -> None:
        """
        Add a search to history.

        Args:
            query: Search query
            result_count: Number of results
            latency_ms: Search latency
            filters: Applied filters
        """
        entry = SearchEntry(
            query=query,
            timestamp=datetime.now().isoformat(),
            result_count=result_count,
            latency_ms=latency_ms,
            filters=filters or {}
        )

        self._history.append(entry)

        # Prune old entries
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

        self._save_state()

    def record_click(self, query: str, result_id: str) -> None:
        """Record that a result was clicked for a query."""
        # Find most recent matching query
        for entry in reversed(self._history):
            if entry.query == query:
                entry.clicked_results.append(result_id)
                self._save_state()
                break

    def get_recent(self, limit: int = 20) -> List[SearchEntry]:
        """Get recent searches."""
        return list(reversed(self._history[-limit:]))

    def get_popular(self, days: int = 30, limit: int = 10) -> List[tuple]:
        """
        Get popular queries from the last N days.

        Returns:
            List of (query, count) tuples
        """
        cutoff = datetime.now() - timedelta(days=days)

        recent_queries = [
            entry.query for entry in self._history
            if datetime.fromisoformat(entry.timestamp) >= cutoff
        ]

        counter = Counter(recent_queries)
        return counter.most_common(limit)

    def get_suggestions(self, prefix: str, limit: int = 5) -> List[str]:
        """
        Get query suggestions based on history.

        Args:
            prefix: Query prefix to match
            limit: Maximum suggestions

        Returns:
            List of suggested queries
        """
        prefix = prefix.lower()
        suggestions = []
        seen = set()

        for entry in reversed(self._history):
            if entry.query.lower().startswith(prefix):
                if entry.query not in seen:
                    suggestions.append(entry.query)
                    seen.add(entry.query)

                    if len(suggestions) >= limit:
                        break

        return suggestions

    def clear_history(self) -> None:
        """Clear all search history."""
        self._history.clear()
        self._save_state()
        logger.info("Search history cleared")

    # Saved queries methods

    def save_query(
        self,
        name: str,
        query: str,
        filters: Optional[Dict] = None,
        description: str = "",
        tags: Optional[List[str]] = None
    ) -> SavedQuery:
        """
        Save a query for later use.

        Args:
            name: Display name for saved query
            query: The query string
            filters: Applied filters
            description: Optional description
            tags: Optional tags

        Returns:
            Created SavedQuery
        """
        query_id = f"sq_{len(self._saved)}_{datetime.now().timestamp():.0f}"

        saved = SavedQuery(
            query_id=query_id,
            name=name,
            query=query,
            filters=filters or {},
            created_at=datetime.now().isoformat(),
            description=description,
            tags=tags or []
        )

        self._saved[query_id] = saved
        self._save_state()

        logger.info(f"Saved query: {name}")

        return saved

    def get_saved_queries(
        self,
        tag: Optional[str] = None
    ) -> List[SavedQuery]:
        """
        Get all saved queries.

        Args:
            tag: Optional tag to filter by

        Returns:
            List of saved queries
        """
        queries = list(self._saved.values())

        if tag:
            queries = [q for q in queries if tag in q.tags]

        # Sort by use count (most used first)
        queries.sort(key=lambda q: q.use_count, reverse=True)

        return queries

    def get_saved_query(self, query_id: str) -> Optional[SavedQuery]:
        """Get a specific saved query."""
        return self._saved.get(query_id)

    def use_saved_query(self, query_id: str) -> Optional[SavedQuery]:
        """
        Mark a saved query as used.

        Returns the query for execution.
        """
        if query := self._saved.get(query_id):
            query.use_count += 1
            query.last_used = datetime.now().isoformat()
            self._save_state()
            return query
        return None

    def update_saved_query(
        self,
        query_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> bool:
        """Update a saved query."""
        if query := self._saved.get(query_id):
            if name is not None:
                query.name = name
            if description is not None:
                query.description = description
            if tags is not None:
                query.tags = tags

            self._save_state()
            return True
        return False

    def delete_saved_query(self, query_id: str) -> bool:
        """Delete a saved query."""
        if query_id in self._saved:
            del self._saved[query_id]
            self._save_state()
            return True
        return False

    def get_stats(self) -> Dict:
        """Get search history statistics."""
        if not self._history:
            return {"message": "No search history"}

        total_searches = len(self._history)
        avg_latency = sum(e.latency_ms for e in self._history) / total_searches
        avg_results = sum(e.result_count for e in self._history) / total_searches

        # Searches by day
        day_counts = Counter(
            datetime.fromisoformat(e.timestamp).strftime("%Y-%m-%d")
            for e in self._history
        )

        return {
            "total_searches": total_searches,
            "saved_queries": len(self._saved),
            "avg_latency_ms": avg_latency,
            "avg_result_count": avg_results,
            "searches_by_day": dict(day_counts),
            "unique_queries": len(set(e.query for e in self._history))
        }

    def _load_state(self) -> None:
        """Load state from disk."""
        history_file = self.state_dir / "history.json"
        saved_file = self.state_dir / "saved.json"

        if history_file.exists():
            try:
                with open(history_file) as f:
                    data = json.load(f)

                self._history = [
                    SearchEntry(**entry) for entry in data.get("entries", [])
                ]
            except Exception as e:
                logger.error(f"Failed to load search history: {e}")

        if saved_file.exists():
            try:
                with open(saved_file) as f:
                    data = json.load(f)

                self._saved = {
                    qid: SavedQuery(**qdata)
                    for qid, qdata in data.get("queries", {}).items()
                }
            except Exception as e:
                logger.error(f"Failed to load saved queries: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        # Save history
        history_file = self.state_dir / "history.json"
        with open(history_file, "w") as f:
            json.dump({
                "entries": [
                    {
                        "query": e.query,
                        "timestamp": e.timestamp,
                        "result_count": e.result_count,
                        "latency_ms": e.latency_ms,
                        "filters": e.filters,
                        "clicked_results": e.clicked_results
                    }
                    for e in self._history
                ]
            }, f)

        # Save saved queries
        saved_file = self.state_dir / "saved.json"
        with open(saved_file, "w") as f:
            json.dump({
                "queries": {
                    qid: {
                        "query_id": q.query_id,
                        "name": q.name,
                        "query": q.query,
                        "filters": q.filters,
                        "created_at": q.created_at,
                        "last_used": q.last_used,
                        "use_count": q.use_count,
                        "description": q.description,
                        "tags": q.tags
                    }
                    for qid, q in self._saved.items()
                }
            }, f, indent=2)
