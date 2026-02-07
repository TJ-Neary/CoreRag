import gc
import logging
import os
import secrets
import threading
import time
from pathlib import Path

import psutil
import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from fastapi.templating import Jinja2Templates

from src.api.models import (
    DeleteResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsResponse,
)
from src.batch_processor import BatchProcessor
from src.config import DB_PATH, EMBEDDING_MODEL, STATE_DIR, validate_config
from src.exceptions import CoreRagError
from src.executor import execute_approved_item
from src.folder_manager import (
    ensure_folder_in_structure,
    get_folder_choices,
    load_folder_structure,
    save_folder_structure,
)
from src.intelligence import suggest_folder_structure
from src.staging import get_item, get_pending_items, update_item

# Logging (centralized: colored console, rotating file, JSON, error-only)
from src.utils.logging_config import setup_logging
from src.utils.query_sanitize import build_eq_clause, build_tag_clauses
from src.utils.tagging import TagManager

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CoreRag API",
    description="Local-first knowledge engine with RAG capabilities",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── API Key Authentication ──────────────────────────────────────────────────────
# Set CORERAG_API_KEY in .env or environment to enable authentication.
# If not set, API endpoints are open (for local development).

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_api_key() -> str | None:
    """Get the configured API key from environment."""
    return os.getenv("CORERAG_API_KEY")


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> bool:
    """
    Verify API key for protected endpoints.

    If CORERAG_API_KEY is not set, authentication is disabled (local dev mode).
    If set, the X-API-Key header must match.
    """
    expected_key = _get_api_key()

    # No key configured = auth disabled (local dev mode)
    if not expected_key:
        return True

    # Key configured but not provided
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key.encode(), expected_key.encode()):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    return True


# Ensure vault/archive/inbox directories exist
validate_config()

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "ui" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Singleton batch processor (for AI analysis phase)
_batch = BatchProcessor()
_batch_lock = threading.Lock()

# Singleton tag manager
_tag_manager = TagManager()

# ── Commit Runner (sequential, memory-safe) ──────────────────────────────────

MEMORY_PAUSE_THRESHOLD = 92  # Pause at this % RAM
MEMORY_RESUME_THRESHOLD = 88  # Resume when below this %
MEMORY_CHECK_INTERVAL = 2  # Seconds between checks while paused
COMMIT_BATCH_SIZE = 5  # Process this many, then check memory

_commit_state = {
    "status": "idle",  # idle | running | paused | stopped | complete | error
    "total": 0,
    "committed": 0,
    "current_file": "",
    "errors": [],
    "memory_pct": 0,
    "paused_reason": "",
}
_commit_lock = threading.Lock()
_commit_pause_requested = False
_commit_stop_requested = False


def _get_memory_pct() -> float:
    return psutil.virtual_memory().percent


def _wait_for_safe_memory() -> None:
    """Block until memory drops below resume threshold or stop is requested."""
    global _commit_stop_requested
    while _get_memory_pct() > MEMORY_RESUME_THRESHOLD:
        with _commit_lock:
            if _commit_stop_requested:
                return
            _commit_state["status"] = "paused"
            _commit_state["paused_reason"] = (
                f"Memory at {_get_memory_pct():.0f}%, waiting for <{MEMORY_RESUME_THRESHOLD}%"
            )
            _commit_state["memory_pct"] = _get_memory_pct()
        logger.warning(f"Commit paused: {_commit_state['paused_reason']}")
        gc.collect()
        time.sleep(MEMORY_CHECK_INTERVAL)

    with _commit_lock:
        _commit_state["status"] = "running"
        _commit_state["paused_reason"] = ""


