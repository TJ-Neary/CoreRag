"""
MCP Tools with Debug Mode

Provides tools for Claude/Antigravity agents to interact with the CoreRag system.
Includes debug mode for observability when tuning retrieval.
"""

import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import json

from src.search.decay_scoring import apply_decay_to_results
from src.search.multi_query import QueryDecomposer, ReciprocalRankFusion

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

    def _to_dict(self, obj) -> dict:
        """Convert a dataclass or dict result to a plain dict."""
        if isinstance(obj, dict):
            return obj
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__} if hasattr(obj, "__dataclass_fields__") else vars(obj)

    async def search_knowledge(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        use_reranker: bool = True,
        use_hyde: bool = False,
        use_multi_query: bool = False,
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
            debug: Include raw retrieval context for debugging

        Returns:
            Dict with 'results' list and optional '_debug' context
        """
        import time
        start_time = time.time()

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
                query=query, k=k, filters=filters,
                use_reranker=use_reranker, use_hyde=use_hyde, debug=debug,
            )

        search_query = query
        hyde_doc = None

        # HyDE: generate hypothetical document, embed that instead
        if use_hyde and self._hyde_expander:
            try:
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

        # Format results
        results = self._format_results(final_dicts)

        response = {"results": results}

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
                "decay_applied": True,
                "parent_ids": [c.get("parent_id", c.get("id", "")) for c in candidates[:10]],
                "query_embedding_sample": list(query_vector[:10]),
                "retrieval_time_ms": retrieval_time,
                "rerank_time_ms": rerank_time,
                "total_candidates": len(candidates),
            }

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
            results.append({
                "content": fr.content,
                "document_id": fr.metadata.get("document_id", ""),
                "source_path": fr.source_path,
                "section_title": fr.metadata.get("section_title"),
                "score": float(fr.fused_score),
                "citation": f"[{Path(fr.source_path).name}]({fr.source_path})",
            })

        response = {"results": results}

        if debug:
            response["_debug"] = {
                "multi_query": True,
                "sub_queries": [sq.query for sq in sub_queries],
                "results_per_sub_query": {
                    sq: len(res) for sq, res in query_results.items()
                },
                "fusion_method": "reciprocal_rank_fusion",
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
        allowed_extensions = (
            {f".{t.lstrip('.')}" for t in file_types} if file_types else None
        )

        try:
            for path in self.vault_root.rglob("*"):
                if path.is_file():
                    if allowed_extensions and path.suffix.lower() not in allowed_extensions:
                        continue
                    stat = path.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)

                    if mtime >= cutoff:
                        recent_files.append({
                            "path": str(path.relative_to(self.vault_root)),
                            "name": path.name,
                            "modified": mtime.isoformat(),
                            "size_bytes": stat.st_size,
                            "type": path.suffix.lower(),
                        })

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
            by_relationship[rel].append({
                "entity": n["entity"],
                "direction": n["direction"],
                "document_id": n["document_id"],
                "confidence": n["confidence"],
            })

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
            storage_path = Path.home() / ".corerag" / "profiles"
            self._memory_manager = EpisodicMemoryManager(storage_path)
            self._user_profile = self._memory_manager.load_or_create("default")

    async def get_user_context(self) -> Dict[str, Any]:
        """Get user profile and episodic memory context."""
        self._ensure_memory()

        profile = self._user_profile

        # Get correction patterns from correction log
        correction_summary = {}
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

        from src.memory.episodic_memory import UserFact, FactCategory
        from datetime import datetime

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
                ".md", ".txt", ".pdf", ".docx", ".json", ".yaml", ".csv", ".log",
                ".png", ".jpg", ".jpeg", ".tiff", ".webp", ".bmp", ".heic",
            }
            files = []
            if scan_path.is_file():
                files = [scan_path]
            else:
                for f in scan_path.rglob("*"):
                    if f.is_file() and f.suffix.lower() in supported_exts:
                        files.append(f)

            if not files:
                return {"status": "no_files", "path": str(scan_path), "message": "No indexable files found"}

            # If not forcing, filter to files not already indexed
            if not force and self.db:
                try:
                    child_table = self.db.open_table("child_chunks")
                    indexed = {r["source_path"] for r in child_table.search().select(["source_path"]).limit(100000).to_list()}
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
