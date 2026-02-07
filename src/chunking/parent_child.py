"""
Parent-Child Chunking Strategy

Implements Small-to-Big retrieval pattern:
- Small child chunks (100-200 tokens) for precise vector search
- Large parent chunks (1000-2000 tokens) returned to LLM for context

This solves the retrieval-generation mismatch problem.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src.config import EMBEDDING_DIMENSIONS
from src.utils.query_sanitize import build_eq_clause, build_filter_clause


@dataclass
class ParentChunk:
    """Large chunk returned to LLM for context."""

    id: str
    document_id: str
    content: str
    start_char: int
    end_char: int
    section_title: Optional[str] = None
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "content": self.content,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "section_title": self.section_title,
            "token_count": self.token_count,
            "metadata": json.dumps(self.metadata),
        }


@dataclass
class ChildChunk:
    """Small chunk used for vector search."""

    id: str
    parent_id: str
    document_id: str
    content: str
    start_char: int  # Relative to document
    end_char: int
    chunk_index: int
    embedding: Optional[List[float]] = None

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "parent_id": self.parent_id,
            "document_id": self.document_id,
            "content": self.content,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "chunk_index": self.chunk_index,
        }
        if self.embedding:
            result["vector"] = self.embedding
        return result


class ParentChildChunker:
    """
    Two-level chunking strategy for optimal retrieval and generation.

    Usage:
        chunker = ParentChildChunker()
        parents, children = chunker.chunk_document(text, document_id)
    """

    # Rough approximation: 1 token ≈ 4 characters for English
    CHARS_PER_TOKEN = 4

    def __init__(
        self,
        parent_max_tokens: int = 1500,
        child_target_tokens: int = 150,
        child_overlap_tokens: int = 25,
    ):
        self.parent_max_tokens = parent_max_tokens
        self.child_target_tokens = child_target_tokens
        self.child_overlap_tokens = child_overlap_tokens

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from character count."""
        return len(text) // self.CHARS_PER_TOKEN

    def chunk_document(
        self, content: str, document_id: str, metadata: Optional[dict] = None
    ) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        """
        Split document into parent and child chunks.

        Returns:
            Tuple of (parent_chunks, child_chunks)
        """
        metadata = metadata or {}

        # Step 1: Create parent chunks
        parents = self._create_parent_chunks(content, document_id, metadata)

        # Step 2: Create child chunks for each parent
        all_children = []
        for parent in parents:
            children = self._create_child_chunks(parent, document_id)
            all_children.extend(children)

        return parents, all_children

    def _create_parent_chunks(
        self, content: str, document_id: str, metadata: dict
    ) -> List[ParentChunk]:
        """Split document into parent chunks at natural boundaries."""

        # Detect if markdown with headers
        if self._has_markdown_headers(content):
            return self._split_by_headers(content, document_id, metadata)
        else:
            return self._split_by_paragraphs(content, document_id, metadata)

    def _has_markdown_headers(self, content: str) -> bool:
        """Check if content has markdown-style headers."""
        return bool(re.search(r"^#{1,6}\s+.+$", content, re.MULTILINE))

    def _split_by_headers(
        self, content: str, document_id: str, metadata: dict
    ) -> List[ParentChunk]:
        """Split by markdown headers, respecting token limits."""
        # Pattern matches headers like # Title, ## Section, etc.
        header_pattern = r"^(#{1,6})\s+(.+)$"

        sections = []
        current_section = {"title": None, "content": "", "start": 0}

        lines = content.split("\n")
        char_pos = 0

        for line in lines:
            match = re.match(header_pattern, line)

            if match:
                # Save previous section if it has content
                if current_section["content"].strip():
                    sections.append(current_section.copy())

                # Start new section
                current_section = {
                    "title": match.group(2).strip(),
                    "content": line + "\n",
                    "start": char_pos,
                }
            else:
                current_section["content"] += line + "\n"

            char_pos += len(line) + 1  # +1 for newline

        # Don't forget last section
        if current_section["content"].strip():
            sections.append(current_section)

        # Convert to ParentChunks, splitting if too large
        parents = []
        for section in sections:
            section_parents = self._split_large_section(
                section["content"], section["title"], section["start"], document_id, metadata
            )
            parents.extend(section_parents)

        return parents

    def _split_by_paragraphs(
        self, content: str, document_id: str, metadata: dict
    ) -> List[ParentChunk]:
        """Split by double newlines (paragraphs)."""
        paragraphs = re.split(r"\n\n+", content)

        parents = []
        current_content = ""
        current_start = 0
        char_pos = 0

        for para in paragraphs:
            para_tokens = self.estimate_tokens(para)
            current_tokens = self.estimate_tokens(current_content)

            if current_tokens + para_tokens > self.parent_max_tokens and current_content:
                # Emit current parent
                parents.append(
                    ParentChunk(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        content=current_content.strip(),
                        start_char=current_start,
                        end_char=current_start + len(current_content),
                        token_count=current_tokens,
                        metadata=metadata.copy(),
                    )
                )
                current_content = para + "\n\n"
                current_start = char_pos
            else:
                current_content += para + "\n\n"

            char_pos += len(para) + 2  # +2 for double newline

        # Final parent
        if current_content.strip():
            parents.append(
                ParentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    content=current_content.strip(),
                    start_char=current_start,
                    end_char=current_start + len(current_content),
                    token_count=self.estimate_tokens(current_content),
                    metadata=metadata.copy(),
                )
            )

        return parents

    def _split_large_section(
        self, content: str, title: Optional[str], start_char: int, document_id: str, metadata: dict
    ) -> List[ParentChunk]:
        """Split an oversized section into multiple parents."""
        tokens = self.estimate_tokens(content)

        if tokens <= self.parent_max_tokens:
            return [
                ParentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    content=content.strip(),
                    start_char=start_char,
                    end_char=start_char + len(content),
                    section_title=title,
                    token_count=tokens,
                    metadata=metadata.copy(),
                )
            ]

        # Need to split - use paragraph boundaries
        paragraphs = re.split(r"\n\n+", content)
        parents = []
        current = ""
        current_start = start_char
        part = 1

        for para in paragraphs:
            if self.estimate_tokens(current + para) > self.parent_max_tokens and current:
                parents.append(
                    ParentChunk(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        content=current.strip(),
                        start_char=current_start,
                        end_char=current_start + len(current),
                        section_title=f"{title} (Part {part})" if title else None,
                        token_count=self.estimate_tokens(current),
                        metadata=metadata.copy(),
                    )
                )
                part += 1
                current_start += len(current)
                current = para + "\n\n"
            else:
                current += para + "\n\n"

        if current.strip():
            parents.append(
                ParentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    content=current.strip(),
                    start_char=current_start,
                    end_char=current_start + len(current),
                    section_title=f"{title} (Part {part})" if title and part > 1 else title,
                    token_count=self.estimate_tokens(current),
                    metadata=metadata.copy(),
                )
            )

        return parents

    def _create_child_chunks(self, parent: ParentChunk, document_id: str) -> List[ChildChunk]:
        """Split parent into small, overlapping child chunks."""
        # Simple sentence splitting (could use NLTK/spaCy for better results)
        sentences = self._split_sentences(parent.content)

        children = []
        current_sentences = []
        current_tokens = 0
        chunk_index = 0

        for sentence in sentences:
            sent_tokens = self.estimate_tokens(sentence)

            # Check if adding this sentence exceeds target
            if current_tokens + sent_tokens > self.child_target_tokens and current_sentences:
                # Emit child chunk
                child_content = " ".join(current_sentences)
                child_start = parent.start_char + parent.content.find(current_sentences[0])

                children.append(
                    ChildChunk(
                        id=str(uuid.uuid4()),
                        parent_id=parent.id,
                        document_id=document_id,
                        content=child_content,
                        start_char=child_start,
                        end_char=child_start + len(child_content),
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

                # Overlap: keep sentences that fit in overlap budget
                overlap_sentences = []
                overlap_tokens = 0
                for s in reversed(current_sentences):
                    s_tokens = self.estimate_tokens(s)
                    if overlap_tokens + s_tokens <= self.child_overlap_tokens:
                        overlap_sentences.insert(0, s)
                        overlap_tokens += s_tokens
                    else:
                        break

                current_sentences = overlap_sentences
                current_tokens = overlap_tokens

            current_sentences.append(sentence)
            current_tokens += sent_tokens

        # Final child chunk
        if current_sentences:
            child_content = " ".join(current_sentences)
            child_start = parent.start_char + parent.content.find(current_sentences[0])

            children.append(
                ChildChunk(
                    id=str(uuid.uuid4()),
                    parent_id=parent.id,
                    document_id=document_id,
                    content=child_content,
                    start_char=child_start,
                    end_char=child_start + len(child_content),
                    chunk_index=chunk_index,
                )
            )

        return children

    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences.
        Simple regex-based approach; can be upgraded to NLTK/spaCy.
        """
        # Handle common abbreviations
        text = re.sub(r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr)\.\s", r"\1<DOT> ", text)
        text = re.sub(r"\b(vs|etc|e\.g|i\.e)\.\s", r"\1<DOT> ", text)

        # Split on sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)

        # Restore dots
        sentences = [s.replace("<DOT>", ".") for s in sentences]

        # Filter empty
        return [s.strip() for s in sentences if s.strip()]


class ParentChildRetriever:
    """
    Retrieval layer that searches children but returns parents.
    """

    def __init__(self, db, embedder):
        """
        Args:
            db: LanceDB connection
            embedder: Embedding function (text -> vector)
        """
        self.db = db
        self.embedder = embedder
        self.parent_table = db.open_table("parent_chunks")
        self.child_table = db.open_table("child_chunks")

    async def search(
        self, query: str, k: int = 5, child_oversample: int = 3, filters: Optional[dict] = None
    ) -> List[dict]:
        """
        Search children, return parents with match context.

        Args:
            query: Search query
            k: Number of parent chunks to return
            child_oversample: How many children to search per desired parent
            filters: Optional metadata filters

        Returns:
            List of parent chunks with matched child info
        """
        # Step 1: Embed query
        query_vector = await self.embedder(query)

        # Step 2: Search children
        search = self.child_table.search(query_vector).limit(k * child_oversample)

        if filters:
            search = search.where(build_filter_clause(filters))

        child_results = search.to_list()

        # Step 3: Deduplicate by parent, keep best score per parent
        parent_scores = {}
        for child in child_results:
            pid = child["parent_id"]
            score = child["_distance"]

            if pid not in parent_scores or score < parent_scores[pid]["score"]:
                parent_scores[pid] = {
                    "parent_id": pid,
                    "score": score,
                    "matched_child_content": child["content"],
                    "matched_child_id": child["id"],
                }

        # Step 4: Sort by score, take top k
        top_parents = sorted(parent_scores.values(), key=lambda x: x["score"])[:k]

        # Step 5: Fetch parent content
        results = []
        for p in top_parents:
            parent_rows = (
                self.parent_table.search()
                .where(build_eq_clause("id", p["parent_id"]))
                .limit(1)
                .to_list()
            )

            if parent_rows:
                parent = parent_rows[0]
                results.append(
                    {
                        "content": parent["content"],
                        "matched_snippet": p["matched_child_content"],
                        "score": p["score"],
                        "parent_id": p["parent_id"],
                        "document_id": parent["document_id"],
                        "section_title": parent.get("section_title"),
                        "metadata": json.loads(parent.get("metadata", "{}")),
                    }
                )

        return results


# Convenience function for creating tables
def create_parent_child_tables(db) -> Tuple:
    """
    Create or get parent and child chunk tables in LanceDB.

    Returns:
        Tuple of (parent_table, child_table)
    """
    import pyarrow as pa

    parent_schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("section_title", pa.string()),
            pa.field("start_char", pa.int64()),
            pa.field("end_char", pa.int64()),
            pa.field("token_count", pa.int32()),
            pa.field("metadata", pa.string()),
        ]
    )

    child_schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("parent_id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIMENSIONS)),
            pa.field("start_char", pa.int64()),
            pa.field("end_char", pa.int64()),
            pa.field("chunk_index", pa.int32()),
        ]
    )

    # Create tables if they don't exist
    if "parent_chunks" in db.table_names():
        parent_table = db.open_table("parent_chunks")
    else:
        parent_table = db.create_table("parent_chunks", schema=parent_schema)

    if "child_chunks" in db.table_names():
        child_table = db.open_table("child_chunks")
    else:
        child_table = db.create_table("child_chunks", schema=child_schema)

    return parent_table, child_table