def _run_commit(item_ids: list[str]) -> None:
    """Process approved items sequentially with memory safety."""
    global _commit_pause_requested, _commit_stop_requested
    _commit_pause_requested = False
    _commit_stop_requested = False

    with _commit_lock:
        _commit_state.update(
            {
                "status": "running",
                "total": len(item_ids),
                "committed": 0,
                "current_file": "",
                "errors": [],
                "memory_pct": _get_memory_pct(),
                "paused_reason": "",
            }
        )

    for i, item_id in enumerate(item_ids):
        # Check for stop
        with _commit_lock:
            if _commit_stop_requested:
                _commit_state["status"] = "stopped"
                _commit_state["current_file"] = ""
                _commit_state["paused_reason"] = (
                    f"Stopped by user after {i} of {len(item_ids)} files"
                )
                logger.info(f"Commit stopped by user after {i} files.")
                return

        # Check for user pause
        while _commit_pause_requested and not _commit_stop_requested:
            with _commit_lock:
                _commit_state["status"] = "paused"
                _commit_state["paused_reason"] = "Paused by user"
                _commit_state["memory_pct"] = _get_memory_pct()
            time.sleep(1)

        # Re-check stop after pause
        with _commit_lock:
            if _commit_stop_requested:
                _commit_state["status"] = "stopped"
                _commit_state["current_file"] = ""
                _commit_state["paused_reason"] = (
                    f"Stopped by user after {i} of {len(item_ids)} files"
                )
                logger.info(f"Commit stopped by user after {i} files.")
                return
            _commit_state["status"] = "running"
            _commit_state["paused_reason"] = ""

        # Memory check every COMMIT_BATCH_SIZE files
        if i > 0 and i % COMMIT_BATCH_SIZE == 0:
            mem = _get_memory_pct()
            with _commit_lock:
                _commit_state["memory_pct"] = mem
            if mem > MEMORY_PAUSE_THRESHOLD:
                _wait_for_safe_memory()

        item = get_item(item_id)
        filename = item.get("proposed", {}).get("filename", "unknown") if item else "unknown"

        with _commit_lock:
            _commit_state["current_file"] = filename
            _commit_state["memory_pct"] = _get_memory_pct()

        logger.info(f"Commit [{i + 1}/{len(item_ids)}]: {filename}")

        try:
            # Persist custom folder path
            if item:
                target_folder = item.get("proposed", {}).get("target_folder", "")
                if target_folder:
                    ensure_folder_in_structure(target_folder)

            success = execute_approved_item(item_id)
            if not success:
                with _commit_lock:
                    _commit_state["errors"].append(
                        {"file": filename, "error": "Execution returned False"}
                    )
        except Exception as e:
            logger.error(f"Commit error for {filename}: {e}", exc_info=True)
            with _commit_lock:
                _commit_state["errors"].append({"file": filename, "error": str(e)})

        with _commit_lock:
            _commit_state["committed"] = i + 1

        gc.collect()

    with _commit_lock:
        _commit_state["status"] = "complete"
        _commit_state["current_file"] = ""
        _commit_state["memory_pct"] = _get_memory_pct()

    logger.info(f"Commit complete: {len(item_ids)} files processed.")


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/queue")
async def get_queue():
    return get_pending_items()


@app.post("/api/update/{item_id}")
async def update_queue_item(item_id: str, updates: dict):
    success = update_item(item_id, updates)
    return {"success": success}


@app.post("/api/approve/{item_id}")
async def approve_queue_item(item_id: str, background_tasks: BackgroundTasks):
    item = get_item(item_id)
    if item:
        target_folder = item.get("proposed", {}).get("target_folder", "")
        if target_folder:
            ensure_folder_in_structure(target_folder)
    update_item(item_id, {"status": "approved"})
    background_tasks.add_task(execute_approved_item, item_id)
    return {"status": "approved", "message": "Processing started"}


# ── Batch Analysis Routes ────────────────────────────────────────────────────


@app.get("/api/inbox-count")
async def inbox_count():
    files = _batch.scan_inbox()
    return {"count": len(files), "files": [f.name for f in files]}


@app.post("/api/start-batch")
async def start_batch():
    with _batch_lock:
        if _batch.is_running():
            return {"status": "already_running"}

    def _run():
        _batch.process_all()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "started"}


@app.get("/api/progress")
async def get_progress():
    return _batch.get_progress()


@app.post("/api/batch-pause")
async def batch_pause():
    _batch.pause()
    return {"status": "paused"}


