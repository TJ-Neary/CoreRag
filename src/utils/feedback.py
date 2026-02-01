"""
User feedback loop system for PKM.

Learns from user interactions to improve search relevance.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import math

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of user feedback."""
    CLICK = "click"  # User clicked on result
    EXPAND = "expand"  # User expanded result details
    COPY = "copy"  # User copied content
    OPEN = "open"  # User opened source file
    DWELL = "dwell"  # User spent time viewing
    SKIP = "skip"  # User skipped/scrolled past
    THUMBS_UP = "thumbs_up"  # Explicit positive feedback
    THUMBS_DOWN = "thumbs_down"  # Explicit negative feedback
    SAVE = "save"  # User saved/bookmarked result
    REFINE = "refine"  # User refined search after this result


@dataclass
class FeedbackEvent:
    """A single feedback event."""
    event_id: str
    timestamp: str
    feedback_type: FeedbackType
    query: str
    result_id: str
    result_position: int  # Position in results list (1-indexed)
    result_score: float  # Original relevance score
    metadata: Dict = field(default_factory=dict)


@dataclass
class QueryFeedback:
    """Aggregated feedback for a query pattern."""
    query_pattern: str  # Normalized query
    total_searches: int
    clicks: Dict[str, int]  # result_id -> click count
    positive_signals: Dict[str, int]  # result_id -> positive count
    negative_signals: Dict[str, int]  # result_id -> negative count
    avg_click_position: float
    refinement_rate: float  # How often users refine this query
    last_updated: str


class FeedbackCollector:
    """
    Collect and store user feedback events.

    Passive collection (clicks, dwells) + Active collection (thumbs).
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize feedback collector.

        Args:
            state_dir: Directory for feedback storage
        """
        self.state_dir = state_dir or Path.home() / ".pkm" / "feedback"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._events: List[FeedbackEvent] = []
        self._session_start = datetime.now()

        self._load_recent_events()

    def record_click(
        self,
        query: str,
        result_id: str,
        position: int,
        score: float
    ) -> None:
        """Record a click on a search result."""
        self._record_event(
            FeedbackType.CLICK,
            query=query,
            result_id=result_id,
            position=position,
            score=score
        )

    def record_dwell(
        self,
        query: str,
        result_id: str,
        position: int,
        score: float,
        dwell_time_seconds: float
    ) -> None:
        """Record dwell time on a result."""
        # Only record meaningful dwell times (> 5 seconds)
        if dwell_time_seconds < 5:
            return

        self._record_event(
            FeedbackType.DWELL,
            query=query,
            result_id=result_id,
            position=position,
            score=score,
            metadata={"dwell_seconds": dwell_time_seconds}
        )

    def record_explicit_feedback(
        self,
        query: str,
        result_id: str,
        position: int,
        score: float,
        is_positive: bool
    ) -> None:
        """Record explicit thumbs up/down."""
        feedback_type = FeedbackType.THUMBS_UP if is_positive else FeedbackType.THUMBS_DOWN
        self._record_event(
            feedback_type,
            query=query,
            result_id=result_id,
            position=position,
            score=score
        )

    def record_refinement(
        self,
        original_query: str,
        refined_query: str,
        clicked_results: List[str]
    ) -> None:
        """Record when user refines a search."""
        self._record_event(
            FeedbackType.REFINE,
            query=original_query,
            result_id="",
            position=0,
            score=0,
            metadata={
                "refined_query": refined_query,
                "clicked_before_refine": clicked_results
            }
        )

    def _record_event(
        self,
        feedback_type: FeedbackType,
        query: str,
        result_id: str,
        position: int,
        score: float,
        metadata: Dict = None
    ) -> None:
        """Record a feedback event."""
        event = FeedbackEvent(
            event_id=f"fb_{len(self._events)}_{datetime.now().timestamp():.0f}",
            timestamp=datetime.now().isoformat(),
            feedback_type=feedback_type,
            query=query,
            result_id=result_id,
            result_position=position,
            result_score=score,
            metadata=metadata or {}
        )

        self._events.append(event)
        self._save_events()

        logger.debug(f"Recorded {feedback_type.value} for '{query[:30]}...'")

    def get_session_events(self) -> List[FeedbackEvent]:
        """Get all events from current session."""
        return [
            e for e in self._events
            if datetime.fromisoformat(e.timestamp) >= self._session_start
        ]

    def _load_recent_events(self) -> None:
        """Load recent events from disk."""
        events_file = self.state_dir / "events.jsonl"
        if not events_file.exists():
            return

        # Load last 10000 events
        try:
            with open(events_file) as f:
                lines = f.readlines()[-10000:]

            for line in lines:
                data = json.loads(line)
                data["feedback_type"] = FeedbackType(data["feedback_type"])
                self._events.append(FeedbackEvent(**data))

        except Exception as e:
            logger.error(f"Failed to load feedback events: {e}")

    def _save_events(self) -> None:
        """Append new events to disk."""
        events_file = self.state_dir / "events.jsonl"

        # Only save most recent event (append mode)
        if self._events:
            event = self._events[-1]
            with open(events_file, "a") as f:
                f.write(json.dumps({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "feedback_type": event.feedback_type.value,
                    "query": event.query,
                    "result_id": event.result_id,
                    "result_position": event.result_position,
                    "result_score": event.result_score,
                    "metadata": event.metadata
                }) + "\n")


