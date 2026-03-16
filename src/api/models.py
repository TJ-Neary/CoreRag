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
    k: int = Field(default=5, ge=1, le=100, description="Number of results per page")
    offset: int = Field(default=0, ge=0, description="Number of results to skip (pagination)")
    use_hyde: bool = Field(
        default=False, description="Enable HyDE (Hypothetical Document Embedding) expansion"
    )
    tags: List[str] = Field(default=[], description="Filter results to documents with these tags")
    category: Optional[str] = Field(default=None, description="Filter by document category")
    search_scope: str = Field(
        default="main",
        description="Which DB to search: 'main' (redacted), 'restricted' (full-text), or 'all'",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "authentication setup guide",
                "k": 5,
                "offset": 0,
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
    total: int = Field(description="Total results available (before pagination)")
    query: str = Field(description="Original query string")
    offset: int = Field(default=0, description="Offset used for this page")
    has_more: bool = Field(default=False, description="Whether more results exist beyond this page")
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


class QuickCaptureRequest(BaseModel):
    """Request body for quick capture (mobile/shortcut)."""

    text: str = Field(..., min_length=1, max_length=50000, description="Text to capture")
    source: str = Field(default="quick-capture", max_length=200, description="Source identifier")
    tags: List[str] = Field(default=[], description="Optional tags")


class QuickCaptureResponse(BaseModel):
    """Response from quick capture."""

    document_id: str = Field(description="Generated document ID")
    status: str = Field(description="Capture status")
    error: Optional[str] = Field(default=None, description="Error message if capture failed")


# === Document Retrieval Endpoint ===


class DocumentResponse(BaseModel):
    """Response from document retrieval."""

    document_id: str = Field(description="Document identifier")
    source_path: str = Field(description="Original source path")
    parent_chunks: int = Field(description="Number of parent chunks")
    child_chunks: int = Field(description="Number of child chunks")
    tags: List[str] = Field(default=[], description="Document tags")
    content_preview: str = Field(default="", description="Preview of document content")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")


# === Bulk Delete Endpoint ===


class BulkDeleteRequest(BaseModel):
    """Request body for bulk document deletion."""

    document_ids: List[str] = Field(
        ..., min_length=1, max_length=100, description="Document IDs to delete"
    )


class BulkDeleteResult(BaseModel):
    """Result for a single document in bulk delete."""

    document_id: str = Field(description="Document ID")
    success: bool = Field(description="Whether deletion succeeded")
    chunks_deleted: int = Field(default=0, description="Chunks removed")
    error: Optional[str] = Field(default=None, description="Error if failed")


class BulkDeleteResponse(BaseModel):
    """Response from bulk document deletion."""

    results: List[BulkDeleteResult] = Field(description="Per-document results")
    total_deleted: int = Field(description="Total chunks deleted across all documents")


# === Error Response ===


# === Answer Synthesis Endpoint ===


class AnswerRequest(BaseModel):
    """Request body for answer synthesis."""

    query: str = Field(..., min_length=1, max_length=5000, description="Question to answer")
    k: int = Field(default=5, ge=1, le=50, description="Number of evidence chunks to retrieve")
    validation_mode: str = Field(
        default="relaxed",
        description="Citation validation mode: 'strict' (verbatim quotes) or 'relaxed' (paraphrasing OK)",
    )
    use_reranker: bool = Field(default=True, description="Apply cross-encoder re-ranking")
    use_hyde: bool = Field(default=False, description="Enable HyDE query expansion")
    tags: List[str] = Field(default=[], description="Filter evidence to documents with these tags")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "How does authentication work?",
                "k": 5,
                "validation_mode": "relaxed",
            }
        }


class AnswerCitation(BaseModel):
    """A citation supporting a claim."""

    source_path: str = Field(description="Source document path")
    chunk_index: int = Field(description="Chunk position within document")
    quote: str = Field(description="Supporting quote from evidence")
    confidence: float = Field(default=1.0, description="Citation confidence (0-1)")


class AnswerClaim(BaseModel):
    """A claim from the synthesized answer with citations."""

    text: str = Field(description="The claim text")
    citations: List[AnswerCitation] = Field(default=[], description="Supporting citations")
    confidence: float = Field(default=1.0, description="Claim confidence (0-1)")


class AnswerResponse(BaseModel):
    """Response from answer synthesis."""

    query: str = Field(description="Original question")
    answer: str = Field(description="Synthesized answer text")
    claims: List[AnswerClaim] = Field(default=[], description="Claims with citations")
    sources_used: List[str] = Field(default=[], description="Source documents referenced")
    validation_mode: str = Field(description="Validation mode used")
    validation_errors: List[str] = Field(default=[], description="Any citation validation errors")
    not_found: bool = Field(default=False, description="True if evidence was insufficient")
    llm_calls: int = Field(default=0, description="Number of LLM calls made")
    error: Optional[str] = Field(default=None, description="Error message if synthesis failed")


# === Error Response ===


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error info")
