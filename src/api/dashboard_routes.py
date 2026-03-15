"""
Dashboard & Internal API Routes

Handles the HITL dashboard UI, batch analysis, commit pipeline,
folder management, RAG browser, episodic memory, chat, and tag management.

All routes are internal (no API key auth) — the dashboard runs on localhost.
"""

import gc
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psutil
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src import config
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
from src.staging import batch_update_items, get_item, get_pending_items, load_manifest, update_item
from src.utils.query_sanitize import build_eq_clause
from src.utils.tagging import TagManager

logger = logging.getLogger(__name__)


# ── Commit Runner State ───────────────────────────────────────────────────────

_commit_state: dict[str, Any] = {
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

    # Pre-commit backup
    if config.BACKUP_ENABLED:
        try:
            from src.utils.backup import BackupManager
            from src.utils.backup_triggers import create_backup_if_needed

            backup_mgr = BackupManager(
                data_dir=config.STATE_DIR, max_backups=config.BACKUP_MAX_COUNT
            )
            create_backup_if_needed(
                backup_mgr,
                cooldown_hours=config.BACKUP_COMMIT_COOLDOWN_HOURS,
                backup_name="pre-commit",
            )
        except Exception as e:
            logger.warning("Pre-commit backup failed (continuing): %s", e)

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

    # ── Bulk Operations ─────────────────────────────────────────────────

    @router.post("/api/bulk-approve")
    async def bulk_approve(request: Request, background_tasks: BackgroundTasks) -> dict:
        body = await request.json()
        item_ids = body.get("item_ids", [])
        if not item_ids:
            return {"status": "error", "message": "No items specified"}
        approved = []
        for item_id in item_ids:
            item = get_item(item_id)
            if item and item.get("status") == "pending":
                target_folder = item.get("proposed", {}).get("target_folder", "")
                if target_folder:
                    ensure_folder_in_structure(target_folder)
                update_item(item_id, {"status": "approved"})
                background_tasks.add_task(execute_approved_item, item_id)
                approved.append(item_id)
        return {"status": "ok", "approved": len(approved), "items": approved}

    @router.post("/api/apply-to-similar")
    async def apply_to_similar(request: Request) -> dict:
        body = await request.json()
        target_folder = body.get("target_folder")
        category = body.get("category")
        if not target_folder:
            return {"status": "error", "message": "target_folder required"}
        manifest = load_manifest()
        updated = 0
        for item_id, item in manifest.items():
            if item.get("status") != "pending":
                continue
            if category and item.get("proposed", {}).get("category") != category:
                continue
            update_item(item_id, {"proposed": {"target_folder": target_folder}})
            updated += 1
        return {"status": "ok", "updated": updated, "target_folder": target_folder}

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
        item_ids = [item_id for item_id, item in pending.items() if item.get("status") == "pending"]
        if item_ids:
            batch_update_items({item_id: {"status": "approved"} for item_id in item_ids})

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

            # Select only metadata columns — avoid loading content and vector columns
            # (~30MB for vectors alone at 7,329 x 1024-dim float32)
            p_cols = (
                parents.to_arrow()
                .select([c for c in ["source_path", "content"] if c in parents.schema.names])
                .to_pydict()
            )
            c_cols = (
                children.to_arrow()
                .select([c for c in ["source_path"] if c in children.schema.names])
                .to_pydict()
            )

            files: dict = {}
            for i, sp in enumerate(p_cols.get("source_path", [])):
                if sp not in files:
                    files[sp] = {
                        "source_path": sp,
                        "parent_chunks": 0,
                        "child_chunks": 0,
                        "preview": "",
                    }
                files[sp]["parent_chunks"] += 1
                if not files[sp]["preview"] and p_cols.get("content"):
                    files[sp]["preview"] = p_cols["content"][i][:200]

            for sp in c_cols.get("source_path", []):
                if sp in files:
                    files[sp]["child_chunks"] += 1

            return {
                "files": sorted(files.values(), key=lambda f: f["source_path"]),
                "total_parents": len(p_cols.get("source_path", [])),
                "total_children": len(c_cols.get("source_path", [])),
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

    @router.post("/api/user-facts")
    async def add_user_fact(request: Request) -> dict:
        """Add a new user fact."""
        try:
            from src.memory.episodic_memory import (
                EpisodicMemoryManager,
                FactCategory,
                UserFact,
            )

            body = await request.json()
            content = body.get("content", "").strip()
            category = body.get("category", "personal")
            source = body.get("source", "explicit")

            if not content:
                return {"success": False, "error": "Content is required"}

            try:
                cat = FactCategory(category)
            except ValueError:
                valid = [c.value for c in FactCategory]
                return {"success": False, "error": f"Invalid category. Valid: {valid}"}

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            now = datetime.now().isoformat()
            fact = UserFact(
                content=content,
                category=cat,
                confidence=1.0,
                source=source,
                created_at=now,
                updated_at=now,
            )
            manager.add_fact(profile, fact)

            return {"success": True, "content": content, "category": category}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.get("/api/user-facts/stats")
    async def get_user_facts_stats() -> dict:
        """Get category breakdown and summary stats for user facts."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")

            categories: dict[str, int] = {}
            sources: dict[str, int] = {}
            for f in profile.facts:
                cat = f.category.value
                categories[cat] = categories.get(cat, 0) + 1
                sources[f.source] = sources.get(f.source, 0) + 1

            return {
                "total_facts": len(profile.facts),
                "categories": categories,
                "sources": sources,
                "user_name": profile.name,
            }
        except Exception as e:
            return {"error": str(e), "total_facts": 0, "categories": {}, "sources": {}}

    @router.get("/api/user-facts/export")
    async def export_user_profile() -> dict:
        """Export user profile as JSON."""
        try:
            from src.memory.episodic_memory import EpisodicMemoryManager

            storage_path = STATE_DIR / "profiles"
            manager = EpisodicMemoryManager(storage_path)
            profile = manager.load_or_create("default")
            return profile.to_dict()
        except Exception as e:
            return {"error": str(e)}

    # ── Query Analytics Routes ─────────────────────────────────────────────

    @router.get("/api/analytics/summary")
    async def get_analytics_summary(days: int = 7) -> dict:
        """Get query analytics summary."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            summary = analytics.get_summary(days=days)
            return {
                "total_queries": summary.total_queries,
                "unique_queries": summary.unique_queries,
                "avg_latency_ms": round(summary.avg_latency_ms, 1),
                "avg_results_count": round(summary.avg_results_count, 1),
                "avg_top_score": round(summary.avg_top_score, 3),
                "failed_queries": summary.failed_queries,
                "top_queries": [{"query": q, "count": c} for q, c in summary.top_queries],
                "quality_trend": summary.quality_trend,
                "period_days": days,
            }
        except Exception as e:
            return {"error": str(e), "total_queries": 0}

    @router.get("/api/analytics/failed")
    async def get_failed_queries(limit: int = 20) -> dict:
        """Get queries with poor results."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            failed = analytics.get_failed_queries(limit=limit)
            return {
                "failed_queries": [
                    {
                        "query": e.query,
                        "timestamp": e.timestamp,
                        "results_count": e.results_count,
                        "top_score": e.top_result_score,
                        "top_file": e.top_result_file,
                    }
                    for e in failed
                ],
                "total": len(failed),
            }
        except Exception as e:
            return {"error": str(e), "failed_queries": [], "total": 0}

    @router.get("/api/analytics/golden-suggestions")
    async def get_golden_suggestions(limit: int = 10) -> dict:
        """Get suggested additions to the Golden Set."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            suggestions = analytics.get_golden_set_suggestions(limit=limit)
            return {"suggestions": suggestions, "total": len(suggestions)}
        except Exception as e:
            return {"error": str(e), "suggestions": [], "total": 0}

    @router.get("/api/analytics/patterns")
    async def get_query_patterns() -> dict:
        """Get detected query patterns."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            patterns = analytics.get_patterns()
            return {
                "patterns": [
                    {
                        "pattern": p.pattern,
                        "frequency": p.frequency,
                        "avg_results": round(p.avg_results, 1),
                        "avg_score": round(p.avg_score, 3),
                        "last_seen": p.last_seen,
                        "examples": p.example_queries[:3],
                    }
                    for p in sorted(patterns, key=lambda x: -x.frequency)
                ],
                "total": len(patterns),
            }
        except Exception as e:
            return {"error": str(e), "patterns": [], "total": 0}

    @router.post("/api/analytics/feedback")
    async def log_query_feedback(request: Request) -> dict:
        """Log user feedback for a search query."""
        try:
            from src.analytics.query_analytics import QueryAnalytics

            body = await request.json()
            query = body.get("query", "")
            feedback = body.get("feedback", "")

            if not query or feedback not in ("good", "bad"):
                return {"success": False, "error": "Requires query and feedback (good/bad)"}

            analytics = QueryAnalytics(state_dir=STATE_DIR / "analytics")
            analytics.log_feedback(query, feedback)
            analytics.flush()
            return {"success": True, "query": query, "feedback": feedback}
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

                _db = getattr(request.app.state, "db", None)
                _embedder = getattr(request.app.state, "embedding_service", None)
                if not _db or not _embedder:
                    from src.embeddings.embedding_service import create_embedding_service

                    _db = lancedb.connect(DB_PATH)
                    _embedder = create_embedding_service()

                if "child_chunks" in _db.table_names():
                    query_vector = _embedder.embed_query(user_message)
                    table = _db.open_table("child_chunks")
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

        # Build user prompt from history + current message
        history_text = ""
        for h in history[-10:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            history_text += f"{role}: {content}\n"
        user_prompt = f"{history_text}user: {user_message}" if history_text else user_message

        try:
            from src.llm.provider import get_default_provider

            provider = get_default_provider()
            assistant_message = await provider.generate(system_prompt, user_prompt)

            return {
                "response": assistant_message,
                "sources": sources,
                "model": provider.config.model,
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