class FeedbackAnalyzer:
    """
    Analyze feedback to improve search quality.

    Computes relevance adjustments based on user behavior.
    """

    def __init__(self, collector: FeedbackCollector):
        """
        Initialize analyzer.

        Args:
            collector: FeedbackCollector instance
        """
        self.collector = collector
        self._query_feedback: Dict[str, QueryFeedback] = {}

    def compute_relevance_boost(
        self,
        query: str,
        result_id: str,
        base_score: float
    ) -> float:
        """
        Compute boosted score based on feedback.

        Args:
            query: Current search query
            result_id: Result to score
            base_score: Original vector similarity score

        Returns:
            Adjusted score
        """
        # Get feedback for similar queries
        query_pattern = self._normalize_query(query)
        feedback = self._get_query_feedback(query_pattern)

        if not feedback:
            return base_score

        boost = 0.0

        # Boost based on clicks
        click_count = feedback.clicks.get(result_id, 0)
        if click_count > 0:
            # Log scale for clicks (diminishing returns)
            boost += 0.1 * math.log1p(click_count)

        # Boost based on explicit positive feedback
        positive = feedback.positive_signals.get(result_id, 0)
        boost += 0.15 * positive

        # Penalty for negative feedback
        negative = feedback.negative_signals.get(result_id, 0)
        boost -= 0.2 * negative

        # Position adjustment (results clicked at lower positions get boost)
        # If users often scroll past top results to click this one, boost it
        if result_id in feedback.clicks:
            expected_clicks = feedback.total_searches * 0.3  # Assume 30% click rate for top
            actual_clicks = feedback.clicks[result_id]
            if actual_clicks > expected_clicks:
                boost += 0.05

        # Apply boost (capped)
        adjusted_score = base_score + min(max(boost, -0.3), 0.3)

        return max(0.0, min(1.0, adjusted_score))

    def get_query_suggestions(
        self,
        query: str,
        limit: int = 5
    ) -> List[str]:
        """
        Suggest related queries based on refinement patterns.

        Args:
            query: Current query
            limit: Maximum suggestions

        Returns:
            List of suggested queries
        """
        query_pattern = self._normalize_query(query)
        suggestions = []

        # Find queries that were refined from this one
        for event in self.collector._events:
            if event.feedback_type == FeedbackType.REFINE:
                if self._normalize_query(event.query) == query_pattern:
                    refined = event.metadata.get("refined_query")
                    if refined and refined not in suggestions:
                        suggestions.append(refined)

        return suggestions[:limit]

    def identify_poor_results(
        self,
        min_impressions: int = 10
    ) -> List[Tuple[str, str, float]]:
        """
        Find results that consistently get negative feedback.

        Returns:
            List of (query_pattern, result_id, negative_rate)
        """
        poor_results = []

        for pattern, feedback in self._query_feedback.items():
            for result_id, negative_count in feedback.negative_signals.items():
                positive_count = feedback.positive_signals.get(result_id, 0)
                total = negative_count + positive_count

                if total >= min_impressions:
                    negative_rate = negative_count / total
                    if negative_rate > 0.5:  # More than 50% negative
                        poor_results.append((pattern, result_id, negative_rate))

        return sorted(poor_results, key=lambda x: x[2], reverse=True)

    def compute_click_through_rate(
        self,
        query_pattern: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Compute click-through rates.

        Returns:
            Dict of query_pattern -> CTR
        """
        ctr = {}

        for pattern, feedback in self._query_feedback.items():
            if query_pattern and pattern != query_pattern:
                continue

            total_clicks = sum(feedback.clicks.values())
            if feedback.total_searches > 0:
                ctr[pattern] = total_clicks / feedback.total_searches

        return ctr

    def get_feedback_stats(self) -> Dict:
        """Get overall feedback statistics."""
        events = self.collector._events

        if not events:
            return {"message": "No feedback data yet"}

        type_counts = {}
        for event in events:
            t = event.feedback_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "total_events": len(events),
            "events_by_type": type_counts,
            "unique_queries": len(set(e.query for e in events)),
            "unique_results_clicked": len(set(
                e.result_id for e in events
                if e.feedback_type == FeedbackType.CLICK
            )),
            "avg_click_position": sum(
                e.result_position for e in events
                if e.feedback_type == FeedbackType.CLICK
            ) / max(1, type_counts.get("click", 1)),
            "positive_feedback_rate": (
                type_counts.get("thumbs_up", 0) /
                max(1, type_counts.get("thumbs_up", 0) + type_counts.get("thumbs_down", 0))
            )
        }

    def _normalize_query(self, query: str) -> str:
        """Normalize query for pattern matching."""
        return " ".join(sorted(query.lower().split()))

    def _get_query_feedback(self, query_pattern: str) -> Optional[QueryFeedback]:
        """Get aggregated feedback for a query pattern."""
        if query_pattern in self._query_feedback:
            return self._query_feedback[query_pattern]

        # Compute from events
        matching_events = [
            e for e in self.collector._events
            if self._normalize_query(e.query) == query_pattern
        ]

        if not matching_events:
            return None

        clicks = {}
        positive = {}
        negative = {}
        positions = []
        refinements = 0

        for event in matching_events:
            if event.feedback_type == FeedbackType.CLICK:
                clicks[event.result_id] = clicks.get(event.result_id, 0) + 1
                positions.append(event.result_position)
            elif event.feedback_type == FeedbackType.THUMBS_UP:
                positive[event.result_id] = positive.get(event.result_id, 0) + 1
            elif event.feedback_type == FeedbackType.THUMBS_DOWN:
                negative[event.result_id] = negative.get(event.result_id, 0) + 1
            elif event.feedback_type == FeedbackType.REFINE:
                refinements += 1

        total_searches = len(set(e.timestamp[:16] for e in matching_events))  # Unique by minute

        feedback = QueryFeedback(
            query_pattern=query_pattern,
            total_searches=total_searches,
            clicks=clicks,
            positive_signals=positive,
            negative_signals=negative,
            avg_click_position=sum(positions) / max(1, len(positions)),
            refinement_rate=refinements / max(1, total_searches),
            last_updated=datetime.now().isoformat()
        )

        self._query_feedback[query_pattern] = feedback
        return feedback


class PersonalizationEngine:
    """
    Personalize search based on user behavior patterns.
    """

    def __init__(self, analyzer: FeedbackAnalyzer):
        """
        Initialize personalization engine.

        Args:
            analyzer: FeedbackAnalyzer instance
        """
        self.analyzer = analyzer
        self._user_preferences: Dict = {}

    def learn_preferences(self) -> None:
        """Learn user preferences from feedback."""
        events = self.analyzer.collector._events

        # Learn file type preferences
        type_clicks = {}
        for event in events:
            if event.feedback_type == FeedbackType.CLICK:
                file_type = event.metadata.get("file_type", "unknown")
                type_clicks[file_type] = type_clicks.get(file_type, 0) + 1

        if type_clicks:
            total = sum(type_clicks.values())
            self._user_preferences["file_type_weights"] = {
                t: c / total for t, c in type_clicks.items()
            }

        # Learn folder preferences
        folder_clicks = {}
        for event in events:
            if event.feedback_type == FeedbackType.CLICK:
                folder = event.metadata.get("folder", "")
                if folder:
                    folder_clicks[folder] = folder_clicks.get(folder, 0) + 1

        if folder_clicks:
            total = sum(folder_clicks.values())
            self._user_preferences["folder_weights"] = {
                f: c / total for f, c in folder_clicks.items()
            }

        # Learn time-of-day patterns
        hour_clicks = {}
        for event in events:
            if event.feedback_type == FeedbackType.CLICK:
                hour = datetime.fromisoformat(event.timestamp).hour
                hour_clicks[hour] = hour_clicks.get(hour, 0) + 1

        self._user_preferences["active_hours"] = hour_clicks

    def get_personalized_boost(
        self,
        result: dict
    ) -> float:
        """Get personalization boost for a result."""
        boost = 0.0

        # File type preference
        file_type = result.get("file_type", "unknown")
        type_weights = self._user_preferences.get("file_type_weights", {})
        if file_type in type_weights:
            boost += type_weights[file_type] * 0.1

        # Folder preference
        folder = result.get("folder", "")
        folder_weights = self._user_preferences.get("folder_weights", {})
        for pref_folder, weight in folder_weights.items():
            if folder.startswith(pref_folder):
                boost += weight * 0.05
                break

        return boost