@app.post("/api/batch-resume")
async def batch_resume():
    _batch.resume()
    return {"status": "resumed"}


@app.post("/api/batch-stop")
async def batch_stop():
    _batch.stop()
    return {"status": "stopped"}


# ── Commit Routes (sequential, memory-safe) ──────────────────────────────────


@app.post("/api/commit-all")
async def commit_all():
    """Mark all pending items as approved and start sequential commit."""
    with _commit_lock:
        if _commit_state["status"] == "running" or _commit_state["status"] == "paused":
            return {"status": "already_running"}

    pending = get_pending_items()
    item_ids = []
    for item_id, item in pending.items():
        if item.get("status") == "pending":
            update_item(item_id, {"status": "approved"})
            item_ids.append(item_id)

    if not item_ids:
        return {"status": "no_items", "approved": 0}

    thread = threading.Thread(target=_run_commit, args=(item_ids,), daemon=True)
    thread.start()

    return {"status": "started", "approved": len(item_ids)}


@app.get("/api/commit-progress")
async def commit_progress():
    with _commit_lock:
        return dict(_commit_state)


@app.post("/api/commit-pause")
async def commit_pause():
    global _commit_pause_requested
    _commit_pause_requested = True
    return {"status": "paused"}


@app.post("/api/commit-resume")
async def commit_resume():
    global _commit_pause_requested
    _commit_pause_requested = False
    return {"status": "resumed"}


@app.post("/api/commit-stop")
async def commit_stop():
    global _commit_stop_requested, _commit_pause_requested
    _commit_stop_requested = True
    _commit_pause_requested = False
    return {"status": "stopped"}


# ── Folder Structure Routes ──────────────────────────────────────────────────


@app.get("/api/folder-structure")
async def get_folder_structure():
    structure = load_folder_structure()
    choices = get_folder_choices()
    return {"structure": structure, "choices": choices}


@app.post("/api/folder-structure")
async def update_folder_structure(structure: dict):
    save_folder_structure(structure)
    return {"success": True}


@app.post("/api/suggest-folders")
async def suggest_folders():
    pending = get_pending_items()
    if not pending:
        return {"error": "No pending items to organize"}

    documents = []
    for item_id, item in pending.items():
        documents.append(
            {
                "id": item_id,
                "filename": item.get("proposed", {}).get("filename", "unknown"),
                "category": item.get("proposed", {}).get("category", "Unsorted"),
                "summary": item.get("metadata", {}).get("summary", ""),
            }
        )

    existing = load_folder_structure()
    result = await suggest_folder_structure(documents, existing)

    if result.get("folders"):
        merged = existing.copy()
        merged["folders"] = result["folders"]
        save_folder_structure(merged)

    return result


# ── RAG Browser Routes ────────────────────────────────────────────────────────


@app.get("/api/rag-index")
async def rag_index():
    """Return a summary of all files indexed in the RAG database."""
    try:
        import lancedb

        db = lancedb.connect(DB_PATH)

        parents = db.open_table("parent_chunks")
        children = db.open_table("child_chunks")
        p_dict = parents.to_arrow().to_pydict()
        c_dict = children.to_arrow().to_pydict()

        # Group by source_path
        files = {}
        for i, sp in enumerate(p_dict.get("source_path", [])):
            if sp not in files:
                files[sp] = {
                    "source_path": sp,
                    "parent_chunks": 0,
                    "child_chunks": 0,
                    "preview": "",
                }
            files[sp]["parent_chunks"] += 1
            if not files[sp]["preview"] and p_dict.get("content"):
                files[sp]["preview"] = p_dict["content"][i][:200]

        for sp in c_dict.get("source_path", []):
            if sp in files:
                files[sp]["child_chunks"] += 1

        return {
            "files": sorted(files.values(), key=lambda f: f["source_path"]),
            "total_parents": len(p_dict.get("source_path", [])),
            "total_children": len(c_dict.get("source_path", [])),
        }
    except Exception as e:
        logger.error(f"RAG index query failed: {e}", exc_info=True)
        return {"files": [], "total_parents": 0, "total_children": 0, "error": str(e)}


