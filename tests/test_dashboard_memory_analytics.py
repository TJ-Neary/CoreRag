"""Tests for dashboard episodic memory and query analytics endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.server import app


@pytest.fixture
def client():
    return TestClient(app)


# ── Episodic Memory Routes ──────────────────────────────────────────────


class TestUserFactsRoutes:
    """Tests for user facts dashboard endpoints."""

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_add_user_fact(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.post(
            "/api/user-facts",
            json={"content": "Lives in Springfield", "category": "personal"},
        )
        data = response.json()
        assert data["success"] is True
        assert data["content"] == "Lives in Springfield"
        assert data["category"] == "personal"

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_add_user_fact_empty_content(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.post(
            "/api/user-facts",
            json={"content": "", "category": "personal"},
        )
        data = response.json()
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_add_user_fact_invalid_category(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.post(
            "/api/user-facts",
            json={"content": "Some fact", "category": "invalid_cat"},
        )
        data = response.json()
        assert data["success"] is False
        assert "Invalid category" in data["error"]

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_user_facts_stats(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        # Add some facts first
        client.post(
            "/api/user-facts",
            json={"content": "Fact A", "category": "personal"},
        )
        client.post(
            "/api/user-facts",
            json={"content": "Fact B", "category": "preference"},
        )

        response = client.get("/api/user-facts/stats")
        data = response.json()
        assert data["total_facts"] >= 2
        assert "personal" in data["categories"]
        assert "preference" in data["categories"]

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_export_user_profile(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        # Add a fact first
        client.post(
            "/api/user-facts",
            json={"content": "Likes Python", "category": "preference"},
        )

        response = client.get("/api/user-facts/export")
        data = response.json()
        assert "user_id" in data
        assert "facts" in data
        assert len(data["facts"]) >= 1


# ── Query Analytics Routes ──────────────────────────────────────────────


class TestAnalyticsRoutes:
    """Tests for query analytics dashboard endpoints."""

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_analytics_summary(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.get("/api/analytics/summary")
        data = response.json()
        assert "total_queries" in data
        assert "quality_trend" in data
        assert data["total_queries"] >= 0

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_analytics_summary_with_days(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.get("/api/analytics/summary?days=30")
        data = response.json()
        assert data["period_days"] == 30

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_failed_queries(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.get("/api/analytics/failed")
        data = response.json()
        assert "failed_queries" in data
        assert "total" in data

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_golden_suggestions(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.get("/api/analytics/golden-suggestions")
        data = response.json()
        assert "suggestions" in data
        assert "total" in data

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_get_query_patterns(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.get("/api/analytics/patterns")
        data = response.json()
        assert "patterns" in data
        assert "total" in data

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_log_feedback_good(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.post(
            "/api/analytics/feedback",
            json={"query": "test query", "feedback": "good"},
        )
        data = response.json()
        assert data["success"] is True
        assert data["feedback"] == "good"

    @patch("src.api.dashboard_routes.STATE_DIR")
    def test_log_feedback_invalid(self, mock_state_dir, client, tmp_path):
        mock_state_dir.__truediv__ = lambda self, x: tmp_path / x

        response = client.post(
            "/api/analytics/feedback",
            json={"query": "test query", "feedback": "neutral"},
        )
        data = response.json()
        assert data["success"] is False
