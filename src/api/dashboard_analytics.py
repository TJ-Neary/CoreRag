"""Dashboard query analytics routes — summary, failed queries, patterns, feedback."""

import logging

from fastapi import APIRouter, Request

from src.config import STATE_DIR

logger = logging.getLogger(__name__)


def create_analytics_router() -> APIRouter:
    """Create a router for query analytics endpoints."""
    router = APIRouter()

    @router.get("/api/analytics/summary")
    async def get_analytics_summary(days: int = 7) -> dict:
        """Get query analytics summary."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            summary = analytics.get_summary(days=days)
            return {
                "total_queries": summary.total_queries,
                "unique_queries": summary.unique_queries,
                "avg_latency_ms": round(summary.avg_latency_ms, 1),
                "avg_results_count": round(summary.avg_results_count, 1),
                "avg_top_score": round(summary.avg_top_score, 3),
                "failed_queries": summary.failed_queries,
                "top_queries": [{"query": q, "count": c} for q, c in summary.top_queries],
                "quality_trend": summary.quality_trend,
                "period_days": days,
            }
        except Exception as e:
            return {"error": str(e), "total_queries": 0}

    @router.get("/api/analytics/failed")
    async def get_failed_queries(limit: int = 20) -> dict:
        """Get queries with poor results."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            failed = analytics.get_failed_queries(limit=limit)
            return {
                "failed_queries": [
                    {
                        "query": e.query,
                        "timestamp": e.timestamp,
                        "results_count": e.results_count,
                        "top_score": e.top_result_score,
                        "top_file": e.top_result_file,
                    }
                    for e in failed
                ],
                "total": len(failed),
            }
        except Exception as e:
            return {"error": str(e), "failed_queries": [], "total": 0}

    @router.get("/api/analytics/golden-suggestions")
    async def get_golden_suggestions(limit: int = 10) -> dict:
        """Get suggested additions to the Golden Set."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            suggestions = analytics.get_golden_set_suggestions(limit=limit)
            return {"suggestions": suggestions, "total": len(suggestions)}
        except Exception as e:
            return {"error": str(e), "suggestions": [], "total": 0}

    @router.get("/api/analytics/patterns")
    async def get_query_patterns() -> dict:
        """Get detected query patterns."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            patterns = analytics.get_patterns()
            return {
                "patterns": [
                    {
                        "pattern": p.pattern,
                        "frequency": p.frequency,
                        "avg_results": round(p.avg_results, 1),
                        "avg_score": round(p.avg_score, 3),
                        "last_seen": p.last_seen,
                        "examples": p.example_queries[:3],
                    }
                    for p in sorted(patterns, key=lambda x: -x.frequency)
                ],
                "total": len(patterns),
            }
        except Exception as e:
            return {"error": str(e), "patterns": [], "total": 0}

    @router.post("/api/analytics/feedback")
    async def log_query_feedback(request: Request) -> dict:
        """Log user feedback for a search query."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            body = await request.json()
            query = body.get("query", "")
            feedback = body.get("feedback", "")

            if not query or feedback not in ("good", "bad"):
                return {"success": False, "error": "Requires query and feedback (good/bad)"}

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            analytics.log_feedback(query, feedback)
            analytics.flush()
            return {"success": True, "query": query, "feedback": feedback}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return router
