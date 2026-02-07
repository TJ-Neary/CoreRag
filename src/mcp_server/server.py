"""
MCP Server Entry Point for CoreRag.

Exposes CoreRag tools to Claude via the Model Context Protocol (MCP).
Uses FastMCP for easy tool registration and serving.

Usage:
    # Start via Claude Desktop (stdio transport)
    python -m src.mcp_server.server
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import lancedb
from dotenv import load_dotenv
from fastmcp import FastMCP

from src.analytics.query_analytics import QueryAnalytics
from src.config import SEMANTIC_CACHE_THRESHOLD
from src.embeddings.embedding_service import EmbeddingService
from src.mcp_server.tools import CoreRagTools
from src.search.hybrid_search import HybridSearcher
from src.search.hyde import create_hyde_expander
from src.search.reranker import CrossEncoderReranker
from src.utils.safe_processor import SafeProcessor, get_ingestion_controller

logger = logging.getLogger(__name__)

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# Global instances (initialized on startup)
_corerag_tools: Optional[CoreRagTools] = None
_embedding_service: Optional[EmbeddingService] = None
_safe_processor: Optional[SafeProcessor] = None
_query_analytics: Optional[QueryAnalytics] = None
_session_tracker = None


def get_config() -> dict:
    """Load configuration from central config module."""
    from src.config import DB_PATH, EMBEDDING_MODEL, RERANKER_MODEL, STATE_DIR, VAULT_PATH

    return {
        "db_path": str(DB_PATH),
        "vault_path": str(VAULT_PATH),
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "state_dir": str(STATE_DIR),
        "enable_analytics": os.getenv("CORERAG_ENABLE_ANALYTICS", "true").lower() == "true",
        "enable_cache": os.getenv("CORERAG_ENABLE_CACHE", "true").lower() == "true",
    }


async def _startup():
    """Initialize CoreRag components on server startup."""
    global _corerag_tools, _embedding_service, _safe_processor, _query_analytics

    config = get_config()
    logger.info(f"Starting CoreRag server with config: {config}")

    # Initialize safe processor (memory management)
    _safe_processor = SafeProcessor()

    # Connect to LanceDB
    db_path = config["db_path"]
    db = lancedb.connect(db_path)
    logger.info(f"Connected to LanceDB at {db_path}")

    # Initialize embedding service
    _embedding_service = EmbeddingService(
        model_name=config["embedding_model"],
        cache_enabled=config["enable_cache"],
    )

    # Initialize hybrid searcher (vector + FTS)
    searcher = HybridSearcher(db, table_name="child_chunks")
    try:
        searcher.ensure_fts_index()
        logger.info("FTS index verified on child_chunks")
    except Exception as e:
        logger.warning(f"FTS index setup deferred (table may not exist yet): {e}")

    # Initialize cross-encoder reranker
    reranker = CrossEncoderReranker(model_name=config["reranker_model"])
    logger.info(f"Reranker ready: {config['reranker_model']}")

    # Initialize query analytics
    if config["enable_analytics"]:
        _query_analytics = QueryAnalytics(state_dir=Path(config["state_dir"]) / "analytics")

    # Initialize semantic cache for search result deduplication
    from src.analytics.query_analytics import SemanticCache

    semantic_cache = None
    if config["enable_cache"]:
        semantic_cache = SemanticCache(
            embedding_service=_embedding_service,
            similarity_threshold=SEMANTIC_CACHE_THRESHOLD,
            max_entries=1000,
            ttl_hours=24,
        )
        logger.info("Semantic cache initialized (threshold=0.92, ttl=24h)")

    # Initialize HyDE expander (uses Ollama for hypothetical document generation)
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
    hyde_expander = create_hyde_expander(
        backend="ollama",
        model=ollama_model,
        embedder=_embedding_service.embed_query,
        cache_dir=Path(config["state_dir"]) / "cache",
    )
    logger.info(f"HyDE expander ready: ollama/{ollama_model}")

    # Vault root for file listing / folder structure tools
    vault_root = Path(config["vault_path"]).expanduser().resolve()

    # Build async embedder callable for CoreRagTools
    # CoreRagTools.search_knowledge calls: query_vector = await self.embedder(query)
    async def _embed_query(text: str) -> list[float]:
        return _embedding_service.embed_query(text)

    # Initialize knowledge graph
    from src.graph.knowledge_graph import KnowledgeGraph

    graph_db_path = Path(config["state_dir"]) / "knowledge_graph.db"
    knowledge_graph = KnowledgeGraph(graph_db_path)
    graph_stats = knowledge_graph.get_stats()
    logger.info(
        f"Knowledge graph: {graph_stats['total_entities']} entities, "
        f"{graph_stats['total_relationships']} relationships"
    )

    # Initialize conflict detector (semantic + numeric contradiction detection)
    from src.quality.conflict_detector import ConflictDetector

    conflict_detector = ConflictDetector(
        embedder=_embedding_service.embed_query,
        state_dir=Path(config["state_dir"]) / "conflicts",
    )
    logger.info("Conflict detector initialized (semantic + numeric modes)")

    # Initialize CoreRag tools with correct constructor signature
    _corerag_tools = CoreRagTools(
        retriever=searcher,
        embedder=_embed_query,
        reranker=reranker,
        db=db,
        vault_root=vault_root,
        hyde_expander=hyde_expander,
        knowledge_graph=knowledge_graph,
        semantic_cache=semantic_cache,
        conflict_detector=conflict_detector,
    )

    # Initialize session tracker
    global _session_tracker
    from src.memory.episodic_memory import SessionTracker

    _session_tracker = SessionTracker()
    logger.info(f"Session tracker started: {_session_tracker._current.session_id}")

    logger.info("CoreRag server initialized successfully")


async def _shutdown():
    """Cleanup on server shutdown."""
    global _safe_processor, _query_analytics, _embedding_service, _session_tracker

    if _session_tracker:
        _session_tracker.end_session()

    if _embedding_service:
        _embedding_service.save_cache()

    if _safe_processor:
        _safe_processor.stop()

    if _query_analytics:
        _query_analytics.flush()

    logger.info("CoreRag server shut down")


@asynccontextmanager
async def lifespan(app):
    """Manage server lifecycle - initialize on startup, cleanup on shutdown."""
    await _startup()
    yield
    await _shutdown()


# Initialize FastMCP server with lifespan manager
mcp = FastMCP(
    name="corerag-server",
    version="1.0.0",
    instructions="Personal Knowledge Management System with RAG capabilities",
    lifespan=lifespan,
)


# === SEARCH TOOLS ===


@mcp.tool()
async def search_knowledge(
    query: str,
    k: int = 5,
    use_reranker: bool = True,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    filters: Optional[dict] = None,
    tags: Optional[list] = None,
    debug: bool = False,
) -> dict:
    """
    Search the knowledge base for relevant information.

    Args:
        query: Natural language search query
        k: Number of results to return (default: 5)
        use_reranker: Apply cross-encoder re-ranking (default: True)
        use_hyde: Use HyDE query expansion (default: False)
        use_multi_query: Decompose complex queries into sub-queries and fuse results (default: False)
        filters: Optional filters (e.g., {"file_type": "md", "category": "work"})
        tags: Optional collection tags to filter by (e.g., ["sphr-study"]). Only returns documents with ALL specified tags.
        debug: Return detailed debug information (default: False)

    Returns:
        Search results with content, sources, and optional debug info
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    import time as _time

    _search_start = _time.time()

    result = await _corerag_tools.search_knowledge(
        query=query,
        k=k,
        use_reranker=use_reranker,
        use_hyde=use_hyde,
        use_multi_query=use_multi_query,
        filters=filters,
        tags=tags,
        debug=debug,
    )

    # Log search event for session tracking
    if _session_tracker:
        _session_tracker.log_event(
            event_type="search",
            tool_name="search_knowledge",
            query=query,
            result_count=len(result.get("results", [])),
            duration_ms=(_time.time() - _search_start) * 1000,
        )

    return result


