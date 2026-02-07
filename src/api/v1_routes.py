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
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.models import (
    DeleteResponse,
    IngestRequest,
    IngestResponse,
    QuickCaptureRequest,
    QuickCaptureResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsResponse,
)
from src.config import DB_PATH, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, STATE_DIR, VAULT_PATHS
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
                        "k": "int (default 5) — max results",
                        "tags": "list[str] (optional) — filter by collection tags",
                        "use_hyde": "bool (default false) — HyDE query expansion",
                    },
                },
                "ingest": {
                    "endpoint": "/api/v1/ingest",
                    "method": "POST",
                    "description": "Add text content to the knowledge base",
                },
                "delete": {
                    "endpoint": "/api/v1/documents/{document_id}",
                    "method": "DELETE",
                    "description": "Remove a document and all its chunks",
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
    async def api_stats(request: Request, _: bool = Depends(verify_api_key)) -> StatsResponse:
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
        request: Request, request_body: SearchRequest, _: bool = Depends(verify_api_key)
    ) -> SearchResponse:
        """Semantic search over the knowledge base with optional HyDE and tag filtering."""
        query = request_body.query
        k = request_body.k
        use_hyde = request_body.use_hyde
        tags = request_body.tags

        if not query:
            return SearchResponse(error="No query provided", results=[], total=0, query="")

        try:
            import lancedb

            from src.embeddings.embedding_service import create_embedding_service

            db = lancedb.connect(DB_PATH)

            if "child_chunks" not in db.table_names():
                return SearchResponse(error="No data indexed yet", results=[], total=0, query=query)

            embedder = create_embedding_service()
            search_text = query

            if use_hyde:
                try:
                    from src.search.hyde import create_hyde_expander

                    hyde = create_hyde_expander(
                        backend="ollama",
                        model=os.getenv("OLLAMA_MODEL", "qwen2.5:32b"),
                        embedder=None,
                    )
                    result = hyde.expand(query)
                    search_text = result.hypothetical_document
                except Exception as e:
                    logger.warning(f"HyDE expansion failed: {e}")

            query_vector = embedder.embed_query(search_text)
            child_table = db.open_table("child_chunks")
            search_op = child_table.search(query_vector).limit(k)

            if tags:
                search_op = search_op.where(build_tag_clauses(tags))

            results_raw = search_op.to_list()

            results = []
            for r in results_raw:
                raw_tags = r.get("tags", "")
                result_tags = [t for t in raw_tags.strip(",").split(",") if t] if raw_tags else []
                results.append(
                    SearchResultItem(
                        content=r.get("content", ""),
                        source_path=r.get("source_path", ""),
                        document_id=r.get("document_id", ""),
                        parent_id=r.get("parent_id", ""),
                        chunk_index=r.get("chunk_index", 0),
                        score=float(r.get("_distance", 0)),
                        tags=result_tags,
                    )
                )

            return SearchResponse(results=results, total=len(results), query=query)

        except CoreRagError as e:
            logger.error(f"Search API failed: {e}")
            return SearchResponse(error=str(e), results=[], total=0, query=query)
        except Exception as e:
            logger.error(f"Search API failed: {e}", exc_info=True)
            return SearchResponse(error=str(e), results=[], total=0, query=query)

    @router.post("/ingest", response_model=IngestResponse)
    @limiter.limit("30/minute")
    async def api_ingest(
        request: Request, request_body: IngestRequest, _: bool = Depends(verify_api_key)
    ) -> IngestResponse:
        """Ingest text content into the knowledge base."""
        content = request_body.content
        source = request_body.source
        metadata = request_body.metadata

        try:
            import lancedb

            from src.chunking.parent_child import ParentChildChunker
            from src.embeddings.embedding_service import create_embedding_service

            db = lancedb.connect(DB_PATH)
            chunker = ParentChildChunker()
            embedder = create_embedding_service()

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
                return IngestResponse(
                    error="Content too short to create chunks",
                    document_id=document_id,
                    source=source,
                    chunks_created=0,
                    parent_chunks=0,
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
                    entities, relationships = extractor._extract_with_patterns(
                        content[:10000], document_id
                    )
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
            return IngestResponse(
                error=str(e),
                document_id="",
                source=source,
                chunks_created=0,
                parent_chunks=0,
            )
        except Exception as e:
            logger.error(f"Ingest API failed: {e}", exc_info=True)
            return IngestResponse(
                error=str(e),
                document_id="",
                source=source,
                chunks_created=0,
                parent_chunks=0,
            )

    @router.delete("/documents/{document_id}", response_model=DeleteResponse)
    @limiter.limit("30/minute")
    async def api_delete_document(
        request: Request, document_id: str, _: bool = Depends(verify_api_key)
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
                    before = tbl.count_rows()
                    tbl.delete(doc_filter)
                    after = tbl.count_rows()
                    deleted[table_name] = before - after

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
                return DeleteResponse(
                    success=False,
                    document_id=document_id,
                    chunks_deleted=0,
                    error=f"Document not found: {document_id}",
                )

            return DeleteResponse(
                success=True,
                document_id=document_id,
                chunks_deleted=total_deleted,
                graph_deleted=graph_deleted,
            )

        except CoreRagError as e:
            logger.error(f"Delete API failed: {e}")
            return DeleteResponse(
                success=False,
                document_id=document_id,
                chunks_deleted=0,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"Delete API failed: {e}", exc_info=True)
            return DeleteResponse(
                success=False,
                document_id=document_id,
                chunks_deleted=0,
                error=str(e),
            )

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
    async def quick_capture(request: Request, body: QuickCaptureRequest, _=Depends(verify_api_key)):
        """Quick capture endpoint for mobile/iOS shortcuts.

        Accepts plain text, indexes directly into RAG without full pipeline.
        """
        import hashlib

        try:
            import lancedb

            from src.chunking.parent_child import ParentChildChunker
            from src.embeddings.embedding_service import create_embedding_service

            db = lancedb.connect(str(DB_PATH))
            chunker = ParentChildChunker()
            embedder = create_embedding_service()

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
            return QuickCaptureResponse(document_id="", status="error", error=str(e))

    return router
