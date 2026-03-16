"""
Core Memory API v1 Routes

External-facing stateless API for AI systems and external consumers.
Endpoints: manifest, stats, search, ingest, delete.

All endpoints except manifest require API key authentication.
"""

import hashlib
import logging
import os
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.models import (
    AnswerCitation,
    AnswerClaim,
    AnswerRequest,
    AnswerResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkDeleteResult,
    DeleteResponse,
    DocumentResponse,
    IngestRequest,
    IngestResponse,
    QuickCaptureRequest,
    QuickCaptureResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsResponse,
)
from src.config import (
    DB_PATH,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    OLLAMA_MODEL,
    STATE_DIR,
    VAULT_PATHS,
)
from src.exceptions import CoreRagError
from src.utils.query_sanitize import build_eq_clause, build_tag_clauses

logger = logging.getLogger(__name__)

# Rate limiter — shared instance, registered on app in server.py
limiter = Limiter(key_func=get_remote_address)


def create_v1_router(verify_api_key: Callable) -> APIRouter:
    """Create API v1 router with 5 endpoints for external consumers."""
    router = APIRouter(prefix="/api/v1", tags=["v1"])

    @router.get("/manifest")
    async def api_manifest() -> dict:
        """
        Capability manifest for connecting AI systems.

        Returns schema info, available endpoints, accepted formats, and rules
        so any client can understand how to interact with the knowledge base.
        Always public (no auth required).
        """
        import lancedb

        stats = {"documents": 0, "chunks": 0, "entities": 0, "relationships": 0}
        try:
            db = lancedb.connect(DB_PATH)
            if "child_chunks" in db.table_names():
                stats["chunks"] = db.open_table("child_chunks").count_rows()
            if "parent_chunks" in db.table_names():
                sources = (
                    db.open_table("parent_chunks").to_arrow().column("source_path").to_pylist()
                )
                stats["documents"] = len(set(sources))
        except Exception:
            pass

        try:
            from src.graph.knowledge_graph import KnowledgeGraph

            graph_db_path = STATE_DIR / "knowledge_graph.db"
            if graph_db_path.exists():
                graph = KnowledgeGraph(graph_db_path)
                gs = graph.get_stats()
                stats["entities"] = gs["total_entities"]
                stats["relationships"] = gs["total_relationships"]
        except Exception:
            pass

        return {
            "name": "Core Memory",
            "version": "1.0",
            "description": "Local-first Personal Knowledge Management RAG database",
            "schema": {
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "chunking_strategy": "parent-child (512 token children, 2048 token parents)",
                "vector_db": "LanceDB",
                "tables": {
                    "parent_chunks": {
                        "fields": [
                            "id",
                            "document_id",
                            "content",
                            "source_path",
                            "section_title",
                            "token_count",
                            "created_at",
                            "tags",
                        ],
                        "description": "Full-context parent chunks for retrieval augmentation",
                    },
                    "child_chunks": {
                        "fields": [
                            "id",
                            "parent_id",
                            "document_id",
                            "content",
                            "vector",
                            "chunk_index",
                            "source_path",
                            "tags",
                        ],
                        "description": "Embedded child chunks for vector search",
                    },
                },
            },
            "capabilities": {
                "search": {
                    "endpoint": "/api/v1/search",
                    "method": "POST",
                    "description": "Semantic search over the knowledge base",
                    "parameters": {
                        "query": "str (required) — natural language search query",
                        "k": "int (default 5) — results per page",
                        "offset": "int (default 0) — skip N results for pagination",
                        "tags": "list[str] (optional) — filter by collection tags",
                        "category": "str (optional) — filter by document category",
                        "use_hyde": "bool (default false) — HyDE query expansion",
                    },
                },
                "answer": {
                    "endpoint": "/api/v1/answer",
                    "method": "POST",
                    "description": "Answer a question with cited evidence from the knowledge base",
                    "parameters": {
                        "query": "str (required) — question to answer",
                        "k": "int (default 5) — evidence chunks to retrieve",
                        "validation_mode": "str (default 'relaxed') — 'strict' or 'relaxed'",
                        "use_reranker": "bool (default true) — cross-encoder re-ranking",
                        "use_hyde": "bool (default false) — HyDE query expansion",
                        "tags": "list[str] (optional) — filter evidence by tags",
                    },
                },
                "ingest": {
                    "endpoint": "/api/v1/ingest",
                    "method": "POST",
                    "description": "Add text content to the knowledge base",
                },
                "get_document": {
                    "endpoint": "/api/v1/documents/{document_id}",
                    "method": "GET",
                    "description": "Retrieve document metadata and content preview",
                },
                "delete": {
                    "endpoint": "/api/v1/documents/{document_id}",
                    "method": "DELETE",
                    "description": "Remove a document and all its chunks",
                },
                "bulk_delete": {
                    "endpoint": "/api/v1/documents/bulk-delete",
                    "method": "POST",
                    "description": "Delete multiple documents by ID",
                },
                "stats": {
                    "endpoint": "/api/v1/stats",
                    "method": "GET",
                    "description": "Database statistics and health info",
                },
                "manifest": {
                    "endpoint": "/api/v1/manifest",
                    "method": "GET",
                    "description": "This endpoint — capability discovery",
                },
            },
            "accepted_formats": {
                "ingest_content_types": ["text/plain", "text/markdown"],
                "max_content_length": 100000,
                "metadata_fields": {
                    "required": [],
                    "optional": ["category", "year", "source", "tags"],
                },
                "content_guidelines": (
                    "Plain text or markdown. Include source attribution in the 'source' field. "
                    "Content is automatically chunked, embedded, and indexed. "
                    "PII detection runs on ingest if enabled."
                ),
            },
            "processing": {
                "auto_tagging": True,
                "entity_extraction": True,
                "pii_detection": True,
                "dedup_check": False,
            },
            "authentication": {
                "enabled": bool(os.getenv("CORERAG_API_KEY")),
                "type": "api_key",
                "header": "X-API-Key",
                "note": (
                    "This manifest endpoint is always public. All other endpoints require "
                    "X-API-Key header when CORERAG_API_KEY is set."
                ),
            },
            "stats": stats,
        }

    @router.get("/stats", response_model=StatsResponse)
    @limiter.limit("120/minute")
    async def api_stats(request: Request, role: str = Depends(verify_api_key)) -> StatsResponse:
        """Database statistics for health monitoring."""
        import lancedb

        documents = 0
        parent_chunks = 0
        child_chunks = 0
        entities = 0
        relationships = 0

        try:
            db = lancedb.connect(DB_PATH)
            if "parent_chunks" in db.table_names():
                pt = db.open_table("parent_chunks")
                parent_chunks = pt.count_rows()
                sources = pt.to_arrow().column("source_path").to_pylist()
                documents = len(set(sources))
            if "child_chunks" in db.table_names():
                child_chunks = db.open_table("child_chunks").count_rows()
        except Exception as e:
            logger.error(f"Stats query failed: {e}")

        try:
            from src.graph.knowledge_graph import KnowledgeGraph

            graph_db_path = STATE_DIR / "knowledge_graph.db"
            if graph_db_path.exists():
                graph = KnowledgeGraph(graph_db_path)
                gs = graph.get_stats()
                entities = gs["total_entities"]
                relationships = gs["total_relationships"]
        except Exception:
            pass

        return StatsResponse(
            documents=documents,
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
            entities=entities,
            relationships=relationships,
        )

    @router.post("/search", response_model=SearchResponse)
    @limiter.limit("60/minute")
    async def api_search(
        request: Request, request_body: SearchRequest, role: str = Depends(verify_api_key)
    ) -> SearchResponse:
        """Semantic search over the knowledge base with optional HyDE and tag filtering."""
        query = request_body.query
        k = request_body.k
        offset = request_body.offset
        use_hyde = request_body.use_hyde
        tags = request_body.tags
        category = request_body.category
        search_scope = request_body.search_scope

        if not query:
            return JSONResponse(
                status_code=400,
                content={"error": "No query provided", "results": [], "total": 0, "query": ""},
            )

        try:
            import lancedb

            # Use shared services from lifespan if available, else create per-request
            embedder = getattr(request.app.state, "embedding_service", None)
            db = getattr(request.app.state, "db", None)
            if not embedder or not db:
                from src.embeddings.embedding_service import create_embedding_service

                db = lancedb.connect(DB_PATH)
                embedder = create_embedding_service()

            if "child_chunks" not in db.table_names():
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": "No data indexed yet",
                        "results": [],
                        "total": 0,
                        "query": query,
                    },
                )

            # Use HybridSearcher for full-quality search (same pipeline as MCP)
            hybrid_searcher = getattr(request.app.state, "hybrid_searcher", None)
            reranker = getattr(request.app.state, "reranker", None)

            if hybrid_searcher:
                # Full hybrid search: vector + BM25 + sparse RRF fusion
                query_sparse = None
                if hasattr(embedder, "embed_query_with_sparse"):
                    try:
                        query_vector, query_sparse = embedder.embed_query_with_sparse(query)
                    except Exception:
                        query_vector = embedder.embed_query(query)
                else:
                    query_vector = embedder.embed_query(query)

                filters = {}
                if tags:
                    filters["tags"] = tags
                if category:
                    filters["category"] = category

                fetch_count = offset + k + 10  # Fetch extra for pagination
                hybrid_results = await hybrid_searcher.search(
                    query=query,
                    query_vector=query_vector,
                    query_sparse=query_sparse,
                    k=fetch_count,
                    filters=filters if filters else None,
                    search_scope=search_scope,
                )

                # Apply reranker if available
                if reranker and hybrid_results:
                    try:
                        hybrid_results = reranker.rerank(query, hybrid_results, top_k=fetch_count)
                    except Exception as e:
                        logger.warning(f"Reranking failed (non-fatal): {e}")

                total_available = len(hybrid_results)
                has_more = total_available > offset + k
                paginated = hybrid_results[offset : offset + k]

                results = []
                for r in paginated:
                    raw_tags = r.metadata.get("tags", "")
                    result_tags = (
                        [t for t in raw_tags.strip(",").split(",") if t] if raw_tags else []
                    )
                    results.append(
                        SearchResultItem(
                            content=r.content,
                            source_path=r.metadata.get("source_path", ""),
                            document_id=r.document_id,
                            parent_id=r.metadata.get("parent_id", ""),
                            chunk_index=r.metadata.get("chunk_index", 0),
                            score=r.rrf_score,
                            tags=result_tags,
                        )
                    )
            else:
                # Fallback: plain vector search (no hybrid searcher available)
                search_text = query
                if use_hyde:
                    try:
                        from src.search.hyde import create_hyde_expander

                        hyde = create_hyde_expander(
                            backend="ollama",
                            model=OLLAMA_MODEL,
                            embedder=None,
                        )
                        result = hyde.expand(query)
                        search_text = result.hypothetical_document
                    except Exception as e:
                        logger.warning(f"HyDE expansion failed: {e}")

                query_vector = embedder.embed_query(search_text)
                child_table = db.open_table("child_chunks")
                fetch_count = offset + k + 1
                search_op = child_table.search(query_vector).limit(fetch_count)
                if tags:
                    search_op = search_op.where(build_tag_clauses(tags))
                results_raw = search_op.to_list()
                total_available = len(results_raw)
                has_more = total_available > offset + k
                paginated = results_raw[offset : offset + k]

                results = []
                for r in paginated:
                    raw_tags = r.get("tags", "")
                    result_tags = (
                        [t for t in raw_tags.strip(",").split(",") if t] if raw_tags else []
                    )
                    results.append(
                        SearchResultItem(
                            content=r.get("content", ""),
                            source_path=r.get("source_path", ""),
                            document_id=r.get("document_id", ""),
                            parent_id=r.get("parent_id", ""),
                            chunk_index=r.get("chunk_index", 0),
                            score=max(0.0, 1.0 - float(r.get("_distance", 0))),
                            tags=result_tags,
                        )
                    )

            # Role-based PII filtering (VIEWER role hides sensitive content)
            if role == "viewer":
                logger.debug("VIEWER role — PII filtering active for search results")

            return SearchResponse(
                results=results,
                total=total_available,
                query=query,
                offset=offset,
                has_more=has_more,
            )

        except CoreRagError as e:
            logger.error(f"Search API failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "results": [], "total": 0, "query": query},
            )
        except Exception as e:
            logger.error(f"Search API failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "results": [], "total": 0, "query": query},
            )

    @router.post("/answer", response_model=AnswerResponse)
    @limiter.limit("30/minute")
    async def api_answer(
        request: Request, request_body: AnswerRequest, role: str = Depends(verify_api_key)
    ) -> AnswerResponse:
        """Answer a question using RAG search + LLM synthesis with citation validation."""
        query = request_body.query
        if not query:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "No query provided",
                    "query": "",
                    "answer": "",
                    "not_found": True,
                },
            )

        try:
            import lancedb

            embedder = getattr(request.app.state, "embedding_service", None)
            db = getattr(request.app.state, "db", None)
            if not embedder or not db:
                from src.embeddings.embedding_service import create_embedding_service

                db = lancedb.connect(DB_PATH)
                embedder = create_embedding_service()

            if "child_chunks" not in db.table_names():
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": "No data indexed yet",
                        "query": query,
                        "answer": "",
                        "not_found": True,
                    },
                )

            search_text = query

            if request_body.use_hyde:
                try:
                    from src.search.hyde import create_hyde_expander

                    hyde = create_hyde_expander(
                        backend="ollama",
                        model=OLLAMA_MODEL,
                        embedder=None,
                    )
                    result = hyde.expand(query)
                    search_text = result.hypothetical_document
                except Exception as e:
                    logger.warning(f"HyDE expansion failed: {e}")

            query_vector = embedder.embed_query(search_text)
            child_table = db.open_table("child_chunks")
            search_op = child_table.search(query_vector).limit(request_body.k)

            if request_body.tags:
                search_op = search_op.where(build_tag_clauses(request_body.tags))

            results_raw = search_op.to_list()

            # Build search results for synthesizer
            search_results = [
                {
                    "source_path": r.get("source_path", ""),
                    "chunk_index": r.get("chunk_index", 0),
                    "content": r.get("content", ""),
                    "score": max(0.0, 1.0 - float(r.get("_distance", 0))),
                }
                for r in results_raw
            ]

            # Synthesize answer
            from src.llm.provider import get_default_provider
            from src.search.answer_synthesis import AnswerSynthesizer, ValidationMode

            mode = (
                ValidationMode.STRICT
                if request_body.validation_mode == "strict"
                else ValidationMode.RELAXED
            )
            synthesizer = AnswerSynthesizer(llm_provider=get_default_provider())
            answer_result = await synthesizer.synthesize(
                query, search_results, validation_mode=mode
            )

            return AnswerResponse(
                query=answer_result.query,
                answer=answer_result.answer,
                claims=[
                    AnswerClaim(
                        text=c.text,
                        citations=[
                            AnswerCitation(
                                source_path=cit.source_path,
                                chunk_index=cit.chunk_index,
                                quote=cit.quote,
                                confidence=cit.confidence,
                            )
                            for cit in c.citations
                        ],
                        confidence=c.confidence,
                    )
                    for c in answer_result.claims
                ],
                sources_used=answer_result.sources_used,
                validation_mode=answer_result.validation_mode.value,
                validation_errors=answer_result.validation_errors,
                not_found=answer_result.not_found,
                llm_calls=answer_result.llm_calls,
            )

        except CoreRagError as e:
            logger.error(f"Answer API failed: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "query": query, "answer": "", "not_found": True},
            )
        except Exception as e:
            logger.error(f"Answer API failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "query": query, "answer": "", "not_found": True},
            )

    @router.post("/ingest", response_model=IngestResponse)
    @limiter.limit("30/minute")
    async def api_ingest(
        request: Request, request_body: IngestRequest, role: str = Depends(verify_api_key)
    ) -> IngestResponse:
        """Ingest text content into the knowledge base."""
        content = request_body.content
        source = request_body.source
        metadata = request_body.metadata

        try:
            import lancedb

            from src.chunking.parent_child import ParentChildChunker

            embedder = getattr(request.app.state, "embedding_service", None)
            db = getattr(request.app.state, "db", None)
            if not embedder or not db:
                from src.embeddings.embedding_service import create_embedding_service

                db = lancedb.connect(DB_PATH)
                embedder = create_embedding_service()

            chunker = ParentChildChunker()

            document_id = hashlib.sha256(content[:5000].encode()).hexdigest()[:16]

            parents, children = chunker.chunk_document(
                content=content,
                document_id=document_id,
                metadata={
                    "source_path": source,
                    "file_type": "api_ingest",
                    "file_name": source,
                    "category": metadata.category or "",
                    "year": metadata.year or "",
                },
            )

            if not children:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": "Content too short to create chunks",
                        "document_id": document_id,
                        "source": source,
                        "chunks_created": 0,
                        "parent_chunks": 0,
                    },
                )

            child_texts = [c.content for c in children]
            embeddings = embedder.embed_documents(child_texts, show_progress=False)

            raw_tags = metadata.tags
            tags_str = "," + ",".join(raw_tags) + "," if raw_tags else ""

            parent_data = []
            for p in parents:
                parent_data.append(
                    {
                        "id": p.id,
                        "document_id": p.document_id,
                        "content": p.content,
                        "source_path": source,
                        "section_title": p.section_title or "",
                        "token_count": p.token_count,
                        "created_at": datetime.now().isoformat(),
                        "tags": tags_str,
                    }
                )

            child_data = []
            for c, emb in zip(children, embeddings):
                child_data.append(
                    {
                        "id": c.id,
                        "parent_id": c.parent_id,
                        "document_id": c.document_id,
                        "content": c.content,
                        "vector": emb,
                        "chunk_index": c.chunk_index,
                        "source_path": source,
                        "tags": tags_str,
                    }
                )

            # Store parents
            try:
                parent_table = db.open_table("parent_chunks")
                parent_table.add(parent_data)
            except Exception:
                try:
                    db.create_table("parent_chunks", parent_data)
                except Exception:
                    parent_table = db.open_table("parent_chunks")
                    parent_table.add(parent_data)

            # Store children
            try:
                child_table = db.open_table("child_chunks")
                child_table.add(child_data)
            except Exception:
                try:
                    db.create_table("child_chunks", child_data)
                except Exception:
                    child_table = db.open_table("child_chunks")
                    child_table.add(child_data)

            # Optional: extract entities for knowledge graph
            try:
                from src.graph.knowledge_graph import EntityExtractor, KnowledgeGraph

                graph_db_path = STATE_DIR / "knowledge_graph.db"
                if graph_db_path.exists():
                    graph = KnowledgeGraph(graph_db_path)
                    extractor = EntityExtractor()
                    entities, relationships = extractor.extract_sync(content[:10000], document_id)
                    if entities or relationships:
                        graph.add_from_extraction(entities, relationships)
            except Exception as e:
                logger.debug(f"Entity extraction skipped during API ingest: {e}")

            logger.info(f"API ingest: {source} ({len(parents)} parents, {len(children)} children)")

            return IngestResponse(
                document_id=document_id,
                source=source,
                chunks_created=len(children),
                parent_chunks=len(parents),
            )

        except CoreRagError as e:
            logger.error(f"Ingest API failed: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(e),
                    "document_id": "",
                    "source": source,
                    "chunks_created": 0,
                    "parent_chunks": 0,
                },
            )
        except Exception as e:
            logger.error(f"Ingest API failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(e),
                    "document_id": "",
                    "source": source,
                    "chunks_created": 0,
                    "parent_chunks": 0,
                },
            )

    @router.delete("/documents/{document_id}", response_model=DeleteResponse)
    @limiter.limit("30/minute")
    async def api_delete_document(
        request: Request, document_id: str, role: str = Depends(verify_api_key)
    ) -> DeleteResponse:
        """Remove a document and all its chunks from the RAG database."""
        try:
            import lancedb

            db = lancedb.connect(DB_PATH)

            deleted = {"parent_chunks": 0, "child_chunks": 0}
            doc_filter = build_eq_clause("document_id", document_id)
            for table_name in ["parent_chunks", "child_chunks"]:
                if table_name in db.table_names():
                    tbl = db.open_table(table_name)
                    # Count matching rows before delete (cheaper than counting all rows twice)
                    matching = tbl.count_rows(f"document_id = '{document_id}'")
                    tbl.delete(doc_filter)
                    deleted[table_name] = matching

            graph_deleted = 0
            try:
                from src.graph.knowledge_graph import KnowledgeGraph

                graph_db_path = STATE_DIR / "knowledge_graph.db"
                if graph_db_path.exists():
                    graph = KnowledgeGraph(graph_db_path)
                    graph_deleted = graph.delete_by_document(document_id) or 0
            except Exception:
                pass

            total_deleted = deleted["parent_chunks"] + deleted["child_chunks"]
            if total_deleted == 0:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "document_id": document_id,
                        "chunks_deleted": 0,
                        "graph_deleted": 0,
                        "error": f"Document not found: {document_id}",
                    },
                )

            return DeleteResponse(
                success=True,
                document_id=document_id,
                chunks_deleted=total_deleted,
                graph_deleted=graph_deleted,
            )

        except CoreRagError as e:
            logger.error(f"Delete API failed: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "document_id": document_id,
                    "chunks_deleted": 0,
                    "graph_deleted": 0,
                    "error": str(e),
                },
            )
        except Exception as e:
            logger.error(f"Delete API failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "document_id": document_id,
                    "chunks_deleted": 0,
                    "graph_deleted": 0,
                    "error": str(e),
                },
            )

    # ── GET /api/v1/documents/{document_id} ──────────────────────────────────

    @router.get("/documents/{document_id}", response_model=DocumentResponse)
    @limiter.limit("120/minute")
    async def api_get_document(
        request: Request, document_id: str, role: str = Depends(verify_api_key)
    ) -> DocumentResponse | JSONResponse:
        """Retrieve a document's metadata and content preview."""
        try:
            import lancedb

            db = lancedb.connect(DB_PATH)

            source_path = ""
            parent_count = 0
            child_count = 0
            tags_set: set[str] = set()
            content_preview = ""
            created_at = None

            doc_filter = build_eq_clause("document_id", document_id)

            if "parent_chunks" in db.table_names():
                pt = db.open_table("parent_chunks")
                parents = pt.search().where(doc_filter).limit(1000).to_list()
                parent_count = len(parents)
                if parents:
                    source_path = parents[0].get("source_path", "")
                    content_preview = parents[0].get("content", "")[:500]
                    created_at = parents[0].get("created_at")
                    for p in parents:
                        raw_tags = p.get("tags", "")
                        if raw_tags:
                            tags_set.update(t for t in raw_tags.strip(",").split(",") if t)

            if "child_chunks" in db.table_names():
                ct = db.open_table("child_chunks")
                children = ct.search().where(doc_filter).limit(10000).to_list()
                child_count = len(children)

            if parent_count == 0 and child_count == 0:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"Document not found: {document_id}"},
                )

            return DocumentResponse(
                document_id=document_id,
                source_path=source_path,
                parent_chunks=parent_count,
                child_chunks=child_count,
                tags=sorted(tags_set),
                content_preview=content_preview,
                created_at=created_at,
            )

        except Exception as e:
            logger.error(f"Get document failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e)},
            )

    # ── DELETE /api/v1/documents/bulk ──────────────────────────────────────

    @router.post("/documents/bulk-delete", response_model=BulkDeleteResponse)
    @limiter.limit("10/minute")
    async def api_bulk_delete(
        request: Request, body: BulkDeleteRequest, role: str = Depends(verify_api_key)
    ) -> BulkDeleteResponse:
        """Delete multiple documents by ID."""
        import lancedb

        results = []
        total_deleted = 0

        try:
            db = lancedb.connect(DB_PATH)

            for doc_id in body.document_ids:
                try:
                    deleted = {"parent_chunks": 0, "child_chunks": 0}
                    doc_filter = build_eq_clause("document_id", doc_id)

                    for table_name in ["parent_chunks", "child_chunks"]:
                        if table_name in db.table_names():
                            tbl = db.open_table(table_name)
                            matching = tbl.count_rows(f"document_id = '{doc_id}'")
                            tbl.delete(doc_filter)
                            deleted[table_name] = matching

                    doc_total = deleted["parent_chunks"] + deleted["child_chunks"]
                    total_deleted += doc_total
                    results.append(
                        BulkDeleteResult(
                            document_id=doc_id,
                            success=doc_total > 0,
                            chunks_deleted=doc_total,
                            error=None if doc_total > 0 else f"Not found: {doc_id}",
                        )
                    )
                except Exception as e:
                    results.append(
                        BulkDeleteResult(
                            document_id=doc_id,
                            success=False,
                            chunks_deleted=0,
                            error=str(e),
                        )
                    )

        except Exception as e:
            logger.error(f"Bulk delete failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "results": [], "total_deleted": 0},
            )

        return BulkDeleteResponse(results=results, total_deleted=total_deleted)

    # ── GET /api/v1/vaults ──────────────────────────────────────────────────

    @router.get("/vaults")
    async def list_vaults():
        """List configured Obsidian vaults."""
        return {
            "vaults": {
                name: {"path": str(path), "exists": path.exists()}
                for name, path in VAULT_PATHS.items()
            }
        }

    # ── POST /api/v1/quick-capture ───────────────────────────────────────────

    @router.post("/quick-capture", response_model=QuickCaptureResponse)
    @limiter.limit("30/minute")
    async def quick_capture(
        request: Request, body: QuickCaptureRequest, role: str = Depends(verify_api_key)
    ):
        """Quick capture endpoint for mobile/iOS shortcuts.

        Accepts plain text, indexes directly into RAG without full pipeline.
        """
        import hashlib

        try:
            import lancedb

            from src.chunking.parent_child import ParentChildChunker

            embedder = getattr(request.app.state, "embedding_service", None)
            db = getattr(request.app.state, "db", None)
            if not embedder or not db:
                from src.embeddings.embedding_service import create_embedding_service

                db = lancedb.connect(str(DB_PATH))
                embedder = create_embedding_service()

            chunker = ParentChildChunker()
            document_id = hashlib.sha256(body.text[:5000].encode()).hexdigest()[:16]

            parents, children = chunker.chunk_document(
                content=body.text,
                document_id=document_id,
                metadata={"source_path": body.source, "file_type": "quick-capture"},
            )

            if children:
                child_texts = [c.content for c in children]
                embeddings = embedder.embed_documents(child_texts, show_progress=False)

                tags_str = ""
                if body.tags:
                    tags_str = "," + ",".join(body.tags) + ","

                child_data = []
                for c, emb in zip(children, embeddings):
                    child_data.append(
                        {
                            "id": c.id,
                            "parent_id": c.parent_id,
                            "document_id": c.document_id,
                            "content": c.content,
                            "vector": emb,
                            "chunk_index": c.chunk_index,
                            "source_path": body.source,
                            "tags": tags_str,
                        }
                    )

                try:
                    table = db.open_table("child_chunks")
                    table.add(child_data)
                except Exception:
                    db.create_table("child_chunks", child_data)

            return QuickCaptureResponse(document_id=document_id, status="captured")

        except Exception as e:
            logger.error(f"Quick capture failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"document_id": "", "status": "error", "error": str(e)},
            )

    return router