@mcp.tool()
async def search_by_entity(
    entity_name: str,
    relationship_type: Optional[str] = None,
    max_hops: int = 2,
) -> dict:
    """
    Search using the knowledge graph for entity relationships.

    Args:
        entity_name: Name of the entity to search for
        relationship_type: Filter by relationship type (optional)
        max_hops: Maximum graph traversal depth (default: 2)

    Returns:
        Related entities and their connections
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.search_by_entity(
        entity_name=entity_name,
        relationship_type=relationship_type,
        max_hops=max_hops,
    )


# === METACOGNITION TOOLS ===


@mcp.tool()
async def list_recent_files(
    days: int = 7,
    limit: int = 50,
    file_types: Optional[list] = None,
) -> list:
    """
    List recently modified files in the knowledge base.

    Args:
        days: Look back this many days (default: 7)
        limit: Maximum files to return (default: 50)
        file_types: Filter by extensions (e.g., ["md", "pdf"])

    Returns:
        List of recent files with metadata
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.list_recent_files(
        days=days,
        limit=limit,
        file_types=file_types,
    )


@mcp.tool()
async def get_folder_structure(
    path: str = "",
    max_depth: int = 3,
) -> dict:
    """
    Get the folder structure of the knowledge base.

    Args:
        path: Relative path to start from (default: root)
        max_depth: Maximum depth to traverse (default: 3)

    Returns:
        Hierarchical folder structure with file counts
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.get_folder_structure(
        path=path,
        max_depth=max_depth,
    )


@mcp.tool()
async def get_user_context() -> dict:
    """
    Get user profile and episodic memory context.

    Returns:
        User preferences, facts, and recent context
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.get_user_context()


