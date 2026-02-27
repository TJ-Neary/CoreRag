"""
MCP Tools with Debug Mode

Provides tools for Claude/Antigravity agents to interact with the CoreRag system.
Includes debug mode for observability when tuning retrieval.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import STATE_DIR
from src.exceptions import CoreRagError
from src.search.decay_scoring import apply_decay_to_results
from src.search.multi_query import QueryDecomposer, ReciprocalRankFusion
from src.utils.query_sanitize import build_eq_clause

logger = logging.getLogger(__name__)


@dataclass
class DebugContext:
    """Debug information for search results."""

    raw_chunks: List[str]  # First 500 chars of each chunk
    vector_scores: List[float]  # Similarity scores
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


class CoreRagTools:
    """
    MCP tools for the CoreRag system.

    These tools are exposed to Claude/Antigravity agents via FastMCP.
    """

    def __init__(
        self,
        retriever,
        embedder,
        reranker=None,
        db=None,
        vault_root: Optional[Path] = None,
        hyde_expander=None,
        knowledge_graph=None,
        semantic_cache=None,
        conflict_detector=None,
    ):
        self.retriever = retriever
        self.embedder = embedder
        self.reranker = reranker
        self.db = db
        self.vault_root = vault_root or Path.cwd()
        self._hyde_expander = hyde_expander
        self._knowledge_graph = knowledge_graph
        self._semantic_cache = semantic_cache
        self._conflict_detector = conflict_detector
        self._memory_manager = None
        self._user_profile = None
        self._query_analytics = None
        self._conversation_manager = None

    def _to_dict(self, obj) -> dict:
        """Convert a dataclass or dict result to a plain dict."""
        if isinstance(obj, dict):
            return obj
        return (
            {k: getattr(obj, k) for k in obj.__dataclass_fields__}
            if hasattr(obj, "__dataclass_fields__")
            else vars(obj)
        )

    async def search_knowledge(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        use_reranker: bool = True,
        use_hyde: bool = False,
        use_multi_query: bool = False,
        conversational: bool = False,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """
        Search the knowledge base semantically.

        Args:
            query: Natural language query
            k: Number of results to return
            filters: Optional metadata filters (file_type, date_range, etc.)
            tags: Optional collection tags to filter by (e.g. ["sphr-study"])
            use_reranker: Whether to apply cross-encoder re-ranking
            use_hyde: Whether to use HyDE query expansion
            use_multi_query: Decompose complex queries into sub-queries and fuse
            conversational: Enable multi-turn context-aware query rewriting
            debug: Include raw retrieval context for debugging

        Returns:
            Dict with 'results' list and optional '_debug' context
        """
        import time

        start_time = time.time()

        # Apply conversational query rewriting if enabled
        original_query = query
        if conversational and self._conversation_manager:
            query = self._conversation_manager.rewrite_query(query)

        # Merge tags into filters dict
        if tags:
            filters = dict(filters) if filters else {}
            filters["tags"] = tags

        # Check semantic cache (skip for debug, multi-query, or HyDE — those need fresh results)
        if self._semantic_cache and not debug and not use_multi_query and not use_hyde:
            cached = self._semantic_cache.get(query)
            if cached is not None:
                logger.debug(f"Semantic cache hit for query: {query[:80]}...")
                return {"results": cached, "_cached": True}

        # Multi-query: decompose, run sub-queries, fuse with RRF
        if use_multi_query:
            return await self._multi_query_search(
                query=query,
                k=k,
                filters=filters,
                use_reranker=use_reranker,
                use_hyde=use_hyde,
                debug=debug,
            )

        search_query = query
        hyde_doc = None

        # HyDE: generate hypothetical document, embed that instead
        if use_hyde and self._hyde_expander:
            try:
                if self._hyde_expander.async_llm_generator:
                    hyde_result = await self._hyde_expander.expand_async(query)
                else:
                    hyde_result = self._hyde_expander.expand(query)
                search_query = hyde_result.hypothetical_document
                hyde_doc = search_query
                logger.debug(f"HyDE expanded query: {search_query[:200]}...")
            except Exception as e:
                logger.warning(f"HyDE expansion failed, using original query: {e}")
                search_query = query

        # Embed query (or HyDE hypothetical document)
        query_vector = await self.embedder(search_query)

        # Initial retrieval via HybridSearcher
        candidates_raw = await self.retriever.search(
            query=query,  # Use original query for FTS keyword matching
            query_vector=query_vector,
            k=k * 10 if use_reranker else k,
            filters=filters,
        )

        # Normalize candidates to dicts
        candidates = [self._to_dict(c) for c in candidates_raw]

        retrieval_time = (time.time() - start_time) * 1000
        rerank_time = None

        # Re-ranking with cross-encoder (uses original query, not HyDE)
        if use_reranker and self.reranker and len(candidates) > k:
            rerank_start = time.time()
            reranked = self.reranker.rerank(
                query=query,
                candidates=[
                    {
                        "id": c.get("id", c.get("parent_id", "")),
                        "content": c.get("content", ""),
                        "document_id": c.get("document_id", ""),
                        "score": c.get("rrf_score", c.get("score", 0)),
                        "metadata": c.get("metadata", {}),
                    }
                    for c in candidates
                ],
                top_k=k,
            )
            rerank_time = (time.time() - rerank_start) * 1000
            final_results = reranked
        else:
            final_results = candidates[:k]

        # Apply time-decay scoring (recent documents score higher)
        final_dicts = self._normalize_to_dicts(final_results)
        if final_dicts:
            final_dicts = apply_decay_to_results(final_dicts)

        # Corrective RAG — post-retrieval relevance filtering
        crag_info = None
        try:
            from src.config import CORRECTIVE_RAG_ENABLED

            if CORRECTIVE_RAG_ENABLED and final_dicts:
                from src.search.corrective_rag import CorrectiveRAG

                crag = CorrectiveRAG()
                crag_result = crag.filter_results(query, final_dicts)
                final_dicts = crag_result.results
                crag_info = {
                    "correct": crag_result.correct_count,
                    "ambiguous": crag_result.ambiguous_count,
                    "filtered": crag_result.incorrect_count,
                    "all_filtered": crag_result.all_filtered,
                }
        except Exception as e:
            logger.debug(f"CRAG filtering skipped: {e}")

        # Format results
        results = self._format_results(final_dicts)

        # Enrich with knowledge graph context
        graph_context = self._get_graph_context(final_dicts)

        response: Dict[str, Any] = {"results": results}
        if graph_context:
            response["graph_context"] = graph_context

        # Store in semantic cache
        if self._semantic_cache and results and not debug:
            try:
                self._semantic_cache.put(query, results)
            except Exception as e:
                logger.debug(f"Semantic cache put failed: {e}")

        # Add debug context
        if debug:
            response["_debug"] = {
                "raw_chunks": [c.get("content", "")[:500] for c in candidates[:10]],
                "vector_scores": [
                    c.get("vector_score", c.get("_distance", 0)) for c in candidates[:10]
                ],
                "fts_scores": [c.get("fts_score") for c in candidates[:10]],
                "rerank_applied": use_reranker and self.reranker is not None,
                "hyde_applied": use_hyde and self._hyde_expander is not None,
                "hyde_document": hyde_doc[:200] if hyde_doc else None,
                "crag_applied": crag_info is not None,
                "crag_info": crag_info,
                "decay_applied": True,
                "parent_ids": [c.get("parent_id", c.get("id", "")) for c in candidates[:10]],
                "query_embedding_sample": list(query_vector[:10]),
                "retrieval_time_ms": retrieval_time,
                "rerank_time_ms": rerank_time,
                "total_candidates": len(candidates),
            }

        # Record turn for conversational context
        if conversational and self._conversation_manager:
            self._conversation_manager.add_turn(original_query, response.get("results", []))
            if original_query != query:
                response["_rewritten_query"] = query

        return response

    def _normalize_to_dicts(self, results: List) -> List[Dict]:
        """Convert a list of dataclass or dict results to plain dicts."""
        dicts = []
        for r in results:
            if isinstance(r, dict):
                dicts.append(r)
            elif hasattr(r, "content"):
                d = {
                    "content": r.content,
                    "document_id": getattr(r, "document_id", ""),
                    "score": getattr(r, "rerank_score", None)
                    or getattr(r, "rrf_score", None)
                    or getattr(r, "score", 0),
                    "metadata": getattr(r, "metadata", {}),
                }
                dicts.append(d)
            else:
                dicts.append(self._to_dict(r))
        return dicts

    def _format_results(self, results: List[Dict]) -> List[Dict]:
        """Format result dicts into the standard response format."""
        formatted = []
        for r in results:
            content = r.get("content", "")
            doc_id = r.get("document_id", "")
            score = r.get("score", r.get("rerank_score", r.get("rrf_score", 0)))
            metadata = r.get("metadata", {})

            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}

            source_path = metadata.get("source_path", doc_id)
            section_title = metadata.get("section_title") or r.get("section_title")

            entry = {
                "content": content,
                "document_id": doc_id,
                "source_path": source_path,
                "section_title": section_title,
                "score": float(score) if score is not None else 0.0,
                "citation": f"[{Path(source_path).name}]({source_path})",
            }

            # Enrich with freshness indicator if file is accessible
            try:
                from src.quality.freshness import FreshnessIndicator

                source = Path(source_path) if source_path else None
                if source and source.exists():
                    fi = FreshnessIndicator()
                    info = fi.get_freshness(source)
                    entry["freshness"] = {
                        "level": info.freshness_level.value,
                        "age_days": info.age_days,
                        "is_stale": info.is_stale,
                    }
            except Exception:
                pass  # Freshness enrichment is best-effort

            formatted.append(entry)
        return formatted

    def _get_graph_context(self, results: List[Dict]) -> Dict[str, Any]:
        """Extract related entities and documents from the knowledge graph.

        Runs after reranking. For each result's document_id, finds entities
        in the graph and their 1-hop neighbors. Returns context that helps
        Claude understand relationships between search results.
        """
        if not self._knowledge_graph:
            return {}

        try:
            # Collect document IDs from results
            result_doc_ids = {r.get("document_id", "") for r in results if r.get("document_id")}
            if not result_doc_ids:
                return {}

            # Find entities mentioned in result documents
            mentioned_entities = set()
            for doc_id in result_doc_ids:
                try:
                    related = self._knowledge_graph.find_related_documents(doc_id, limit=5)
                    for rel in related:
                        for entity_name in rel.get("shared_entities", []):
                            mentioned_entities.add(entity_name)
                except Exception:
                    continue

            if not mentioned_entities:
                return {}

            # Find 1-hop neighbors for discovered entities
            related_doc_ids = set()
            neighbor_entities = set()
            for entity in list(mentioned_entities)[:20]:  # Cap to avoid slow queries
                try:
                    neighbors = self._knowledge_graph.get_neighbors(entity)
                    for n in neighbors[:5]:
                        neighbor_entities.add(n.get("entity", n.get("name", "")))
                        if n.get("document_id") and n["document_id"] not in result_doc_ids:
                            related_doc_ids.add(n["document_id"])
                except Exception:
                    continue

            if not mentioned_entities and not related_doc_ids:
                return {}

            return {
                "mentioned_entities": sorted(mentioned_entities)[:15],
                "related_entities": sorted(neighbor_entities - mentioned_entities)[:10],
                "related_documents": sorted(related_doc_ids)[:5],
            }

        except Exception as e:
            logger.debug(f"Graph context enrichment failed: {e}")
            return {}

    async def _multi_query_search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        use_reranker: bool = True,
        use_hyde: bool = False,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """Run multi-query search: decompose, search each sub-query, fuse with RRF."""
        decomposer = QueryDecomposer()
        sub_queries = decomposer.decompose(query)

        logger.info(f"Multi-query: decomposed into {len(sub_queries)} sub-queries")

        # Run each sub-query through the normal search pipeline (sequentially to avoid
        # nested async complexity; sub-queries are typically 2-4)
        query_results: Dict[str, List[Dict]] = {}
        for sq in sub_queries:
            sub_result = await self.search_knowledge(
                query=sq.query,
                k=k * 3,  # Oversample for fusion
                filters=filters,
                use_reranker=use_reranker,
                use_hyde=use_hyde,
                use_multi_query=False,  # Prevent recursion
                debug=False,
            )
            # Convert formatted results back to dicts with source_path as ID
            query_results[sq.query] = sub_result.get("results", [])

        # Fuse with Reciprocal Rank Fusion
        fusion = ReciprocalRankFusion(k=60)
        fused = fusion.fuse(query_results, id_key="source_path", score_key="score")

        # Convert FusedResult dataclasses to response format
        results = []
        for fr in fused[:k]:
            results.append(
                {
                    "content": fr.content,
                    "document_id": fr.metadata.get("document_id", ""),
                    "source_path": fr.source_path,
                    "section_title": fr.metadata.get("section_title"),
                    "score": float(fr.fused_score),
                    "citation": f"[{Path(fr.source_path).name}]({fr.source_path})",
                }
            )

        response: Dict[str, Any] = {"results": results}

        if debug:
            response["_debug"] = {
                "multi_query": True,
                "sub_queries": [sq.query for sq in sub_queries],
                "results_per_sub_query": {sq: len(res) for sq, res in query_results.items()},
                "fusion_method": "reciprocal_rank_fusion",
            }

        return response

    async def get_document(self, document_id: str, include_chunks: bool = False) -> Dict[str, Any]:
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
            results = table.search().where(build_eq_clause("document_id", document_id)).to_list()

            if not results:
                return {"error": f"Document not found: {document_id}"}

            # Combine chunks into full document
            chunks = sorted(results, key=lambda x: x.get("start_char", 0))
            full_content = "\n\n".join(c["content"] for c in chunks)

            response = {
                "document_id": document_id,
                "content": full_content,
                "metadata": json.loads(chunks[0].get("metadata", "{}")),
            }

            if include_chunks:
                response["chunks"] = [
                    {
                        "id": c["id"],
                        "content": c["content"],
                        "section_title": c.get("section_title"),
                        "start_char": c.get("start_char"),
                        "end_char": c.get("end_char"),
                    }
                    for c in chunks
                ]

            return response

        except CoreRagError as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return {"error": str(e)}

    async def list_recent_files(
        self,
        days: int = 7,
        limit: int = 50,
        file_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List recently modified/added files.

        Metacognition tool: Helps agents understand what's been worked on recently.

        Args:
            days: Number of days to look back
            limit: Maximum files to return
            file_types: Optional list of extensions to filter (e.g. ["md", "pdf"])

        Returns:
            List of recent files with metadata
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_files = []
        allowed_extensions = {f".{t.lstrip('.')}" for t in file_types} if file_types else None

        try:
            for path in self.vault_root.rglob("*"):
                if path.is_file():
                    if allowed_extensions and path.suffix.lower() not in allowed_extensions:
                        continue
                    stat = path.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)

                    if mtime >= cutoff:
                        recent_files.append(
                            {
                                "path": str(path.relative_to(self.vault_root)),
                                "name": path.name,
                                "modified": mtime.isoformat(),
                                "size_bytes": stat.st_size,
                                "type": path.suffix.lower(),
                            }
                        )

            recent_files.sort(key=lambda x: str(x["modified"]), reverse=True)
            return recent_files[:limit]

        except CoreRagError as e:
            logger.error(f"Error listing recent files: {e}")
            return []
        except Exception as e:
            logger.error(f"Error listing recent files: {e}")
            return []

    async def get_folder_structure(self, path: str = "", max_depth: int = 3) -> Dict[str, Any]:
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

            result: Dict[str, Any] = {
                "name": current.name or str(self.vault_root),
                "type": "directory",
                "children": [],
            }

            try:
                for item in sorted(current.iterdir()):
                    if item.name.startswith("."):
                        continue  # Skip hidden files

                    if item.is_dir():
                        result["children"].append(build_tree(item, depth + 1))
                    else:
                        result["children"].append(
                            {"name": item.name, "type": "file", "extension": item.suffix.lower()}
                        )

            except PermissionError:
                result["_permission_denied"] = True

            return result

        return build_tree(target, 0)

    async def get_related_documents(self, document_id: str, k: int = 5) -> List[Dict[str, Any]]:
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
            chunks = (
                child_table.search()
                .where(build_eq_clause("document_id", document_id))
                .limit(100)
                .to_list()
            )

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
                k=k + 1,  # +1 because source doc might be in results
            )

            # Filter out the source document
            related = [
                {
                    "document_id": r.get("document_id"),
                    "source_path": r.get("metadata", {}).get("source_path"),
                    "score": r.get("score", 0),
                    "snippet": r.get("content", "")[:200],
                }
                for r in results
                if r.get("document_id") != document_id
            ][:k]

            return related

        except CoreRagError as e:
            logger.error(f"Error finding related documents: {e}")
            return []
        except Exception as e:
            logger.error(f"Error finding related documents: {e}")
            return []

    async def get_context_for_topic(self, topic: str, max_tokens: int = 4000) -> Dict[str, Any]:
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
        results = await self.search_knowledge(query=topic, k=20, use_reranker=True)

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
            "chunk_count": len(context_parts),
        }

    # ── Knowledge Graph ──────────────────────────────────────────────────────

    async def search_by_entity(
        self,
        entity_name: str,
        relationship_type: Optional[str] = None,
        max_hops: int = 2,
    ) -> Dict[str, Any]:
        """Search using the knowledge graph for entity relationships."""
        if not self._knowledge_graph:
            # No graph available — fall back to semantic search
            results = await self.search_knowledge(query=entity_name, k=5, use_reranker=True)
            return {
                "entity": entity_name,
                "graph_available": False,
                "fallback": "semantic_search",
                "results": results.get("results", []),
            }

        # Query the knowledge graph
        rel_types = [relationship_type] if relationship_type else None
        neighbors = self._knowledge_graph.get_neighbors(
            entity_name, relationship_types=rel_types, direction="both"
        )

        if not neighbors:
            # Entity not in graph — fall back to semantic search
            results = await self.search_knowledge(query=entity_name, k=5, use_reranker=True)
            return {
                "entity": entity_name,
                "graph_available": True,
                "entity_found": False,
                "fallback": "semantic_search",
                "results": results.get("results", []),
            }

        # Group neighbors by relationship type
        by_relationship: Dict[str, list] = {}
        for n in neighbors:
            rel = n["relationship"]
            if rel not in by_relationship:
                by_relationship[rel] = []
            by_relationship[rel].append(
                {
                    "entity": n["entity"],
                    "direction": n["direction"],
                    "document_id": n["document_id"],
                    "confidence": n["confidence"],
                }
            )

        stats = self._knowledge_graph.get_stats()

        return {
            "entity": entity_name,
            "graph_available": True,
            "entity_found": True,
            "relationships": by_relationship,
            "total_connections": len(neighbors),
            "graph_stats": {
                "total_entities": stats["total_entities"],
                "total_relationships": stats["total_relationships"],
            },
        }

    # ── Episodic Memory ─────────────────────────────────────────────────────

    def _ensure_memory(self):
        """Lazily initialize memory manager and load user profile."""
        if self._memory_manager is None:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            self._memory_manager = EpisodicMemoryManager(storage_path)
            self._user_profile = self._memory_manager.load_or_create("default")

    async def get_user_context(self) -> Dict[str, Any]:
        """Get user profile and episodic memory context."""
        self._ensure_memory()

        assert self._user_profile is not None
        profile = self._user_profile

        # Get correction patterns from correction log
        correction_summary: Dict[str, Any] = {}
        try:
            from src.correction_log import _load_corrections

            corrections = _load_corrections()
            if corrections:
                # Aggregate correction patterns
                folder_changes = []
                filename_changes = []
                for c in corrections[-20:]:
                    corr = c.get("corrections", {})
                    if "target_folder" in corr:
                        folder_changes.append(
                            f"{corr['target_folder']['ai']} -> {corr['target_folder']['human']}"
                        )
                    if "filename" in corr:
                        filename_changes.append(
                            f"{corr['filename']['ai']} -> {corr['filename']['human']}"
                        )
                if folder_changes:
                    correction_summary["folder_patterns"] = folder_changes[-5:]
                if filename_changes:
                    correction_summary["filename_patterns"] = filename_changes[-5:]
                correction_summary["total_corrections"] = len(corrections)
        except Exception as e:
            logger.warning(f"Failed to load correction patterns: {e}")

        return {
            "facts": [
                {"fact": f.content, "category": f.category.value, "confidence": f.confidence}
                for f in profile.facts
            ],
            "preferences": profile.preferences,
            "correction_patterns": correction_summary,
            "user_name": profile.name,
        }

    async def add_user_fact(
        self,
        fact: str,
        category: str = "general",
    ) -> Dict[str, Any]:
        """Add a fact about the user to episodic memory."""
        self._ensure_memory()

        from datetime import datetime

        from src.memory.episodic_memory import FactCategory, UserFact

        # Map string category to FactCategory enum
        category_map = {
            "general": FactCategory.PERSONAL,
            "personal": FactCategory.PERSONAL,
            "preference": FactCategory.PREFERENCE,
            "life_event": FactCategory.LIFE_EVENT,
            "project": FactCategory.PROJECT,
            "relationship": FactCategory.RELATIONSHIP,
            "technical": FactCategory.TECHNICAL,
            "health": FactCategory.HEALTH,
            "work": FactCategory.WORK,
        }
        fact_category = category_map.get(category.lower(), FactCategory.PERSONAL)

        now = datetime.now().isoformat()
        user_fact = UserFact(
            content=fact,
            category=fact_category,
            confidence=1.0,
            source="explicit",
            created_at=now,
            updated_at=now,
        )

        assert self._memory_manager is not None
        assert self._user_profile is not None
        self._memory_manager.add_fact(self._user_profile, user_fact)
        logger.info(f"Stored user fact: [{fact_category.value}] {fact}")

        return {
            "stored": True,
            "fact": fact,
            "category": fact_category.value,
            "total_facts": len(self._user_profile.facts),
        }

    # ── Conflict Detection ────────────────────────────────────────────────────

    async def detect_conflicts(
        self,
        path: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Scan documents for contradictions, numeric mismatches, and outdated info."""
        if not self._conflict_detector:
            return {"error": "Conflict detector not initialized"}

        try:
            scan_path = Path(path) if path else self.vault_root
            if not scan_path.exists():
                return {"error": f"Path not found: {scan_path}"}

            report = self._conflict_detector.scan_directory(scan_path, recursive=True)

            return {
                "path": str(scan_path),
                "documents_analyzed": report.documents_analyzed,
                "conflicts_found": report.conflicts_found,
                "by_type": report.by_type,
                "by_severity": report.by_severity,
                "conflicts": [
                    {
                        "type": c.conflict_type.value,
                        "severity": c.severity.value,
                        "description": c.description,
                        "topic": c.topic,
                        "confidence": c.confidence,
                        "evidence_a": {
                            "file": c.evidence_a.file_path,
                            "content": c.evidence_a.content[:300],
                        },
                        "evidence_b": {
                            "file": c.evidence_b.file_path,
                            "content": c.evidence_b.content[:300],
                        },
                        "resolution": c.resolution_suggestion,
                    }
                    for c in report.conflicts[:limit]
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Ingestion Tools ────────────────────────────────────────────────────────

    async def trigger_reindex(
        self,
        path: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Trigger re-indexing of files in the vault."""
        try:
            from src.utils.checkpoint import CheckpointManager

            scan_path = Path(path) if path else self.vault_root
            if not scan_path.exists():
                return {"error": f"Path not found: {scan_path}"}

            # Collect indexable files
            supported_exts = {
                ".md",
                ".txt",
                ".pdf",
                ".docx",
                ".json",
                ".yaml",
                ".csv",
                ".log",
                ".png",
                ".jpg",
                ".jpeg",
                ".tiff",
                ".webp",
                ".bmp",
                ".heic",
            }
            files = []
            if scan_path.is_file():
                files = [scan_path]
            else:
                for f in scan_path.rglob("*"):
                    if f.is_file() and f.suffix.lower() in supported_exts:
                        files.append(f)

            if not files:
                return {
                    "status": "no_files",
                    "path": str(scan_path),
                    "message": "No indexable files found",
                }

            # If not forcing, filter to files not already indexed
            if not force and self.db:
                try:
                    child_table = self.db.open_table("child_chunks")
                    indexed = {
                        r["source_path"]
                        for r in child_table.search()
                        .select(["source_path"])
                        .limit(100000)
                        .to_list()
                    }
                    files = [f for f in files if f.name not in indexed]
                except Exception:
                    pass  # Table may not exist yet

            # Create checkpoint job
            cm = CheckpointManager()
            job = cm.create_job("reindex", files, config={"force": force, "path": str(scan_path)})

            return {
                "status": "queued",
                "job_id": job.job_id,
                "total_files": len(files),
                "path": str(scan_path),
                "force": force,
                "message": f"Reindex job created with {len(files)} files. Use get_ingestion_queue to monitor progress.",
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_ingestion_queue(self) -> Dict[str, Any]:
        """Get current ingestion queue status."""
        # Phase 9 will wire this to src/utils/queue_manager.py
        # For now, read from the staging manifest if available
        try:
            manifest_path = Path(__file__).resolve().parent.parent.parent / "staging_manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                pending = sum(1 for v in manifest.values() if v.get("status") == "pending")
                processing = sum(1 for v in manifest.values() if v.get("status") == "processing")
                completed = sum(1 for v in manifest.values() if v.get("status") == "completed")
                return {
                    "pending": pending,
                    "processing": processing,
                    "completed": completed,
                    "total": len(manifest),
                }
        except Exception as e:
            logger.error(f"Error reading ingestion queue: {e}")

        return {"pending": 0, "processing": 0, "completed": 0, "total": 0}

    # === Document Versioning ===

    async def get_document_history(self, document_id: str, limit: int = 10) -> Dict[str, Any]:
        """Get version history for a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        history = vm.get_history(document_id, limit=limit)
        total = len(vm.get_versions(document_id))
        return {"document_id": document_id, "versions": history, "total": total}

    async def get_document_diff(
        self, document_id: str, from_version: int, to_version: int
    ) -> Dict[str, Any]:
        """Get diff between two versions of a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        diff = vm.get_diff(document_id, from_version, to_version)
        if not diff:
            return {"error": "Version(s) not found"}
        return {
            "from_version": from_version,
            "to_version": to_version,
            "additions": diff.additions,
            "deletions": diff.deletions,
            "summary": diff.summary,
            "diff_lines": diff.diff_lines[:50],
        }

    async def restore_document_version(
        self, document_id: str, version_number: int
    ) -> Dict[str, Any]:
        """Restore a previous version of a document."""
        from src.utils.versioning import VersionManager

        vm = VersionManager()
        restored = vm.restore_version(document_id, version_number)
        if not restored:
            return {"error": f"Version {version_number} not found"}
        return {
            "success": True,
            "new_version": restored.version_number,
            "restored_from": version_number,
        }

    # === Knowledge Gaps ===

    async def analyze_knowledge_gaps(self) -> Dict[str, Any]:
        """Analyze the knowledge base for gaps and improvement opportunities."""
        from src.analytics.gaps_analyzer import GapsAnalyzer

        analyzer = GapsAnalyzer(
            analytics=self._query_analytics,
            db=self.db,
        )
        return analyzer.get_comprehensive_analysis()

    # === Golden Set Management ===

    async def get_golden_suggestions(self, limit: int = 10) -> Dict[str, Any]:
        """Get analytics-based suggestions for golden set entries."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        suggestions = mgr.get_suggestions(limit=limit)
        return {
            "suggestions": suggestions,
            "count": len(suggestions),
            "current_entries": mgr.entry_count,
        }

    async def approve_golden_suggestion(self, query: str) -> Dict[str, Any]:
        """Approve a golden set suggestion from analytics."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        success = mgr.approve_suggestion(query)
        if success:
            return {"status": "approved", "query": query, "total_entries": mgr.entry_count}
        return {"status": "failed", "error": f"Query not found in suggestions: {query}"}

    async def list_golden_entries(
        self, limit: int = 50, source: Optional[str] = None
    ) -> Dict[str, Any]:
        """List current golden set entries."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        entries = mgr.list_entries(source_filter=source, limit=limit)
        return {"entries": entries, "total": mgr.entry_count}

    # === Multi-Vault Support ===

    async def list_vaults(self) -> Dict[str, Any]:
        """List configured Obsidian vaults."""
        from src.config import VAULT_PATHS

        return {
            "vaults": {
                name: {"path": str(path), "exists": path.exists()}
                for name, path in VAULT_PATHS.items()
            }
        }

    # === External Integrations ===

    async def list_integrations(self) -> Dict[str, Any]:
        """List available integration plugins and their status."""
        integrations = []
        try:
            from src.integrations.readwise import ReadwisePlugin

            rw = ReadwisePlugin()
            integrations.append(
                {
                    "name": rw.name(),
                    "connected": rw.check_connection(),
                    "config": rw.get_config_schema(),
                }
            )
        except Exception as e:
            logger.debug(f"Readwise plugin unavailable: {e}")
        return {"integrations": integrations}

    async def sync_integration(self, name: str) -> Dict[str, Any]:
        """Run a sync cycle for a named integration."""
        if name == "readwise":
            from src.integrations.readwise import ReadwisePlugin

            plugin = ReadwisePlugin()
            if not plugin.check_connection():
                return {
                    "status": "error",
                    "error": "Readwise not connected (check READWISE_API_TOKEN)",
                }
            return plugin.sync()
        return {"status": "error", "error": f"Unknown integration: {name}"}
