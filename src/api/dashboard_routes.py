"""
Dashboard & Internal API Routes

Handles the HITL dashboard UI, batch analysis, commit pipeline,
folder management, RAG browser, episodic memory, chat, and tag management.

All routes are internal (no API key auth) — the dashboard runs on localhost.
"""

import gc
import logging
import os
import threading
import time
from dataclasses import dataclass

import psutil
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.batch_processor import BatchProcessor
from src.config import (
    BATCH_MEMORY_PAUSE_PCT,
    BATCH_MEMORY_RESUME_PCT,
    COMMIT_BATCH_SIZE,
    DB_PATH,
    MEMORY_CHECK_INTERVAL_SEC,
    STATE_DIR,
)
from src.executor import execute_approved_item
from src.folder_manager import (
    ensure_folder_in_structure,
    get_folder_choices,
    load_folder_structure,
    save_folder_structure,
)
from src.intelligence import suggest_folder_structure
from src.staging import get_item, get_pending_items, update_item
from src.utils.query_sanitize import build_eq_clause
from src.utils.tagging import TagManager

logger = logging.getLogger(__name__)


# ── Commit Runner State ───────────────────────────────────────────────────────

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
    while _get_memory_pct() > BATCH_MEMORY_RESUME_PCT:
        with _commit_lock:
            if _commit_stop_requested:
                return
            _commit_state["status"] = "paused"
            _commit_state["paused_reason"] = (
                f"Memory at {_get_memory_pct():.0f}%, waiting for <{BATCH_MEMORY_RESUME_PCT}%"
            )
            _commit_state["memory_pct"] = _get_memory_pct()
        logger.warning(f"Commit paused: {_commit_state['paused_reason']}")
        gc.collect()
        time.sleep(MEMORY_CHECK_INTERVAL_SEC)

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
            if mem > BATCH_MEMORY_PAUSE_PCT:
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


# ── Dashboard State ───────────────────────────────────────────────────────────


@dataclass
class DashboardState:
    """Shared state objects passed from the app factory in server.py."""

    batch: BatchProcessor
    batch_lock: threading.Lock
    tag_manager: TagManager
    templates: Jinja2Templates


# ── Router Factory ────────────────────────────────────────────────────────────


