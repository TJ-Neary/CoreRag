"""
Pydantic Models for Core Memory API v1

Provides request/response validation and automatic OpenAPI documentation.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# === Search Endpoint ===


class SearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(..., min_length=1, max_length=5000, description="Search query text")
    k: int = Field(default=5, ge=1, le=100, description="Number of results to return")
    use_hyde: bool = Field(
        default=False, description="Enable HyDE (Hypothetical Document Embedding) expansion"
    )
    tags: List[str] = Field(default=[], description="Filter results to documents with these tags")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "authentication setup guide",
                "k": 5,
                "use_hyde": False,
                "tags": ["sphr-study"],
            }
        }


class SearchResultItem(BaseModel):
    """A single search result."""

    content: str = Field(description="Matched content text")
    source_path: str = Field(description="Original file path")
    document_id: str = Field(description="Unique document identifier")
    parent_id: str = Field(description="Parent chunk ID")
    chunk_index: int = Field(description="Position within document")
    score: float = Field(description="Similarity score (lower is better)")
    tags: List[str] = Field(default=[], description="Document tags")


class SearchResponse(BaseModel):
    """Response from semantic search."""

    results: List[SearchResultItem] = Field(description="Search results")
    total: int = Field(description="Total number of results returned")
    query: str = Field(description="Original query string")
    error: Optional[str] = Field(default=None, description="Error message if search failed")


# === Ingest Endpoint ===


class IngestMetadata(BaseModel):
    """Optional metadata for ingested content."""

    category: Optional[str] = Field(default=None, description="Document category")
    year: Optional[str] = Field(default=None, description="Document year")
    tags: List[str] = Field(default=[], description="Tags to apply")
    source_type: Optional[str] = Field(
        default=None, description="Type of source (note, chat, etc.)"
    )


class IngestRequest(BaseModel):
    """Request body for content ingestion."""

    content: str = Field(..., min_length=1, max_length=100000, description="Text content to ingest")
    source: str = Field(
        default="api-ingest",
        max_length=200,
        description="Source identifier (e.g., 'ai-assistant-note')",
    )
    metadata: IngestMetadata = Field(
        default_factory=IngestMetadata, description="Optional metadata"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "content": "This is a note about authentication...",
                "source": "my-app",
                "metadata": {"category": "notes", "year": "2026", "tags": ["auth", "security"]},
            }
        }


class IngestResponse(BaseModel):
    """Response from content ingestion."""

    document_id: str = Field(description="Unique document identifier")
    source: str = Field(description="Source identifier")
    chunks_created: int = Field(description="Number of child chunks created")
    parent_chunks: int = Field(description="Number of parent chunks created")
    error: Optional[str] = Field(default=None, description="Error message if ingestion failed")


# === Stats Endpoint ===


class StatsResponse(BaseModel):
    """Database statistics."""

    documents: int = Field(description="Number of unique documents")
    parent_chunks: int = Field(description="Number of parent chunks")
    child_chunks: int = Field(description="Number of child chunks")
    entities: int = Field(description="Number of knowledge graph entities")
    relationships: int = Field(description="Number of entity relationships")


# === Delete Endpoint ===


class DeleteResponse(BaseModel):
    """Response from document deletion."""

    success: bool = Field(description="Whether deletion succeeded")
    document_id: str = Field(description="Deleted document ID")
    chunks_deleted: int = Field(description="Total chunks removed")
    graph_deleted: int = Field(default=0, description="Graph entities removed")
    error: Optional[str] = Field(default=None, description="Error message if deletion failed")


# === Manifest Endpoint ===


class AuthenticationInfo(BaseModel):
    """Authentication configuration."""

    enabled: bool = Field(description="Whether API key auth is enabled")
    type: str = Field(description="Authentication type")
    header: str = Field(description="HTTP header name for API key")
    note: str = Field(description="Usage notes")


class EndpointInfo(BaseModel):
    """Information about an API endpoint."""

    endpoint: str = Field(description="URL path")
    method: str = Field(description="HTTP method")
    description: str = Field(description="What the endpoint does")


class ManifestResponse(BaseModel):
    """Capability manifest for connecting systems."""

    name: str = Field(description="System name")
    version: str = Field(description="API version")
    description: str = Field(description="System description")
    endpoints: Dict[str, EndpointInfo] = Field(description="Available endpoints")
    accepted_formats: Dict[str, Any] = Field(description="Accepted input formats")
    processing: Dict[str, bool] = Field(description="Processing capabilities")
    authentication: AuthenticationInfo = Field(description="Auth configuration")
    stats: StatsResponse = Field(description="Current database statistics")


# === Error Response ===


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error info")
