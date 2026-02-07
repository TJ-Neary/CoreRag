"""
Core Memory API

- models.py: Pydantic request/response schemas
- v1_routes.py: External API v1 (manifest, stats, search, ingest, delete)
- dashboard_routes.py: Internal dashboard UI + batch/commit/tag/RAG routes
"""

from src.api.dashboard_routes import DashboardState, create_dashboard_router
from src.api.models import (
    DeleteResponse,
    ErrorResponse,
    IngestMetadata,
    IngestRequest,
    IngestResponse,
    ManifestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsResponse,
)
from src.api.v1_routes import create_v1_router

__all__ = [
    "DashboardState",
    "create_dashboard_router",
    "create_v1_router",
    "SearchRequest",
    "SearchResponse",
    "SearchResultItem",
    "IngestRequest",
    "IngestResponse",
    "IngestMetadata",
    "StatsResponse",
    "DeleteResponse",
    "ManifestResponse",
    "ErrorResponse",
]
