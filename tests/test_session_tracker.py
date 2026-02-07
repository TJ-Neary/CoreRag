"""Tests for SessionTracker (episodic memory)."""

import json
import tempfile
from pathlib import Path

import pytest

from src.memory.episodic_memory import SessionTracker


class TestSessionTracker:
    """Tests for the lightweight session tracker."""

    @pytest.fixture
    def tracker(self):
        with tempfile.TemporaryDirectory() as td:
            yield SessionTracker(storage_dir=Path(td))

    def test_creates_session_on_init(self, tracker):
        assert tracker._current is not None
        assert tracker._current.session_id is not None
        assert tracker._current.started_at is not None

    def test_log_event_records_events(self, tracker):
        tracker.log_event(
            event_type="search",
            tool_name="search_knowledge",
            query="test query",
            result_count=5,
            duration_ms=120.0,
        )
        assert len(tracker._current.events) == 1
        event = tracker._current.events[0]
        assert event.event_type == "search"
        assert event.tool_name == "search_knowledge"
        assert event.query == "test query"
        assert event.result_count == 5
        assert event.duration_ms == 120.0

    def test_log_multiple_events(self, tracker):
        for i in range(5):
            tracker.log_event(event_type="search", tool_name="tool", query=f"q{i}")
        assert len(tracker._current.events) == 5

    def test_get_current_session(self, tracker):
        tracker.log_event(event_type="search", tool_name="search_knowledge", query="hello")
        info = tracker.get_current_session()
        assert info is not None
        assert "session_id" in info
        assert info["event_count"] == 1
        assert len(info["events"]) == 1

    def test_end_session_saves_to_disk(self, tracker):
        tracker.log_event(event_type="search", tool_name="search_knowledge", query="test")
        session_id = tracker._current.session_id
        tracker.end_session()

        # Verify file was written
        session_file = tracker.storage_dir / f"session_{session_id}.json"
        assert session_file.exists()

        # Verify content
        with open(session_file) as f:
            data = json.load(f)
        assert data["session_id"] == session_id
        assert len(data["events"]) == 1
        assert data["ended_at"] is not None

    def test_end_session_clears_current(self, tracker):
        tracker.end_session()
        assert tracker._current is None

    def test_get_recent_sessions(self, tracker):
        # End current session so it saves
        tracker.log_event(event_type="search", tool_name="tool", query="q1")
        tracker.end_session()

        # Start a new one
        tracker._start_session()
        tracker.log_event(event_type="search", tool_name="tool", query="q2")
        tracker.end_session()

        sessions = tracker.get_recent_sessions(limit=10)
        assert len(sessions) == 2
        assert all("session_id" in s for s in sessions)

    def test_auto_save_every_10_events(self, tracker):
        session_id = tracker._current.session_id
        for i in range(10):
            tracker.log_event(event_type="search", tool_name="tool", query=f"q{i}")

        # After 10 events, auto-save should have occurred
        session_file = tracker.storage_dir / f"session_{session_id}.json"
        assert session_file.exists()

    def test_get_popular_queries(self, tracker):
        for _ in range(3):
            tracker.log_event(event_type="search", tool_name="tool", query="popular query")
        tracker.log_event(event_type="search", tool_name="tool", query="rare query")

        popular = tracker.get_popular_queries(limit=5)
        assert len(popular) >= 1
        assert popular[0]["query"] == "popular query"
        assert popular[0]["count"] == 3
