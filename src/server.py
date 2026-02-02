import gc
import os
import threading
import logging
import time
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.staging import get_pending_items, update_item, get_item
from src.executor import execute_approved_item
from src.batch_processor import BatchProcessor
from src.folder_manager import (
    load_folder_structure,
    save_folder_structure,
    get_folder_choices,
    ensure_folder_in_structure,
)
from src.intelligence import suggest_folder_structure
from src.config import validate_config

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Ensure vault/archive/inbox directories exist
validate_config()

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "ui" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Singleton batch processor (for AI analysis phase)
_batch = BatchProcessor()
_batch_lock = threading.Lock()

# ── Commit Runner (sequential, memory-safe) ──────────────────────────────────

MEMORY_PAUSE_THRESHOLD = 92   # Pause at this % RAM
MEMORY_RESUME_THRESHOLD = 88  # Resume when below this %
MEMORY_CHECK_INTERVAL = 2     # Seconds between checks while paused
COMMIT_BATCH_SIZE = 5         # Process this many, then check memory

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
        _commit_state.update({
            "status": "running",
            "total": len(item_ids),
            "committed": 0,
            "current_file": "",
            "errors": [],
            "memory_pct": _get_memory_pct(),
            "paused_reason": "",
        })

    for i, item_id in enumerate(item_ids):
        # Check for stop
        with _commit_lock:
            if _commit_stop_requested:
                _commit_state["status"] = "stopped"
                _commit_state["current_file"] = ""
                _commit_state["paused_reason"] = f"Stopped by user after {i} of {len(item_ids)} files"
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
                _commit_state["paused_reason"] = f"Stopped by user after {i} of {len(item_ids)} files"
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
                    _commit_state["errors"].append({"file": filename, "error": "Execution returned False"})
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
        documents.append({
            "id": item_id,
            "filename": item.get("proposed", {}).get("filename", "unknown"),
            "category": item.get("proposed", {}).get("category", "Unsorted"),
            "summary": item.get("metadata", {}).get("summary", ""),
        })

    existing = load_folder_structure()
    result = suggest_folder_structure(documents, existing)

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
        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        db = lancedb.connect(db_path)

        parents = db.open_table("parent_chunks")
        children = db.open_table("child_chunks")
        p_dict = parents.to_arrow().to_pydict()
        c_dict = children.to_arrow().to_pydict()

        # Group by source_path
        files = {}
        for i, sp in enumerate(p_dict.get("source_path", [])):
            if sp not in files:
                files[sp] = {"source_path": sp, "parent_chunks": 0, "child_chunks": 0, "preview": ""}
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
        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        db = lancedb.connect(db_path)

        for table_name in ["parent_chunks", "child_chunks"]:
            tbl = db.open_table(table_name)
            tbl.delete(f"source_path = '{file_name}'")

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
        storage_path = Path.home() / ".corerag" / "profiles"
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
                corrections.append({
                    "file": c.get("original_filename", ""),
                    "corrections": c.get("corrections", {}),
                    "timestamp": c.get("timestamp", ""),
                })
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
        storage_path = Path.home() / ".corerag" / "profiles"
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

            db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
            db = lancedb.connect(db_path)

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

    db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))

    # Collect live stats
    stats = {"documents": 0, "chunks": 0, "entities": 0, "relationships": 0}
    try:
        db = lancedb.connect(db_path)
        if "child_chunks" in db.table_names():
            stats["chunks"] = db.open_table("child_chunks").count_rows()
        if "parent_chunks" in db.table_names():
            sources = db.open_table("parent_chunks").to_arrow().column("source_path").to_pylist()
            stats["documents"] = len(set(sources))
    except Exception:
        pass

    try:
        from src.graph.knowledge_graph import KnowledgeGraph
        graph_db_path = Path(os.getenv("CoreRag_STATE_DIR", str(Path.home() / ".corerag"))) / "knowledge_graph.db"
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
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dimensions": 384,
            "chunking_strategy": "parent-child (512 token children, 2048 token parents)",
            "vector_db": "LanceDB",
            "tables": {
                "parent_chunks": {
                    "fields": ["id", "document_id", "content", "source_path",
                               "section_title", "token_count", "created_at"],
                    "description": "Full-context parent chunks for retrieval augmentation",
                },
                "child_chunks": {
                    "fields": ["id", "parent_id", "document_id", "content",
                               "vector", "chunk_index", "source_path"],
                    "description": "Embedded child chunks for vector search",
                },
            },
        },
        "capabilities": {
            "search": {
                "endpoint": "/api/v1/search",
                "method": "POST",
                "description": "Semantic search over the knowledge base",
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
        "stats": stats,
    }


@app.get("/api/v1/stats")
async def api_stats():
    """Database statistics for health monitoring."""
    import lancedb

    db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))

    stats = {
        "documents": 0,
        "parent_chunks": 0,
        "child_chunks": 0,
        "entities": 0,
        "relationships": 0,
    }

    try:
        db = lancedb.connect(db_path)
        if "parent_chunks" in db.table_names():
            pt = db.open_table("parent_chunks")
            stats["parent_chunks"] = pt.count_rows()
            sources = pt.to_arrow().column("source_path").to_pylist()
            stats["documents"] = len(set(sources))
        if "child_chunks" in db.table_names():
            stats["child_chunks"] = db.open_table("child_chunks").count_rows()
    except Exception as e:
        logger.error(f"Stats query failed: {e}")

    try:
        from src.graph.knowledge_graph import KnowledgeGraph
        graph_db_path = Path(os.getenv("CoreRag_STATE_DIR", str(Path.home() / ".corerag"))) / "knowledge_graph.db"
        if graph_db_path.exists():
            graph = KnowledgeGraph(graph_db_path)
            gs = graph.get_stats()
            stats["entities"] = gs["total_entities"]
            stats["relationships"] = gs["total_relationships"]
    except Exception:
        pass

    return stats


