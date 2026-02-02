"""Search result models for CoreRag."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    document_id: str
    score: float  # Similarity score (0-1, higher is better)

    # Chunk content
    text: str
    page_number: Optional[int] = None
    timestamp_start: Optional[float] = None

    # Document context
    document_title: str = ""
    file_path: str = ""
    file_type: str = ""

    # Surrounding context (optional, for expanded results)
    context_before: Optional[str] = None
    context_after: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "score": self.score,
            "text": self.text,
            "page_number": self.page_number,
            "timestamp_start": self.timestamp_start,
            "document_title": self.document_title,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }

    def format_for_display(self) -> str:
        """Format result for human-readable display."""
        location = ""
        if self.page_number:
            location = f" (page {self.page_number})"
        elif self.timestamp_start:
            minutes = int(self.timestamp_start // 60)
            seconds = int(self.timestamp_start % 60)
            location = f" ({minutes}:{seconds:02d})"

        return f"""
**{self.document_title or 'Untitled'}**{location}
Score: {self.score:.2f}

{self.text}

Source: {self.file_path}
""".strip()


@dataclass
class SearchResponse:
    """Response from a search query."""

    query: str
    results: List[SearchResult] = field(default_factory=list)
    total_count: int = 0
    search_time_ms: float = 0.0

    # Filters applied
    topic_filter: Optional[str] = None
    collection_filter: Optional[str] = None
    file_type_filter: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_count": self.total_count,
            "search_time_ms": self.search_time_ms,
            "topic_filter": self.topic_filter,
            "collection_filter": self.collection_filter,
            "file_type_filter": self.file_type_filter,
        }

    def format_for_claude(self) -> str:
        """Format response for Claude MCP tool output."""
        if not self.results:
            return f"No results found for query: '{self.query}'"

        output = [f"Found {self.total_count} results for '{self.query}':\n"]

        for i, result in enumerate(self.results, 1):
            output.append(f"---\n**Result {i}** (score: {result.score:.2f})")
            output.append(result.format_for_display())

        output.append(f"\n---\nSearch completed in {self.search_time_ms:.1f}ms")

        return "\n".join(output)
