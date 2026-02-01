"""
MCP Tools with Debug Mode

Provides tools for Claude/Antigravity agents to interact with the PKM system.
Includes debug mode for observability when tuning retrieval.
"""

import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class DebugContext:
    """Debug information for search results."""
    raw_chunks: List[str]           # First 500 chars of each chunk
    vector_scores: List[float]      # Similarity scores
    fts_scores: List[Optional[float]]  # Keyword match scores
    rerank_applied: bool
    rerank_scores: List[Optional[float]]
    parent_ids: List[str]
    chunk_ids: List[str]
    query_embedding_sample: List[float]  # First 10 dims of query vector
    retrieval_time_ms: float
    rerank_time_ms: Optional[float]


@dataclass
class SearchResultWithDebug:
    """Search result with optional debug context."""
    content: str
    document_id: str
    source_path: str
    section_title: Optional[str]
    score: float
    citation: str
    debug: Optional[DebugContext] = None


class PKMTools:
    """
    MCP tools for the PKM system.

    These tools are exposed to Claude/Antigravity agents via FastMCP.
    """

    def __init__(
        self,
        retriever,
        embedder,
        reranker=None,
        db=None,
        vault_root: Optional[Path] = None
    ):
        self.retriever = retriever
        self.embedder = embedder
        self.reranker = reranker
        self.db = db
        self.vault_root = vault_root or Path.cwd()

    async def search_knowledge(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        use_reranker: bool = True,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Search the knowledge base semantically.

        Args:
            query: Natural language query
            k: Number of results to return
            filters: Optional metadata filters (file_type, date_range, etc.)
            use_reranker: Whether to apply cross-encoder re-ranking
            debug: Include raw retrieval context for debugging

        Returns:
            Dict with 'results' list and optional '_debug' context
        """
        import time
        start_time = time.time()

        # Embed query
        query_vector = await self.embedder(query)

        # Initial retrieval
        candidates = await self.retriever.search(
            query=query,
            query_vector=query_vector,
            k=k * 10 if use_reranker else k,  # Oversample for reranking
            filters=filters
        )

        retrieval_time = (time.time() - start_time) * 1000
        rerank_time = None

        # Re-ranking
        if use_reranker and self.reranker and len(candidates) > k:
            rerank_start = time.time()
            reranked = self.reranker.rerank(
                query=query,
                candidates=[
                    {
                        "id": c.get("parent_id", c.get("id")),
                        "content": c["content"],
                        "document_id": c["document_id"],
                        "score": c.get("score", c.get("rrf_score", 0)),
                        "metadata": c.get("metadata", {})
                    }
                    for c in candidates
                ],
                top_k=k
            )
            rerank_time = (time.time() - rerank_start) * 1000
            final_results = reranked
        else:
            final_results = candidates[:k]

        # Format results
        results = []
        for i, r in enumerate(final_results):
            # Handle different result types
            if hasattr(r, "content"):
                content = r.content
                doc_id = r.document_id
                score = r.rerank_score if hasattr(r, "rerank_score") else r.score
                metadata = r.metadata if hasattr(r, "metadata") else {}
            else:
                content = r.get("content", "")
                doc_id = r.get("document_id", "")
                score = r.get("rerank_score", r.get("score", 0))
                metadata = r.get("metadata", {})

            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            source_path = metadata.get("source_path", doc_id)
            section_title = metadata.get("section_title", r.get("section_title"))

            results.append({
                "content": content,
                "document_id": doc_id,
                "source_path": source_path,
                "section_title": section_title,
                "score": score,
                "citation": f"[{Path(source_path).name}]({source_path})"
            })

        response = {"results": results}

        # Add debug context
        if debug:
            response["_debug"] = {
                "raw_chunks": [c.get("content", "")[:500] for c in candidates[:10]],
                "vector_scores": [c.get("score", c.get("_distance", 0)) for c in candidates[:10]],
                "fts_scores": [c.get("fts_score") for c in candidates[:10]],
                "rerank_applied": use_reranker and self.reranker is not None,
                "parent_ids": [c.get("parent_id", c.get("id", "")) for c in candidates[:10]],
                "query_embedding_sample": list(query_vector[:10]),
                "retrieval_time_ms": retrieval_time,
                "rerank_time_ms": rerank_time,
                "total_candidates": len(candidates)
            }

        return response

    async def get_document(
        self,
        document_id: str,
        include_chunks: bool = False
    ) -> Dict[str, Any]:
        """
        Get a specific document by ID.

        Args:
            document_id: Document identifier
            include_chunks: Whether to include all chunks

        Returns:
            Document content and metadata
        """
        try:
            # Query parent chunks table
            table = self.db.open_table("parent_chunks")
            results = table.search().where(
                f"document_id = '{document_id}'"
            ).to_list()

            if not results:
                return {"error": f"Document not found: {document_id}"}

            # Combine chunks into full document
            chunks = sorted(results, key=lambda x: x.get("start_char", 0))
            full_content = "\n\n".join(c["content"] for c in chunks)

            response = {
                "document_id": document_id,
                "content": full_content,
                "metadata": json.loads(chunks[0].get("metadata", "{}"))
            }

            if include_chunks:
                response["chunks"] = [
                    {
                        "id": c["id"],
                        "content": c["content"],
                        "section_title": c.get("section_title"),
                        "start_char": c.get("start_char"),
                        "end_char": c.get("end_char")
                    }
                    for c in chunks
                ]

            return response

        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return {"error": str(e)}

    async def list_recent_files(
        self,
        days: int = 7,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List recently modified/added files.

        Metacognition tool: Helps agents understand what's been worked on recently.

        Args:
            days: Number of days to look back
            limit: Maximum files to return

        Returns:
            List of recent files with metadata
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_files = []

        try:
            for path in self.vault_root.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)

                    if mtime >= cutoff:
                        recent_files.append({
                            "path": str(path.relative_to(self.vault_root)),
                            "name": path.name,
                            "modified": mtime.isoformat(),
                            "size_bytes": stat.st_size,
                            "type": path.suffix.lower()
                        })

            # Sort by modification time, most recent first
            recent_files.sort(key=lambda x: x["modified"], reverse=True)

            return recent_files[:limit]

        except Exception as e:
            logger.error(f"Error listing recent files: {e}")
            return []

    async def get_folder_structure(
        self,
        path: str = "",
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """
        Get folder structure for navigation.

        Metacognition tool: Prevents agents from searching for "Project Alpha"
        when the folder is actually named "Project Alpha v2".

        Args:
            path: Relative path within vault (empty = root)
            max_depth: Maximum depth to traverse

        Returns:
            Nested structure of folders and files
        """
        target = self.vault_root / path if path else self.vault_root

        if not target.exists():
            return {"error": f"Path not found: {path}"}

        def build_tree(current: Path, depth: int) -> Dict:
            if depth > max_depth:
                return {"_truncated": True}

            result = {
                "name": current.name or str(self.vault_root),
                "type": "directory",
                "children": []
            }

            try:
                for item in sorted(current.iterdir()):
                    if item.name.startswith("."):
                        continue  # Skip hidden files

                    if item.is_dir():
                        result["children"].append(build_tree(item, depth + 1))
                    else:
                        result["children"].append({
                            "name": item.name,
                            "type": "file",
                            "extension": item.suffix.lower()
                        })

            except PermissionError:
                result["_permission_denied"] = True

            return result

        return build_tree(target, 0)

    async def get_related_documents(
        self,
        document_id: str,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find documents related to a given document.

        Uses the document's embedding to find similar content.

        Args:
            document_id: Source document ID
            k: Number of related documents to find

        Returns:
            List of related documents
        """
        try:
            # Get document embedding (average of chunk embeddings)
            child_table = self.db.open_table("child_chunks")
            chunks = child_table.search().where(
                f"document_id = '{document_id}'"
            ).limit(100).to_list()

            if not chunks:
                return []

            # Average the embeddings
            import numpy as np
            embeddings = [c["vector"] for c in chunks if "vector" in c]
            if not embeddings:
                return []

            avg_embedding = np.mean(embeddings, axis=0).tolist()

            # Search for similar documents
            results = await self.retriever.search(
                query="",  # Empty query, using vector directly
                query_vector=avg_embedding,
                k=k + 1  # +1 because source doc might be in results
            )

            # Filter out the source document
            related = [
                {
                    "document_id": r.get("document_id"),
                    "source_path": r.get("metadata", {}).get("source_path"),
                    "score": r.get("score", 0),
                    "snippet": r.get("content", "")[:200]
                }
                for r in results
                if r.get("document_id") != document_id
            ][:k]

            return related

        except Exception as e:
            logger.error(f"Error finding related documents: {e}")
            return []

    async def get_context_for_topic(
        self,
        topic: str,
        max_tokens: int = 4000
    ) -> Dict[str, Any]:
        """
        Get comprehensive context for a topic.

        Aggregates relevant chunks up to a token limit, suitable for
        injecting into an LLM's context window.

        Args:
            topic: Topic to gather context for
            max_tokens: Maximum tokens worth of context

        Returns:
            Aggregated context with citations
        """
        # Search with higher k
        results = await self.search_knowledge(
            query=topic,
            k=20,
            use_reranker=True
        )

        # Aggregate until token limit
        context_parts = []
        citations = []
        estimated_tokens = 0

        for r in results.get("results", []):
            chunk_tokens = len(r["content"]) // 4  # Rough estimate

            if estimated_tokens + chunk_tokens > max_tokens:
                break

            context_parts.append(r["content"])
            citations.append(r["citation"])
            estimated_tokens += chunk_tokens

        return {
            "context": "\n\n---\n\n".join(context_parts),
            "citations": list(set(citations)),
            "estimated_tokens": estimated_tokens,
            "chunk_count": len(context_parts)
        }


# FastMCP registration helper
def register_tools(mcp, tools: PKMTools):
    """Register PKM tools with FastMCP server."""

    @mcp.tool()
    async def search_knowledge(
        query: str,
        k: int = 5,
        filters: dict = None,
        use_reranker: bool = True,
        debug: bool = False
    ) -> dict:
        """Search the knowledge base semantically."""
        return await tools.search_knowledge(query, k, filters, use_reranker, debug)

    @mcp.tool()
    async def get_document(document_id: str, include_chunks: bool = False) -> dict:
        """Get a specific document by ID."""
        return await tools.get_document(document_id, include_chunks)

    @mcp.tool()
    async def list_recent_files(days: int = 7, limit: int = 50) -> list:
        """List recently modified files."""
        return await tools.list_recent_files(days, limit)

    @mcp.tool()
    async def get_folder_structure(path: str = "", max_depth: int = 3) -> dict:
        """Get folder structure for navigation."""
        return await tools.get_folder_structure(path, max_depth)

    @mcp.tool()
    async def get_related_documents(document_id: str, k: int = 5) -> list:
        """Find documents related to a given document."""
        return await tools.get_related_documents(document_id, k)

    @mcp.tool()
    async def get_context_for_topic(topic: str, max_tokens: int = 4000) -> dict:
        """Get comprehensive context for a topic."""
        return await tools.get_context_for_topic(topic, max_tokens)