@app.delete("/api/rag-index/{file_name}")
async def rag_delete(file_name: str):
    """Remove a file from the RAG database by source_path filename."""
    try:
        import lancedb

        db = lancedb.connect(DB_PATH)

        for table_name in ["parent_chunks", "child_chunks"]:
            tbl = db.open_table(table_name)
            tbl.delete(build_eq_clause("source_path", file_name))

        return {"success": True, "deleted": file_name}
    except Exception as e:
        logger.error(f"RAG delete failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ── RAG Verification Routes ──────────────────────────────────────────────────


@app.get("/api/rag-verify")
async def rag_verify():
    """Compare original documents against RAG-indexed content for quality check."""
    try:
        from src.rag_verify import verify_all

        results = verify_all()

        # Build summary
        total = len(results)
        good = sum(1 for r in results if r["status"] == "good")
        acceptable = sum(1 for r in results if r["status"] == "acceptable")
        degraded = sum(1 for r in results if r["status"] == "degraded")
        missing = sum(1 for r in results if r["status"] in ("not_in_rag", "original_not_found"))

        return {
            "summary": {
                "total": total,
                "good": good,
                "acceptable": acceptable,
                "degraded": degraded,
                "missing": missing,
            },
            "files": results,
        }
    except Exception as e:
        logger.error(f"RAG verification failed: {e}", exc_info=True)
        return {"error": str(e), "summary": {}, "files": []}


# ── Episodic Memory Routes ────────────────────────────────────────────────────


@app.get("/api/user-facts")
async def get_user_facts():
    """Get user facts and correction patterns for dashboard display."""
    try:
        from src.memory.episodic_memory import EpisodicMemoryManager

        storage_path = STATE_DIR / "profiles"
        manager = EpisodicMemoryManager(storage_path)
        profile = manager.load_or_create("default")

        facts = [
            {
                "content": f.content,
                "category": f.category.value,
                "confidence": f.confidence,
                "source": f.source,
                "created_at": f.created_at,
            }
            for f in profile.facts
        ]

        # Load correction patterns
        corrections = []
        try:
            from src.correction_log import _load_corrections

            raw = _load_corrections()
            for c in raw[-20:]:
                corrections.append(
                    {
                        "file": c.get("original_filename", ""),
                        "corrections": c.get("corrections", {}),
                        "timestamp": c.get("timestamp", ""),
                    }
                )
        except Exception:
            pass

        return {
            "user_name": profile.name,
            "facts": facts,
            "corrections": corrections,
            "total_facts": len(facts),
            "total_corrections": len(corrections),
        }
    except Exception as e:
        return {"error": str(e), "facts": [], "corrections": []}


@app.delete("/api/user-facts/{index}")
async def delete_user_fact(index: int):
    """Delete a user fact by index."""
    try:
        from src.memory.episodic_memory import EpisodicMemoryManager

        storage_path = STATE_DIR / "profiles"
        manager = EpisodicMemoryManager(storage_path)
        profile = manager.load_or_create("default")

        if 0 <= index < len(profile.facts):
            removed = profile.facts.pop(index)
            manager.save(profile)
            return {"success": True, "removed": removed.content}
        return {"success": False, "error": "Index out of range"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Chat Routes (LLM with RAG context) ───────────────────────────────────────


@app.post("/api/chat")
async def chat(request: Request):
    """Send a message to the LLM with optional RAG context."""
    body = await request.json()
    user_message = body.get("message", "")
    use_rag = body.get("use_rag", True)
    history = body.get("history", [])

    if not user_message:
        return {"error": "No message provided"}

    context_chunks = []
    sources = []

    # Retrieve RAG context if enabled
    if use_rag:
        try:
            import lancedb

            from src.embeddings.embedding_service import create_embedding_service

            db = lancedb.connect(DB_PATH)

            if "child_chunks" in db.table_names():
                embedder = create_embedding_service()
                query_vector = embedder.embed_query(user_message)
                table = db.open_table("child_chunks")
                results = table.search(query_vector).limit(5).to_list()

                for r in results:
                    content = r.get("content", "")
                    source = r.get("source_path", "unknown")
                    context_chunks.append(content)
                    if source not in sources:
                        sources.append(source)
        except Exception as e:
            logger.warning(f"RAG retrieval for chat failed: {e}")

    # Build prompt with context
    system_prompt = "You are a helpful assistant for a Personal Knowledge Management system. "
    if context_chunks:
        context_text = "\n\n---\n\n".join(context_chunks)
        system_prompt += (
            "Use the following retrieved documents to answer the user's question. "
            "Cite sources when relevant. If the documents don't contain the answer, say so.\n\n"
            f"Retrieved documents:\n{context_text}"
        )

    # Build messages for Ollama
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-10:]:  # Keep last 10 messages for context
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    # Call Ollama
    try:
        import httpx

        ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{ollama_host}/api/chat",
                json={"model": ollama_model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            assistant_message = data.get("message", {}).get("content", "")

        return {
            "response": assistant_message,
            "sources": sources,
            "model": ollama_model,
            "rag_used": bool(context_chunks),
        }
    except Exception as e:
        logger.error(f"Chat LLM call failed: {e}")
        return {"error": f"LLM call failed: {e}", "sources": sources}


# ── Tag Management Routes ────────────────────────────────────────────────────


@app.get("/api/tags")
async def list_tags():
    """List all known tags from the tag registry."""
    tags = _tag_manager.get_all_tags()
    return {
        "tags": [
            {
                "name": t.name,
                "color": t.color,
                "use_count": t.use_count,
                "description": t.description,
            }
            for t in tags
        ]
    }


@app.post("/api/tags/bulk")
async def bulk_tag(request: Request):
    """Apply a tag to all pending staged items."""
    body = await request.json()
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "No tag provided"}

    pending = get_pending_items()
    count = 0
    for item_id, item in pending.items():
        if item.get("status") in ("pending", "processing"):
            current_tags = item.get("proposed", {}).get("tags", [])
            if tag not in current_tags:
                current_tags.append(tag)
                update_item(item_id, {"proposed": {"tags": current_tags}})
                count += 1

    _tag_manager.create_tag(tag)
    return {"success": True, "applied_to": count, "tag": tag}


@app.post("/api/documents/{doc_id}/tags")
async def update_document_tags(doc_id: str, request: Request):
    """Update tags on an already-committed document in LanceDB."""
    body = await request.json()
    tags = body.get("tags", [])

    if not isinstance(tags, list):
        return {"error": "tags must be a list of strings"}

    tags_str = "," + ",".join(tags) + "," if tags else ""

    try:
        import lancedb

        db = lancedb.connect(DB_PATH)

        updated = 0
        for table_name in ["parent_chunks", "child_chunks"]:
            if table_name in db.table_names():
                tbl = db.open_table(table_name)
                # LanceDB update: delete + re-add rows matching document_id
                doc_filter = build_eq_clause("document_id", doc_id)
                rows = tbl.search().where(doc_filter).limit(10000).to_list()
                if rows:
                    for row in rows:
                        row["tags"] = tags_str
                    tbl.delete(doc_filter)
                    tbl.add(rows)
                    updated += len(rows)

        # Update tag manager registry
        _tag_manager.set_tags(doc_id, tags)

        return {"success": True, "document_id": doc_id, "tags": tags, "chunks_updated": updated}

    except Exception as e:
        logger.error(f"Tag update failed for {doc_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ── Legacy bulk approve (kept for backwards compat) ──────────────────────────


@app.post("/api/approve-all")
async def approve_all():
    """Redirects to commit-all for the new workflow."""
    return await commit_all()


# ── Core Memory API (v1) — For external AI systems ──────────────────────────


@app.get("/api/v1/manifest")
async def api_manifest():
    """
    Capability manifest for connecting AI systems.

    Returns schema info, available endpoints, accepted formats, and rules
    so any client (Claude Desktop, external AI assistants, local LLMs) can understand
    how to interact with the knowledge base.
    """
    import lancedb

    # Collect live stats
    stats = {"documents": 0, "chunks": 0, "entities": 0, "relationships": 0}
    try:
        db = lancedb.connect(DB_PATH)
        if "child_chunks" in db.table_names():
            stats["chunks"] = db.open_table("child_chunks").count_rows()
        if "parent_chunks" in db.table_names():
            sources = db.open_table("parent_chunks").to_arrow().column("source_path").to_pylist()
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
            "embedding_dimensions": 384,
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
            "enabled": bool(_get_api_key()),
            "type": "api_key",
            "header": "X-API-Key",
            "note": "This manifest endpoint is always public. All other endpoints require X-API-Key header when CORERAG_API_KEY is set.",
        },
        "stats": stats,
    }


