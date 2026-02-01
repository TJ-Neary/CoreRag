"""
Chunking strategies for document processing.

This module provides intelligent chunking that solves the
retrieval-generation mismatch problem in RAG systems.
"""

from .parent_child import (
    ParentChunk,
    ChildChunk,
    ParentChildChunker,
    ParentChildRetriever,
    create_parent_child_tables,
)

__all__ = [
    "ParentChunk",
    "ChildChunk",
    "ParentChildChunker",
    "ParentChildRetriever",
    "create_parent_child_tables",
]
