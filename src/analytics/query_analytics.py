"""
Query Analytics for CoreRag.

Tracks and analyzes search queries to:
- Identify patterns and frequent queries
- Detect failed searches (no good results)
- Suggest Golden Set additions
- Measure search quality over time
- Enable semantic caching

All data is stored locally - no external services.
"""

import hashlib
import json
import logging
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class QueryEvent:
    """A single query event."""

    query: str
    timestamp: str
    results_count: int
    top_result_score: float
    top_result_file: Optional[str]
    latency_ms: float
    used_reranker: bool = False
    used_hyde: bool = False
    user_feedback: Optional[str] = None  # "good", "bad", None
    session_id: Optional[str] = None


@dataclass
class QueryPattern:
    """A detected query pattern."""

    pattern: str
    frequency: int
    avg_results: float
    avg_score: float
    last_seen: str
    example_queries: List[str] = field(default_factory=list)


@dataclass
class AnalyticsSummary:
    """Summary of query analytics."""

    total_queries: int
    unique_queries: int
    avg_latency_ms: float
    avg_results_count: float
    avg_top_score: float
    failed_queries: int  # No results or low scores
    top_queries: List[Tuple[str, int]]
    quality_trend: str  # "improving", "stable", "declining"


class QueryAnalytics:
    """
    Track and analyze search queries.

    Features:
    - Query logging with results
    - Pattern detection
    - Quality metrics
    - Failed query identification
    - Golden Set suggestions
    """

    # Thresholds
    FAILED_QUERY_SCORE_THRESHOLD = 0.3
    MIN_RESULTS_THRESHOLD = 1

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        max_events: int = 10000,
        enable_patterns: bool = True,
    ):
        """
        Initialize query analytics.

        Args:
            state_dir: Directory for persistence
            max_events: Maximum events to keep in memory
            enable_patterns: Enable pattern detection
        """
        from src.config import STATE_DIR

        self.state_dir = state_dir or STATE_DIR / "analytics"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        self.enable_patterns = enable_patterns

        self._events: List[QueryEvent] = []
        self._query_counts: Dict[str, int] = defaultdict(int)
        self._patterns: Dict[str, QueryPattern] = {}
        self._lock = threading.Lock()

        self._load_state()

    def log_query(
        self,
        query: str,
        results_count: int,
        top_result_score: float,
        top_result_file: Optional[str] = None,
        latency_ms: float = 0.0,
        used_reranker: bool = False,
        used_hyde: bool = False,
        session_id: Optional[str] = None,
    ) -> QueryEvent:
        """
        Log a search query.

        Args:
            query: The search query
            results_count: Number of results returned
            top_result_score: Score of top result
            top_result_file: Path to top result file
            latency_ms: Query latency
            used_reranker: Whether reranker was used
            used_hyde: Whether HyDE was used
            session_id: Session identifier

        Returns:
            The logged QueryEvent
        """
        event = QueryEvent(
            query=query,
            timestamp=datetime.now().isoformat(),
            results_count=results_count,
            top_result_score=top_result_score,
            top_result_file=top_result_file,
            latency_ms=latency_ms,
            used_reranker=used_reranker,
            used_hyde=used_hyde,
            session_id=session_id,
        )

        with self._lock:
            self._events.append(event)
            self._query_counts[self._normalize_query(query)] += 1

            # Trim if over limit
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events :]

        # Update patterns
        if self.enable_patterns:
            self._update_patterns(event)

        return event

    def log_feedback(
        self,
        query: str,
        feedback: str,  # "good" or "bad"
    ) -> None:
        """Log user feedback for a query."""
        with self._lock:
            # Find recent matching query
            for event in reversed(self._events):
                if event.query == query and event.user_feedback is None:
                    event.user_feedback = feedback
                    break

    def get_summary(self, days: int = 7) -> AnalyticsSummary:
        """
        Get analytics summary.

        Args:
            days: Look back period

        Returns:
            AnalyticsSummary
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self._lock:
            recent = [e for e in self._events if datetime.fromisoformat(e.timestamp) >= cutoff]

        if not recent:
            return AnalyticsSummary(
                total_queries=0,
                unique_queries=0,
                avg_latency_ms=0,
                avg_results_count=0,
                avg_top_score=0,
                failed_queries=0,
                top_queries=[],
                quality_trend="stable",
            )

        # Calculate metrics
        unique_queries = len(set(e.query for e in recent))
        avg_latency = sum(e.latency_ms for e in recent) / len(recent)
        avg_results = sum(e.results_count for e in recent) / len(recent)
        avg_score = sum(e.top_result_score for e in recent) / len(recent)

        failed = sum(
            1
            for e in recent
            if e.results_count < self.MIN_RESULTS_THRESHOLD
            or e.top_result_score < self.FAILED_QUERY_SCORE_THRESHOLD
        )

        # Top queries
        query_freq: dict[str, int] = defaultdict(int)
        for e in recent:
            query_freq[e.query] += 1
        top_queries = sorted(query_freq.items(), key=lambda x: -x[1])[:10]

        # Quality trend (compare first half to second half)
        mid = len(recent) // 2
        if mid > 0:
            first_half_score = sum(e.top_result_score for e in recent[:mid]) / mid
            second_half_score = sum(e.top_result_score for e in recent[mid:]) / (len(recent) - mid)

            if second_half_score > first_half_score + 0.05:
                trend = "improving"
            elif second_half_score < first_half_score - 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return AnalyticsSummary(
            total_queries=len(recent),
            unique_queries=unique_queries,
            avg_latency_ms=avg_latency,
            avg_results_count=avg_results,
            avg_top_score=avg_score,
            failed_queries=failed,
            top_queries=top_queries,
            quality_trend=trend,
        )

    def get_failed_queries(self, limit: int = 20) -> List[QueryEvent]:
        """Get queries that had poor results (candidates for Golden Set)."""
        with self._lock:
            failed = [
                e
                for e in self._events
                if e.results_count < self.MIN_RESULTS_THRESHOLD
                or e.top_result_score < self.FAILED_QUERY_SCORE_THRESHOLD
            ]

        # Sort by recency
        failed.sort(key=lambda x: x.timestamp, reverse=True)
        return failed[:limit]

    def get_golden_set_suggestions(self, limit: int = 10) -> List[Dict]:
        """
        Get suggested additions to the Golden Set.

        Returns queries that:
        - Are frequently asked
        - Had good results (high scores)
        - Haven't been added to Golden Set yet
        """
        with self._lock:
            # Group by normalized query
            query_stats: Dict[str, Dict] = defaultdict(
                lambda: {
                    "count": 0,
                    "avg_score": 0.0,
                    "best_file": None,
                    "best_score": 0.0,
                    "example": "",
                }
            )

            for e in self._events:
                norm = self._normalize_query(e.query)
                stats = query_stats[norm]
                stats["count"] += 1
                stats["avg_score"] = (
                    stats["avg_score"] * (stats["count"] - 1) + e.top_result_score
                ) / stats["count"]
                if e.top_result_score > stats["best_score"]:
                    stats["best_score"] = e.top_result_score
                    stats["best_file"] = e.top_result_file
                    stats["example"] = e.query

        # Filter for good candidates
        suggestions = []
        for norm, stats in query_stats.items():
            if stats["count"] >= 3 and stats["avg_score"] >= 0.5 and stats["best_file"]:
                suggestions.append(
                    {
                        "query": stats["example"],
                        "expected_file": stats["best_file"],
                        "frequency": stats["count"],
                        "avg_score": stats["avg_score"],
                    }
                )

        # Sort by frequency
        suggestions.sort(key=lambda x: -x["frequency"])
        return suggestions[:limit]

    def get_patterns(self) -> List[QueryPattern]:
        """Get detected query patterns."""
        with self._lock:
            return list(self._patterns.values())

    def flush(self) -> None:
        """Persist state to disk."""
        self._save_state()

    def _normalize_query(self, query: str) -> str:
        """Normalize query for comparison."""
        return query.lower().strip()

    def _update_patterns(self, event: QueryEvent) -> None:
        """Update pattern detection with new event."""
        # Simple pattern: first few words
        words = event.query.lower().split()[:3]
        if len(words) >= 2:
            pattern_key = " ".join(words)

            with self._lock:
                if pattern_key not in self._patterns:
                    self._patterns[pattern_key] = QueryPattern(
                        pattern=pattern_key,
                        frequency=0,
                        avg_results=0,
                        avg_score=0,
                        last_seen=event.timestamp,
                        example_queries=[],
                    )

                p = self._patterns[pattern_key]
                p.frequency += 1
                p.avg_results = (
                    p.avg_results * (p.frequency - 1) + event.results_count
                ) / p.frequency
                p.avg_score = (
                    p.avg_score * (p.frequency - 1) + event.top_result_score
                ) / p.frequency
                p.last_seen = event.timestamp

                if event.query not in p.example_queries:
                    p.example_queries.append(event.query)
                    if len(p.example_queries) > 5:
                        p.example_queries = p.example_queries[-5:]

    def _load_state(self) -> None:
        """Load state from disk."""
        events_file = self.state_dir / "query_events.json"
        if events_file.exists():
            try:
                with open(events_file) as f:
                    data = json.load(f)
                    self._events = [QueryEvent(**e) for e in data.get("events", [])]
                    self._query_counts = defaultdict(int, data.get("counts", {}))
                logger.info(f"Loaded {len(self._events)} query events")
            except Exception as e:
                logger.warning(f"Failed to load analytics state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        events_file = self.state_dir / "query_events.json"

        try:
            with open(events_file, "w") as f:
                json.dump(
                    {
                        "events": [asdict(e) for e in self._events],
                        "counts": dict(self._query_counts),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"Failed to save analytics state: {e}")


class SemanticCache:
    """
    Cache search results by semantic similarity.

    Avoids recomputing results for similar queries.
    """

    def __init__(
        self,
        embedding_service: Any,  # EmbeddingService
        similarity_threshold: float = 0.92,
        max_entries: int = 1000,
        ttl_hours: int = 24,
    ):
        """
        Initialize semantic cache.

        Args:
            embedding_service: Service for generating embeddings
            similarity_threshold: Minimum similarity for cache hit
            max_entries: Maximum cache entries
            ttl_hours: Time to live for entries
        """
        self.embedding_service = embedding_service
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl_hours = ttl_hours

        self._cache: Dict[str, Dict] = {}  # query_hash -> {embedding, results, timestamp}
        self._embeddings: List[Tuple[str, List[float]]] = []  # (hash, embedding)
        self._lock = threading.Lock()

    def get(self, query: str) -> Optional[List[Dict]]:
        """
        Get cached results for a query.

        Returns cached results if a semantically similar query exists.
        """
        query_embedding = self.embedding_service.embed_query(query)

        with self._lock:
            # Check for similar queries
            for cached_hash, cached_embedding in self._embeddings:
                similarity = self._cosine_similarity(query_embedding, cached_embedding)

                if similarity >= self.similarity_threshold:
                    entry = self._cache.get(cached_hash)
                    if entry and not self._is_expired(entry):
                        logger.debug(f"Semantic cache hit (similarity: {similarity:.3f})")
                        return entry["results"]

        return None

    def put(self, query: str, results: List[Dict]) -> None:
        """Cache results for a query."""
        query_embedding = self.embedding_service.embed_query(query)
        query_hash = hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()

        with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_entries:
                oldest_hash = self._embeddings.pop(0)[0]
                del self._cache[oldest_hash]

            self._cache[query_hash] = {
                "embedding": query_embedding,
                "results": results,
                "timestamp": datetime.now().isoformat(),
            }
            self._embeddings.append((query_hash, query_embedding))

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._embeddings.clear()

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def _is_expired(self, entry: Dict) -> bool:
        """Check if cache entry is expired."""
        created = datetime.fromisoformat(entry["timestamp"])
        return datetime.now() - created > timedelta(hours=self.ttl_hours)

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        with self._lock:
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "similarity_threshold": self.similarity_threshold,
                "ttl_hours": self.ttl_hours,
            }