@app.get("/api/v1/stats", response_model=StatsResponse)
async def api_stats(_: bool = Depends(verify_api_key)) -> StatsResponse:
    """Database statistics for health monitoring."""
    import lancedb

    db_path = str(DB_PATH)

    documents = 0
    parent_chunks = 0
    child_chunks = 0
    entities = 0
    relationships = 0

    try:
        db = lancedb.connect(db_path)
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


@app.post("/api/v1/search", response_model=SearchResponse)
async def api_search(
    request_body: SearchRequest, _: bool = Depends(verify_api_key)
) -> SearchResponse:
    """
    Semantic search over the knowledge base.

    Performs vector similarity search with optional HyDE expansion and tag filtering.
    """
    query = request_body.query
    k = request_body.k
    use_hyde = request_body.use_hyde
    tags = request_body.tags

    if not query:
        return SearchResponse(error="No query provided", results=[], total=0, query="")

    try:
        import lancedb

        from src.embeddings.embedding_service import create_embedding_service

        db_path = str(DB_PATH)
        db = lancedb.connect(db_path)

        if "child_chunks" not in db.table_names():
            return {"error": "No data indexed yet", "results": []}

        embedder = create_embedding_service()
        search_text = query

        # Optional HyDE expansion
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

        # Apply tag filtering if specified
        if tags:
            search_op = search_op.where(build_tag_clauses(tags))

        results_raw = search_op.to_list()

        results = []
        for r in results_raw:
            # Parse tags from comma-delimited string back to list
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