# === SYSTEM TOOLS ===


@mcp.tool()
async def get_system_status() -> dict:
    """
    Get current system status including memory, ingestion state, and health.

    Returns:
        System status including memory usage, active queries, and health metrics
    """
    if not _safe_processor:
        return {"error": "Safe processor not initialized"}

    ingestion = get_ingestion_controller()

    return {
        "memory": {
            "status": _safe_processor.get_status().__dict__,
            "is_safe": _safe_processor.is_safe(),
        },
        "ingestion": ingestion.get_status(),
        "analytics": _query_analytics.get_summary() if _query_analytics else None,
    }


@mcp.tool()
async def add_user_fact(
    fact: str,
    category: str = "general",
) -> dict:
    """
    Add a fact about the user to episodic memory.

    Args:
        fact: The fact to remember (e.g., "User prefers dark mode")
        category: Category for the fact (default: "general")

    Returns:
        Confirmation of added fact
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.add_user_fact(fact=fact, category=category)


# === INGESTION TOOLS ===


@mcp.tool()
async def trigger_reindex(
    path: Optional[str] = None,
    force: bool = False,
) -> dict:
    """
    Trigger re-indexing of files.

    Args:
        path: Specific file or folder to reindex (optional, defaults to all)
        force: Force reindex even if file hasn't changed (default: False)

    Returns:
        Indexing status and queued files
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.trigger_reindex(path=path, force=force)


