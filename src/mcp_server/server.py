"""
MCP Server Entry Point for PKM System.

Exposes PKM tools to Claude via the Model Context Protocol (MCP).
Uses FastMCP for easy tool registration and serving.

Usage:
    # Start the server
    python -m src.mcp_server.server

    # Or with uvicorn for production
    uvicorn src.mcp_server.server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

# Import our tools
from src.mcp_server.tools import PKMTools
from src.embeddings.embedding_service import EmbeddingService
from src.search.hybrid_search import HybridSearcher
from src.search.reranker import CrossEncoderReranker
from src.memory.episodic_memory import EpisodicMemoryManager
from src.utils.safe_processor import SafeProcessor, get_ingestion_controller
from src.analytics.query_analytics import QueryAnalytics

logger = logging.getLogger(__name__)

# Global instances (initialized on startup)
_pkm_tools: Optional[PKMTools] = None
_embedding_service: Optional[EmbeddingService] = None
_safe_processor: Optional[SafeProcessor] = None
_query_analytics: Optional[QueryAnalytics] = None


def get_config() -> dict:
    """Load configuration from environment or defaults."""
    return {
        "db_path": os.getenv("PKM_DB_PATH", str(Path.home() / ".pkm" / "lancedb")),
        "embedding_model": os.getenv("PKM_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "reranker_model": os.getenv("PKM_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
        "watch_dir": os.getenv("PKM_WATCH_DIR", str(Path.home() / "Documents" / "PKM_Input")),
        "state_dir": os.getenv("PKM_STATE_DIR", str(Path.home() / ".pkm")),
        "enable_analytics": os.getenv("PKM_ENABLE_ANALYTICS", "true").lower() == "true",
        "enable_cache": os.getenv("PKM_ENABLE_CACHE", "true").lower() == "true",
    }


async def _startup():
    """Initialize PKM components on server startup."""
    global _pkm_tools, _embedding_service, _safe_processor, _query_analytics

    config = get_config()
    logger.info(f"Starting PKM server with config: {config}")

    # Initialize safe processor (memory management)
    _safe_processor = SafeProcessor()

    # Initialize embedding service
    _embedding_service = EmbeddingService(
        model_name=config["embedding_model"],
        cache_enabled=config["enable_cache"],
    )

    # Initialize query analytics
    if config["enable_analytics"]:
        _query_analytics = QueryAnalytics(
            state_dir=Path(config["state_dir"]) / "analytics"
        )

    # Initialize PKM tools
    _pkm_tools = PKMTools(
        db_path=Path(config["db_path"]),
        embedding_service=_embedding_service,
        analytics=_query_analytics,
    )

    logger.info("PKM server initialized successfully")


async def _shutdown():
    """Cleanup on server shutdown."""
    global _safe_processor, _query_analytics

    if _safe_processor:
        _safe_processor.stop()

    if _query_analytics:
        _query_analytics.flush()

    logger.info("PKM server shut down")


@asynccontextmanager
async def lifespan(app):
    """Manage server lifecycle - initialize on startup, cleanup on shutdown."""
    await _startup()
    yield
    await _shutdown()


# Initialize FastMCP server with lifespan manager
mcp = FastMCP(
    name="pkm-server",
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
    filters: Optional[dict] = None,
    debug: bool = False,
) -> dict:
    """
    Search the knowledge base for relevant information.

    Args:
        query: Natural language search query
        k: Number of results to return (default: 5)
        use_reranker: Apply cross-encoder re-ranking (default: True)
        use_hyde: Use HyDE query expansion (default: False)
        filters: Optional filters (e.g., {"file_type": "md", "category": "work"})
        debug: Return detailed debug information (default: False)

    Returns:
        Search results with content, sources, and optional debug info
    """
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.search_knowledge(
        query=query,
        k=k,
        use_reranker=use_reranker,
        use_hyde=use_hyde,
        filters=filters,
        debug=debug,
    )


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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.search_by_entity(
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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.list_recent_files(
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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.get_folder_structure(
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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.get_user_context()


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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.add_user_fact(fact=fact, category=category)


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
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.trigger_reindex(path=path, force=force)


@mcp.tool()
async def get_ingestion_queue() -> dict:
    """
    Get current ingestion queue status.

    Returns:
        Queue length, currently processing file, and recent completions
    """
    if not _pkm_tools:
        return {"error": "PKM tools not initialized"}

    return await _pkm_tools.get_ingestion_queue()


# === RESOURCE ENDPOINTS ===

@mcp.resource("pkm://status")
async def get_status_resource() -> str:
    """Get PKM system status as a resource."""
    status = await get_system_status()
    return f"PKM Status: {status}"


@mcp.resource("pkm://recent/{days}")
async def get_recent_resource(days: int = 7) -> str:
    """Get recent files as a resource."""
    files = await list_recent_files(days=days)
    return f"Recent files ({days} days): {len(files)} files"


# === SERVER ENTRY POINT ===

def create_app():
    """Create the FastMCP application."""
    return mcp


# For direct running
if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Run the server
    uvicorn.run(
        "src.mcp_server.server:mcp",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