@app.post("/api/v1/search")
async def api_search(request: Request):
    """
    Semantic search over the knowledge base.

    Input: {"query": "...", "k": 5, "use_hyde": false}
    Output: {"results": [...], "total": N}
    """
    body = await request.json()
    query = body.get("query", "")
    k = body.get("k", 5)
    use_hyde = body.get("use_hyde", False)

    if not query:
        return {"error": "No query provided", "results": []}

    try:
        import lancedb
        from src.embeddings.embedding_service import create_embedding_service

        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
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
        results_raw = child_table.search(query_vector).limit(k).to_list()

        results = []
        for r in results_raw:
            results.append({
                "content": r.get("content", ""),
                "source_path": r.get("source_path", ""),
                "document_id": r.get("document_id", ""),
                "parent_id": r.get("parent_id", ""),
                "chunk_index": r.get("chunk_index", 0),
                "score": float(r.get("_distance", 0)),
            })

        return {"results": results, "total": len(results), "query": query}

    except Exception as e:
        logger.error(f"Search API failed: {e}", exc_info=True)
        return {"error": str(e), "results": []}


@app.post("/api/v1/ingest")
async def api_ingest(request: Request):
    """
    Ingest text content into the knowledge base.

    Input: {
        "content": "...",
        "source": "ai-assistant-note",
        "metadata": {"category": "notes", "year": "2026", "tags": []}
    }
    Output: {"document_id": "abc123", "chunks_created": 12}
    """
    import hashlib

    body = await request.json()
    content = body.get("content", "")
    source = body.get("source", "api-ingest")
    metadata = body.get("metadata", {})

    if not content:
        return {"error": "No content provided"}

    if len(content) > 100000:
        return {"error": f"Content too large ({len(content)} chars). Max 100,000."}

    try:
        import lancedb
        from src.chunking.parent_child import ParentChildChunker
        from src.embeddings.embedding_service import create_embedding_service
        from datetime import datetime

        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
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
                "category": metadata.get("category", ""),
                "year": metadata.get("year", ""),
            },
        )

        if not children:
            return {"error": "Content too short to create chunks", "document_id": document_id}

        child_texts = [c.content for c in children]
        embeddings = embedder.embed_documents(child_texts, show_progress=False)

        parent_data = []
        for p in parents:
            parent_data.append({
                "id": p.id,
                "document_id": p.document_id,
                "content": p.content,
                "source_path": source,
                "section_title": p.section_title or "",
                "token_count": p.token_count,
                "created_at": datetime.now().isoformat(),
            })

        child_data = []
        for c, emb in zip(children, embeddings):
            child_data.append({
                "id": c.id,
                "parent_id": c.parent_id,
                "document_id": c.document_id,
                "content": c.content,
                "vector": emb,
                "chunk_index": c.chunk_index,
                "source_path": source,
            })

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
            from src.graph.knowledge_graph import KnowledgeGraph, EntityExtractor
            graph_db_path = Path(os.getenv("CoreRag_STATE_DIR", str(Path.home() / ".corerag"))) / "knowledge_graph.db"
            if graph_db_path.exists():
                graph = KnowledgeGraph(graph_db_path)
                extractor = EntityExtractor()
                entities, relationships = extractor._extract_with_patterns(content[:10000], document_id)
                if entities or relationships:
                    graph.add_from_extraction(entities, relationships)
        except Exception as e:
            logger.debug(f"Entity extraction skipped during API ingest: {e}")

        logger.info(f"API ingest: {source} ({len(parents)} parents, {len(children)} children)")

        return {
            "document_id": document_id,
            "source": source,
            "chunks_created": len(children),
            "parent_chunks": len(parents),
        }

    except Exception as e:
        logger.error(f"Ingest API failed: {e}", exc_info=True)
        return {"error": str(e)}


@app.delete("/api/v1/documents/{document_id}")
async def api_delete_document(document_id: str):
    """Remove a document and all its chunks from the RAG database."""
    try:
        import lancedb

        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        db = lancedb.connect(db_path)

        deleted = {"parent_chunks": 0, "child_chunks": 0}
        for table_name in ["parent_chunks", "child_chunks"]:
            if table_name in db.table_names():
                tbl = db.open_table(table_name)
                before = tbl.count_rows()
                tbl.delete(f"document_id = '{document_id}'")
                after = tbl.count_rows()
                deleted[table_name] = before - after

        # Also remove from knowledge graph
        try:
            from src.graph.knowledge_graph import KnowledgeGraph
            graph_db_path = Path(os.getenv("CoreRag_STATE_DIR", str(Path.home() / ".corerag"))) / "knowledge_graph.db"
            if graph_db_path.exists():
                graph = KnowledgeGraph(graph_db_path)
                graph.delete_by_document(document_id)
        except Exception:
            pass

        total_deleted = deleted["parent_chunks"] + deleted["child_chunks"]
        if total_deleted == 0:
            return {"success": False, "error": f"Document not found: {document_id}"}

        return {
            "success": True,
            "document_id": document_id,
            "deleted_chunks": deleted,
        }

    except Exception as e:
        logger.error(f"Delete API failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