@app.post("/api/v1/ingest", response_model=IngestResponse)
async def api_ingest(
    request_body: IngestRequest, _: bool = Depends(verify_api_key)
) -> IngestResponse:
    """
    Ingest text content into the knowledge base.

    Chunks content, generates embeddings, and indexes for search.
    """
    import hashlib

    content = request_body.content
    source = request_body.source
    metadata = request_body.metadata

    try:
        from datetime import datetime

        import lancedb

        from src.chunking.parent_child import ParentChildChunker
        from src.embeddings.embedding_service import create_embedding_service

        db_path = str(DB_PATH)
        db = lancedb.connect(db_path)
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

        # Build comma-delimited tags string for LIKE-based filtering
        raw_tags = metadata.tags
        if raw_tags:
            tags_str = "," + ",".join(raw_tags) + ","
        else:
            tags_str = ""

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


@app.delete("/api/v1/documents/{document_id}", response_model=DeleteResponse)
async def api_delete_document(
    document_id: str, _: bool = Depends(verify_api_key)
) -> DeleteResponse:
    """Remove a document and all its chunks from the RAG database."""
    try:
        import lancedb

        db_path = str(DB_PATH)
        db = lancedb.connect(db_path)

        deleted = {"parent_chunks": 0, "child_chunks": 0}
        doc_filter = build_eq_clause("document_id", document_id)
        for table_name in ["parent_chunks", "child_chunks"]:
            if table_name in db.table_names():
                tbl = db.open_table(table_name)
                before = tbl.count_rows()
                tbl.delete(doc_filter)
                after = tbl.count_rows()
                deleted[table_name] = before - after

        # Also remove from knowledge graph
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