def create_dashboard_router(state: DashboardState) -> APIRouter:
    """Create the dashboard router with all internal routes."""
    router = APIRouter()

    # ── Dashboard HTML ────────────────────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return state.templates.TemplateResponse("dashboard.html", {"request": request})

    # ── Queue Routes ──────────────────────────────────────────────────────

    @router.get("/api/queue")
    async def get_queue() -> dict:
        return get_pending_items()

    @router.post("/api/update/{item_id}")
    async def update_queue_item(item_id: str, updates: dict) -> dict:
        success = update_item(item_id, updates)
        return {"success": success}

    @router.post("/api/approve/{item_id}")
    async def approve_queue_item(item_id: str, background_tasks: BackgroundTasks) -> dict:
        item = get_item(item_id)
        if item:
            target_folder = item.get("proposed", {}).get("target_folder", "")
            if target_folder:
                ensure_folder_in_structure(target_folder)
        update_item(item_id, {"status": "approved"})
        background_tasks.add_task(execute_approved_item, item_id)
        return {"status": "approved", "message": "Processing started"}

    # ── Batch Analysis Routes ─────────────────────────────────────────────

    @router.get("/api/inbox-count")
    async def inbox_count() -> dict:
        files = state.batch.scan_inbox()
        return {"count": len(files), "files": [f.name for f in files]}

    @router.post("/api/start-batch")
    async def start_batch() -> dict:
        with state.batch_lock:
            if state.batch.is_running():
                return {"status": "already_running"}

        def _run() -> None:
            state.batch.process_all()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {"status": "started"}

    @router.get("/api/progress")
    async def get_progress() -> dict:
        return state.batch.get_progress()

    @router.post("/api/batch-pause")
    async def batch_pause() -> dict:
        state.batch.pause()
        return {"status": "paused"}

    @router.post("/api/batch-resume")
    async def batch_resume() -> dict:
        state.batch.resume()
        return {"status": "resumed"}

    @router.post("/api/batch-stop")
    async def batch_stop() -> dict:
        state.batch.stop()
        return {"status": "stopped"}

    # ── Commit Routes (sequential, memory-safe) ──────────────────────────

    @router.post("/api/commit-all")
    async def commit_all() -> dict:
        """Mark all pending items as approved and start sequential commit."""
        with _commit_lock:
            if _commit_state["status"] in ("running", "paused"):
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

    @router.get("/api/commit-progress")
    async def commit_progress() -> dict:
        with _commit_lock:
            return dict(_commit_state)

    @router.post("/api/commit-pause")
    async def commit_pause() -> dict:
        global _commit_pause_requested
        _commit_pause_requested = True
        return {"status": "paused"}

    @router.post("/api/commit-resume")
    async def commit_resume() -> dict:
        global _commit_pause_requested
        _commit_pause_requested = False
        return {"status": "resumed"}

    @router.post("/api/commit-stop")
    async def commit_stop() -> dict:
        global _commit_stop_requested, _commit_pause_requested
        _commit_stop_requested = True
        _commit_pause_requested = False
        return {"status": "stopped"}

    # ── Folder Structure Routes ───────────────────────────────────────────

    @router.get("/api/folder-structure")
    async def get_folder_structure() -> dict:
        structure = load_folder_structure()
        choices = get_folder_choices()
        return {"structure": structure, "choices": choices}

    @router.post("/api/folder-structure")
    async def update_folder_structure(structure: dict) -> dict:
        save_folder_structure(structure)
        return {"success": True}

    @router.post("/api/suggest-folders")
    async def suggest_folders() -> dict:
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

    # ── RAG Browser Routes ────────────────────────────────────────────────

    @router.get("/api/rag-index")
    async def rag_index() -> dict:
        """Return a summary of all files indexed in the RAG database."""
        try:
            import lancedb

            db = lancedb.connect(DB_PATH)

            parents = db.open_table("parent_chunks")
            children = db.open_table("child_chunks")
            p_dict = parents.to_arrow().to_pydict()
            c_dict = children.to_arrow().to_pydict()

            files: dict = {}
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

    @router.delete("/api/rag-index/{file_name}")
    async def rag_delete(file_name: str) -> dict:
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

    # ── RAG Verification ──────────────────────────────────────────────────

    @router.get("/api/rag-verify")
    async def rag_verify() -> dict:
        """Compare original documents against RAG-indexed content."""
        try:
            from src.rag_verify import verify_all

            results = verify_all()

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

    # ── Episodic Memory Routes ────────────────────────────────────────────

    @router.get("/api/user-facts")
    async def get_user_facts() -> dict:
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

    @router.delete("/api/user-facts/{index}")
    async def delete_user_fact(index: int) -> dict:
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

    # ── Chat Routes (LLM with RAG context) ────────────────────────────────

    @router.post("/api/chat")
    async def chat(request: Request) -> dict:
        """Send a message to the LLM with optional RAG context."""
        body = await request.json()
        user_message = body.get("message", "")
        use_rag = body.get("use_rag", True)
        history = body.get("history", [])

        if not user_message:
            return {"error": "No message provided"}

        context_chunks = []
        sources: list[str] = []

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

        system_prompt = "You are a helpful assistant for a Personal Knowledge Management system. "
        if context_chunks:
            context_text = "\n\n---\n\n".join(context_chunks)
            system_prompt += (
                "Use the following retrieved documents to answer the user's question. "
                "Cite sources when relevant. If the documents don't contain the answer, "
                "say so.\n\n"
                f"Retrieved documents:\n{context_text}"
            )

        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": user_message})

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

    # ── Tag Management Routes ─────────────────────────────────────────────

    @router.get("/api/tags")
    async def list_tags() -> dict:
        """List all known tags from the tag registry."""
        tags = state.tag_manager.get_all_tags()
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

    @router.post("/api/tags/bulk")
    async def bulk_tag(request: Request) -> dict:
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

        state.tag_manager.create_tag(tag)
        return {"success": True, "applied_to": count, "tag": tag}

    @router.post("/api/documents/{doc_id}/tags")
    async def update_document_tags(doc_id: str, request: Request) -> dict:
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
                    doc_filter = build_eq_clause("document_id", doc_id)
                    rows = tbl.search().where(doc_filter).limit(10000).to_list()
                    if rows:
                        for row in rows:
                            row["tags"] = tags_str
                        tbl.delete(doc_filter)
                        tbl.add(rows)
                        updated += len(rows)

            state.tag_manager.set_tags(doc_id, tags)

            return {
                "success": True,
                "document_id": doc_id,
                "tags": tags,
                "chunks_updated": updated,
            }

        except Exception as e:
            logger.error(f"Tag update failed for {doc_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ── Legacy ────────────────────────────────────────────────────────────

    @router.post("/api/approve-all")
    async def approve_all() -> dict:
        """Redirects to commit-all for the new workflow."""
        return await commit_all()

    return router