@mcp.tool()
async def get_ingestion_queue() -> dict:
    """
    Get current ingestion queue status.

    Returns:
        Queue length, currently processing file, and recent completions
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.get_ingestion_queue()


# === QUALITY TOOLS ===


@mcp.tool()
async def check_stale_content(
    path: Optional[str] = None,
    days: int = 365,
) -> dict:
    """
    Find stale content in the knowledge base.

    Args:
        path: Directory to check (defaults to vault root)
        days: Consider files older than this as stale (default: 365)

    Returns:
        List of stale files with age and freshness level
    """
    try:
        from src.quality.freshness import FreshnessIndicator

        fi = FreshnessIndicator(stale_days=days)
        check_path = Path(path) if path else (Path(get_config()["vault_path"]))
        stale = fi.get_stale_content(check_path, recursive=True)
        return {
            "path": str(check_path),
            "threshold_days": days,
            "stale_count": len(stale),
            "files": [
                {
                    "path": str(s.file_path),
                    "age_days": s.age_days,
                    "level": s.freshness_level.value,
                    "modified_at": s.modified_at.isoformat() if s.modified_at else None,
                }
                for s in stale[:20]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def check_links(
    path: Optional[str] = None,
) -> dict:
    """
    Check for broken links in documents.

    Args:
        path: Directory to scan (defaults to vault root)

    Returns:
        Link health report with broken link details
    """
    try:
        from src.quality.link_checker import check_links as _check_links

        check_path = Path(path) if path else (Path(get_config()["vault_path"]))
        report = await _check_links(check_path, recursive=True)
        return {
            "path": str(check_path),
            "documents_scanned": report.documents_scanned,
            "total_links": report.total_links,
            "broken_links": report.broken_links,
            "redirect_links": report.redirect_links,
            "overall_health": report.overall_health,
            "broken_details": (
                [
                    {"url": d["url"], "status": d["status"], "file": d.get("file", "")}
                    for d in report.broken_details[:20]
                ]
                if hasattr(report, "broken_details") and report.broken_details
                else []
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def detect_conflicts(
    path: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """
    Scan documents for contradictions, numeric mismatches, and outdated information.

    Args:
        path: Directory to scan (defaults to vault root)
        limit: Maximum conflicts to return (default: 10)

    Returns:
        Conflict report with evidence and resolution suggestions
    """
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}

    return await _corerag_tools.detect_conflicts(path=path, limit=limit)


# === BACKUP TOOLS ===


@mcp.tool()
async def create_backup(
    name: Optional[str] = None,
    backup_type: str = "full",
) -> dict:
    """
    Create a backup of the CoreRag database and state.

    Args:
        name: Optional name prefix for the backup
        backup_type: Type of backup ("full" or "incremental")

    Returns:
        Backup details including path and size
    """
    try:
        from src.utils.backup import BackupManager

        config = get_config()
        bm = BackupManager(data_dir=Path(config["state_dir"]))
        info = bm.create_backup(backup_name=name, backup_type=backup_type)
        return {
            "name": info.name,
            "timestamp": info.timestamp,
            "size_bytes": info.size_bytes,
            "path": info.path,
            "backup_type": info.backup_type,
            "components": info.components,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def list_backups() -> dict:
    """
    List available CoreRag backups.

    Returns:
        List of backups with name, timestamp, and size
    """
    try:
        from src.utils.backup import BackupManager

        config = get_config()
        bm = BackupManager(data_dir=Path(config["state_dir"]))
        backups = bm.list_backups()
        return {
            "count": len(backups),
            "backups": [
                {
                    "name": b.name,
                    "timestamp": b.timestamp,
                    "size_bytes": b.size_bytes,
                    "backup_type": b.backup_type,
                    "components": b.components,
                }
                for b in backups
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# === QUALITY TOOLS ===


@mcp.tool()
async def find_duplicates(
    path: Optional[str] = None,
    include_semantic: bool = False,
) -> dict:
    """
    Scan a directory for duplicate files (exact, near-duplicate, and optionally semantic).

    Args:
        path: Directory to scan (defaults to vault root)
        include_semantic: Enable semantic duplicate detection via embeddings (slower)

    Returns:
        Duplicate report with matches, counts, and reclaimable space
    """
    try:
        from src.quality.duplicate_detector import DuplicateDetector

        config = get_config()
        check_path = Path(path).expanduser() if path else Path(config["vault_path"]).expanduser()

        embedder = _embedding_service if include_semantic and _embedding_service else None
        detector = DuplicateDetector(embedding_service=embedder)
        report = detector.scan_directory(check_path, recursive=True)

        return {
            "path": str(check_path),
            "total_files": report.total_files,
            "exact_duplicates": report.exact_duplicates,
            "near_duplicates": report.near_duplicates,
            "semantic_duplicates": report.semantic_duplicates,
            "space_reclaimable_bytes": report.space_reclaimable_bytes,
            "matches": [
                {
                    "file1": m.file1,
                    "file2": m.file2,
                    "similarity": round(m.similarity, 3),
                    "match_type": m.match_type,
                }
                for m in (report.matches or [])[:20]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# === MAINTENANCE TOOLS ===


@mcp.tool()
async def get_database_health() -> dict:
    """
    Get a health report for the LanceDB vector database.

    Returns:
        Health report including size, fragmentation, table stats, and recommendations
    """
    try:
        from src.maintenance.db_optimizer import LanceDBOptimizer

        config = get_config()
        optimizer = LanceDBOptimizer(db_path=Path(config["db_path"]))
        report = optimizer.get_health_report()

        return {
            "db_path": str(report.db_path),
            "total_size_mb": round(report.total_size_mb, 2),
            "fragmentation_estimate": round(report.fragmentation_estimate, 2),
            "tables": [
                {
                    "name": t.get("name", ""),
                    "rows": t.get("rows", 0),
                    "size_mb": round(t.get("size_mb", 0), 2),
                }
                for t in (report.tables or [])
            ],
            "recommendations": report.recommendations or [],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def optimize_database() -> dict:
    """
    Run optimization on the LanceDB vector database (compact, defragment).

    Returns:
        Optimization results per table including space saved
    """
    try:
        from src.maintenance.db_optimizer import LanceDBOptimizer

        config = get_config()
        optimizer = LanceDBOptimizer(db_path=Path(config["db_path"]))
        results = optimizer.optimize_all()

        return {
            "tables_optimized": len(results),
            "results": [
                {
                    "table": r.table_name,
                    "success": r.success,
                    "space_saved_mb": round(r.space_saved_mb, 2),
                    "duration_seconds": round(r.duration_seconds, 2),
                    "rows_before": r.rows_before,
                    "rows_after": r.rows_after,
                    "error": r.error,
                }
                for r in results
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# === TAG TOOLS ===


@mcp.tool()
async def list_tags(limit: int = 50) -> dict:
    """
    List all known collection tags in the CoreRag system.

    Args:
        limit: Maximum number of tags to return (default: 50)

    Returns:
        Tag list with names, colors, use counts, and descriptions
    """
    try:
        from src.utils.tagging import TagManager

        tm = TagManager()
        all_tags = tm.get_all_tags()

        return {
            "count": len(all_tags),
            "tags": [
                {
                    "name": t.name,
                    "color": getattr(t, "color", None),
                    "use_count": getattr(t, "use_count", 0),
                    "description": getattr(t, "description", ""),
                }
                for t in all_tags[:limit]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def manage_tags(
    action: str,
    tag_name: Optional[str] = None,
    target_tag: Optional[str] = None,
    color: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """
    Create, delete, or merge collection tags.

    Args:
        action: "create", "delete", "merge", or "get_tree"
        tag_name: Tag name (required for create, delete, merge)
        target_tag: Target tag for merge (source tag_name is merged into target)
        color: Optional color hex for create (e.g. "#4A90D9")
        description: Optional description for create

    Returns:
        Action result
    """
    try:
        from src.utils.tagging import TagManager

        tm = TagManager()

        if action == "create":
            if not tag_name:
                return {"error": "tag_name is required for create"}
            tag = tm.create_tag(tag_name, color=color, description=description)
            return {"success": True, "tag": tag.name}

        elif action == "delete":
            if not tag_name:
                return {"error": "tag_name is required for delete"}
            result = tm.delete_tag(tag_name)
            return {"success": result, "deleted": tag_name}

        elif action == "merge":
            if not tag_name or not target_tag:
                return {"error": "tag_name and target_tag required for merge"}
            affected = tm.merge_tags(tag_name, target_tag)
            return {
                "success": True,
                "merged": tag_name,
                "into": target_tag,
                "documents_affected": affected,
            }

        elif action == "get_tree":
            tree = tm.get_tag_tree()
            return {"tree": tree}

        else:
            return {"error": f"Unknown action: {action}. Use create, delete, merge, or get_tree"}

    except Exception as e:
        return {"error": str(e)}


# === RESOURCE ENDPOINTS ===


@mcp.resource("corerag://status")
async def get_status_resource() -> str:
    """Get CoreRag system status as a resource."""
    status = await get_system_status()
    return f"CoreRag Status: {status}"


@mcp.resource("corerag://recent/{days}")
async def get_recent_resource(days: int = 7) -> str:
    """Get recent files as a resource."""
    files = await list_recent_files(days=days)
    return f"Recent files ({days} days): {len(files)} files"


# === SERVER ENTRY POINT ===


def create_app():
    """Create the FastMCP application."""
    return mcp


def main() -> None:
    """Entry point for the corerag-server console script."""
    from src.utils.logging_config import setup_logging

    setup_logging(json_logs=True)
    mcp.run(transport="stdio")


# For direct running (Claude Desktop uses stdio transport)
if __name__ == "__main__":
    main()
