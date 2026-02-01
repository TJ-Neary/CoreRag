"""
Citation and source tracking for PKM.

Provides precise source attribution for all search results.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)


class SourceType(Enum):
    """Types of content sources."""
    DOCUMENT = "document"
    WEBPAGE = "webpage"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "image"
    NOTE = "note"
    EMAIL = "email"
    CHAT = "chat"


@dataclass
class SourceLocation:
    """
    Precise location within a source.

    Enables "click to jump" functionality.
    """
    # Document locations
    page: Optional[int] = None
    paragraph: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    # Media locations
    timestamp_start: Optional[float] = None  # seconds
    timestamp_end: Optional[float] = None

    # Section locations
    section: Optional[str] = None
    heading: Optional[str] = None

    # Chunk reference
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None

    def to_anchor(self) -> str:
        """Generate URL anchor for this location."""
        if self.page:
            return f"page={self.page}"
        if self.timestamp_start:
            return f"t={int(self.timestamp_start)}"
        if self.chunk_id:
            return f"chunk={self.chunk_id}"
        if self.heading:
            return f"heading={quote(self.heading)}"
        return ""

    def to_display(self) -> str:
        """Human-readable location string."""
        parts = []

        if self.page:
            parts.append(f"Page {self.page}")
        if self.paragraph:
            parts.append(f"¶{self.paragraph}")
        if self.section:
            parts.append(f"§{self.section}")
        if self.heading:
            parts.append(f'"{self.heading}"')
        if self.timestamp_start is not None:
            mins = int(self.timestamp_start // 60)
            secs = int(self.timestamp_start % 60)
            parts.append(f"{mins}:{secs:02d}")
        if self.line_start:
            if self.line_end and self.line_end != self.line_start:
                parts.append(f"Lines {self.line_start}-{self.line_end}")
            else:
                parts.append(f"Line {self.line_start}")

        return ", ".join(parts) if parts else "Unknown location"


@dataclass
class Citation:
    """
    Complete citation for a piece of content.

    Tracks origin, location, and access history.
    """
    # Identity
    citation_id: str
    chunk_id: str
    document_id: str

    # Source info
    source_type: SourceType
    source_path: str
    source_title: str

    # Location
    location: SourceLocation

    # Context
    snippet: str  # The actual quoted text
    snippet_context: str  # Surrounding text for context

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    accessed_count: int = 0
    last_accessed: Optional[str] = None

    # Original source (if content was copied/forwarded)
    original_source: Optional[str] = None
    chain_of_custody: List[str] = field(default_factory=list)

    def to_link(self, scheme: str = "pkm") -> str:
        """Generate clickable link to source."""
        anchor = self.location.to_anchor()
        base = f"{scheme}://open/{quote(self.source_path)}"
        if anchor:
            return f"{base}#{anchor}"
        return base

    def to_markdown(self) -> str:
        """Format as markdown citation."""
        loc = self.location.to_display()
        return f"[{self.source_title}]({self.to_link()}) ({loc})"

    def to_academic(self) -> str:
        """Format as academic-style citation."""
        loc = self.location.to_display()
        return f'"{self.snippet}" — {self.source_title}, {loc}'


class CitationManager:
    """
    Manage citations across the knowledge base.

    Tracks source attribution, builds citation chains,
    and generates formatted references.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize citation manager.

        Args:
            state_dir: Directory for citation storage
        """
        self.state_dir = state_dir or Path.home() / ".pkm" / "citations"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._citations: Dict[str, Citation] = {}
        self._by_document: Dict[str, List[str]] = {}
        self._by_chunk: Dict[str, str] = {}

        self._load_state()

    def create_citation(
        self,
        chunk_id: str,
        document_id: str,
        source_type: SourceType,
        source_path: str,
        source_title: str,
        snippet: str,
        location: Optional[SourceLocation] = None,
        snippet_context: str = ""
    ) -> Citation:
        """
        Create a new citation for a chunk.

        Args:
            chunk_id: ID of the chunk being cited
            document_id: ID of parent document
            source_type: Type of source
            source_path: Path to source file
            source_title: Human-readable title
            snippet: The quoted text
            location: Precise location in source
            snippet_context: Surrounding context

        Returns:
            Created Citation
        """
        citation_id = f"cite_{chunk_id[:8]}_{len(self._citations)}"

        citation = Citation(
            citation_id=citation_id,
            chunk_id=chunk_id,
            document_id=document_id,
            source_type=source_type,
            source_path=source_path,
            source_title=source_title,
            location=location or SourceLocation(),
            snippet=snippet[:500],  # Truncate long snippets
            snippet_context=snippet_context[:200]
        )

        self._citations[citation_id] = citation
        self._by_chunk[chunk_id] = citation_id

        if document_id not in self._by_document:
            self._by_document[document_id] = []
        self._by_document[document_id].append(citation_id)

        self._save_state()

        return citation

    def get_citation(self, citation_id: str) -> Optional[Citation]:
        """Get citation by ID."""
        return self._citations.get(citation_id)

    def get_by_chunk(self, chunk_id: str) -> Optional[Citation]:
        """Get citation for a chunk."""
        if citation_id := self._by_chunk.get(chunk_id):
            return self._citations.get(citation_id)
        return None

    def get_by_document(self, document_id: str) -> List[Citation]:
        """Get all citations for a document."""
        citation_ids = self._by_document.get(document_id, [])
        return [self._citations[cid] for cid in citation_ids if cid in self._citations]

    def record_access(self, citation_id: str) -> None:
        """Record that a citation was accessed (clicked)."""
        if citation := self._citations.get(citation_id):
            citation.accessed_count += 1
            citation.last_accessed = datetime.now().isoformat()
            self._save_state()

    def format_results_with_citations(
        self,
        results: List[dict],
        format_type: str = "markdown"
    ) -> str:
        """
        Format search results with proper citations.

        Args:
            results: Search results with chunk_ids
            format_type: "markdown", "academic", "compact"

        Returns:
            Formatted string with citations
        """
        lines = []

        for i, result in enumerate(results, 1):
            chunk_id = result.get("chunk_id")
            citation = self.get_by_chunk(chunk_id) if chunk_id else None

            if format_type == "markdown":
                if citation:
                    lines.append(f"{i}. {citation.to_markdown()}")
                    lines.append(f"   > {result.get('snippet', '')[:200]}...")
                else:
                    lines.append(f"{i}. {result.get('title', 'Unknown')}")
                    lines.append(f"   > {result.get('snippet', '')[:200]}...")

            elif format_type == "academic":
                if citation:
                    lines.append(citation.to_academic())
                else:
                    lines.append(f'"{result.get("snippet", "")[:100]}..." — Unknown source')

            elif format_type == "compact":
                title = result.get('title', 'Unknown')[:30]
                loc = citation.location.to_display() if citation else ""
                lines.append(f"[{i}] {title} {loc}")

        return "\n".join(lines)

    def build_chain_of_custody(
        self,
        citation_id: str,
        original_source: str
    ) -> None:
        """
        Track when content is forwarded/copied.

        Maintains provenance chain.
        """
        if citation := self._citations.get(citation_id):
            citation.original_source = original_source
            citation.chain_of_custody.append(
                f"{datetime.now().isoformat()}: {citation.source_path}"
            )
            self._save_state()

    def export_bibliography(
        self,
        document_ids: Optional[List[str]] = None,
        format_type: str = "markdown"
    ) -> str:
        """
        Export bibliography for documents.

        Args:
            document_ids: Specific documents (None = all)
            format_type: Output format

        Returns:
            Formatted bibliography
        """
        citations = []

        if document_ids:
            for doc_id in document_ids:
                citations.extend(self.get_by_document(doc_id))
        else:
            citations = list(self._citations.values())

        # Deduplicate by source
        seen_sources = set()
        unique_citations = []
        for c in citations:
            if c.source_path not in seen_sources:
                seen_sources.add(c.source_path)
                unique_citations.append(c)

        # Sort by title
        unique_citations.sort(key=lambda c: c.source_title.lower())

        lines = ["# Bibliography", ""]
        for c in unique_citations:
            lines.append(f"- {c.to_markdown()}")

        return "\n".join(lines)

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_dir / "citations.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)

                for cid, cdata in data.get("citations", {}).items():
                    location = SourceLocation(**cdata.pop("location", {}))
                    source_type = SourceType(cdata.pop("source_type"))
                    self._citations[cid] = Citation(
                        **cdata,
                        location=location,
                        source_type=source_type
                    )

                self._by_document = data.get("by_document", {})
                self._by_chunk = data.get("by_chunk", {})

            except Exception as e:
                logger.error(f"Failed to load citations: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.state_dir / "citations.json"

        data = {
            "citations": {},
            "by_document": self._by_document,
            "by_chunk": self._by_chunk
        }

        for cid, citation in self._citations.items():
            data["citations"][cid] = {
                "citation_id": citation.citation_id,
                "chunk_id": citation.chunk_id,
                "document_id": citation.document_id,
                "source_type": citation.source_type.value,
                "source_path": citation.source_path,
                "source_title": citation.source_title,
                "location": {
                    "page": citation.location.page,
                    "paragraph": citation.location.paragraph,
                    "line_start": citation.location.line_start,
                    "line_end": citation.location.line_end,
                    "timestamp_start": citation.location.timestamp_start,
                    "timestamp_end": citation.location.timestamp_end,
                    "section": citation.location.section,
                    "heading": citation.location.heading,
                    "chunk_id": citation.location.chunk_id,
                    "chunk_index": citation.location.chunk_index,
                },
                "snippet": citation.snippet,
                "snippet_context": citation.snippet_context,
                "created_at": citation.created_at,
                "accessed_count": citation.accessed_count,
                "last_accessed": citation.last_accessed,
                "original_source": citation.original_source,
                "chain_of_custody": citation.chain_of_custody,
            }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)


# URL scheme handlers for different apps
class LinkGenerator:
    """Generate links for different applications."""

    @staticmethod
    def obsidian_link(vault: str, file_path: str, heading: str = "") -> str:
        """Generate Obsidian link."""
        link = f"obsidian://open?vault={quote(vault)}&file={quote(file_path)}"
        if heading:
            link += f"&heading={quote(heading)}"
        return link

    @staticmethod
    def vscode_link(file_path: str, line: int = 1) -> str:
        """Generate VS Code link."""
        return f"vscode://file/{file_path}:{line}"

    @staticmethod
    def finder_link(file_path: str) -> str:
        """Generate macOS Finder link."""
        return f"file://{file_path}"

    @staticmethod
    def web_link(url: str, anchor: str = "") -> str:
        """Generate web link with anchor."""
        if anchor:
            return f"{url}#{anchor}"
        return url
