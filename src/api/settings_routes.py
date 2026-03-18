"""
Settings API — Dashboard-only endpoints for agent CRUD, LLM config, and DB management.

All endpoints reject requests that include an X-API-Key header (dashboard-only,
localhost trust). External agents must not be able to modify settings.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def _reject_api_key(request: Request) -> JSONResponse | None:
    """Block any request that carries an API key — settings are dashboard-only."""
    if request.headers.get("X-API-Key"):
        return JSONResponse(
            status_code=403,
            content={"error": "Settings are dashboard-only"},
        )
    return None


def create_settings_router() -> APIRouter:
    """Factory that returns a settings APIRouter with all endpoints."""
    router = APIRouter(tags=["settings"])

    # ── 1. Full settings + restart_required ──────────────────────────────

    @router.get("/api/settings", response_model=None)
    async def get_settings(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            from src.config import LLM_PROVIDER, OLLAMA_MODEL
            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            mgr.load()

            agents = mgr.get_agents()
            llm_cfg = mgr.get_llm_config()

            restart_required = (
                llm_cfg.get("provider") and llm_cfg["provider"] != LLM_PROVIDER
            ) or (llm_cfg.get("ollama_model") and llm_cfg["ollama_model"] != OLLAMA_MODEL)

            return {
                "settings": {
                    "agents": agents,
                    "llm": llm_cfg,
                },
                "restart_required": bool(restart_required),
            }
        except Exception:
            logger.exception("Error loading settings")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 2. List agents ───────────────────────────────────────────────────

    @router.get("/api/settings/agents", response_model=None)
    async def list_agents(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            agents = mgr.get_agents()
            return {"agents": agents}
        except Exception:
            logger.exception("Error listing agents")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 3. Create agent ──────────────────────────────────────────────────

    @router.post("/api/settings/agents", response_model=None)
    async def create_agent(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            body = await request.json()
            name = body.get("name", "").strip()
            if not name:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Agent name is required"},
                )

            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            api_key = mgr.create_agent(name)
            agent = mgr.get_agent(name)

            return {
                "name": name,
                "api_key": api_key,
                "permissions": agent["permissions"] if agent else {},
            }
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        except Exception:
            logger.exception("Error creating agent")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 4. Update agent permissions ──────────────────────────────────────

    @router.put("/api/settings/agents/{name}", response_model=None)
    async def update_agent(name: str, request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            body = await request.json()
            permissions = body.get("permissions")
            if permissions is None:
                return JSONResponse(
                    status_code=422,
                    content={"error": "permissions field is required"},
                )

            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            mgr.update_agent(name, permissions)
            agent = mgr.get_agent(name)

            return {"name": name, "permissions": agent["permissions"] if agent else {}}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception:
            logger.exception("Error updating agent '%s'", name)
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 5. Delete agent ──────────────────────────────────────────────────

    @router.delete("/api/settings/agents/{name}", response_model=None)
    async def delete_agent(name: str, request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            mgr.delete_agent(name)
            return {"status": "deleted", "name": name}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception:
            logger.exception("Error deleting agent '%s'", name)
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 6. Update LLM config ────────────────────────────────────────────

    @router.put("/api/settings/llm", response_model=None)
    async def update_llm(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            body = await request.json()
            kwargs: dict[str, Any] = {}
            for key in ("provider", "model", "ollama_model", "api_key_name", "api_key_value"):
                if key in body:
                    kwargs[key] = body[key]

            if not kwargs:
                return JSONResponse(
                    status_code=422,
                    content={"error": "No LLM config fields provided"},
                )

            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            mgr.update_llm_config(**kwargs)

            return {"status": "updated", "llm": mgr.get_llm_config()}
        except Exception:
            logger.exception("Error updating LLM config")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 7. List available Ollama models ──────────────────────────────────

    @router.get("/api/settings/ollama-models", response_model=None)
    async def ollama_models(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            import httpx

            from src.config import OLLAMA_HOST

            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("Failed to fetch Ollama models: %s", e)
            return JSONResponse(
                status_code=502,
                content={"error": f"Cannot reach Ollama: {e}"},
            )

    # ── 8. Model status ─────────────────────────────────────────────────

    @router.get("/api/settings/model-status", response_model=None)
    async def model_status(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            from src.config import (
                EMBEDDING_MODEL,
                LLM_MODEL,
                LLM_PROVIDER,
                OLLAMA_MODEL,
                RERANKER_MODEL,
            )
            from src.settings.settings_manager import SettingsManager

            mgr = SettingsManager()
            llm_cfg = mgr.get_llm_config()

            restart_required = (
                llm_cfg.get("provider") and llm_cfg["provider"] != LLM_PROVIDER
            ) or (llm_cfg.get("ollama_model") and llm_cfg["ollama_model"] != OLLAMA_MODEL)

            return {
                "llm_provider": LLM_PROVIDER or "auto-detect",
                "llm_model": LLM_MODEL or "provider default",
                "ollama_model": OLLAMA_MODEL,
                "embedding_model": EMBEDDING_MODEL,
                "reranker_model": RERANKER_MODEL,
                "restart_required": bool(restart_required),
            }
        except Exception:
            logger.exception("Error getting model status")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 9. Database stats ────────────────────────────────────────────────

    @router.get("/api/settings/db-stats", response_model=None)
    async def db_stats(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            import lancedb

            from src.config import DB_PATH, RESTRICTED_DB_PATH

            stats: dict[str, Any] = {"main": {}, "restricted": {}}

            for label, db_path in [("main", DB_PATH), ("restricted", RESTRICTED_DB_PATH)]:
                path = Path(db_path)
                if not path.exists():
                    stats[label] = {"exists": False}
                    continue

                db = lancedb.connect(str(path))
                table_names = db.table_names()
                tables: dict[str, int] = {}
                for tname in table_names:
                    try:
                        table = db.open_table(tname)
                        tables[tname] = table.count_rows()
                    except Exception:
                        tables[tname] = -1

                # Calculate directory size
                size_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                stats[label] = {
                    "exists": True,
                    "path": str(path),
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "tables": tables,
                }

            return stats
        except Exception:
            logger.exception("Error getting DB stats")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # ── 10. Database actions ─────────────────────────────────────────────

    @router.post("/api/settings/db-action", response_model=None)
    async def db_action(request: Request):  # type: ignore[no-untyped-def]
        reject = await _reject_api_key(request)
        if reject:
            return reject
        try:
            body = await request.json()
            action = body.get("action", "")

            valid_actions = {
                "optimize_main",
                "optimize_restricted",
                "backup",
                "health_check",
            }
            if action not in valid_actions:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Invalid action '{action}'. "
                        f"Valid: {', '.join(sorted(valid_actions))}"
                    },
                )

            if action == "optimize_main":
                from src.config import DB_PATH
                from src.maintenance.db_optimizer import LanceDBOptimizer

                optimizer = LanceDBOptimizer(db_path=DB_PATH)
                results = optimizer.optimize_all()
                return {
                    "action": action,
                    "status": "completed",
                    "results": [
                        {
                            "table": r.table_name,
                            "success": r.success,
                            "space_saved_mb": round(r.space_saved_mb, 2),
                            "duration_seconds": round(r.duration_seconds, 2),
                            "error": r.error,
                        }
                        for r in results
                    ],
                }

            elif action == "optimize_restricted":
                from src.config import RESTRICTED_DB_PATH
                from src.maintenance.db_optimizer import LanceDBOptimizer

                optimizer = LanceDBOptimizer(db_path=RESTRICTED_DB_PATH)
                results = optimizer.optimize_all()
                return {
                    "action": action,
                    "status": "completed",
                    "results": [
                        {
                            "table": r.table_name,
                            "success": r.success,
                            "space_saved_mb": round(r.space_saved_mb, 2),
                            "duration_seconds": round(r.duration_seconds, 2),
                            "error": r.error,
                        }
                        for r in results
                    ],
                }

            elif action == "backup":
                from src.config import BACKUP_MAX_COUNT, STATE_DIR
                from src.utils.backup import BackupManager

                mgr = BackupManager(data_dir=STATE_DIR, max_backups=BACKUP_MAX_COUNT)
                info = mgr.create_backup(backup_name="manual", backup_type="full")
                return {
                    "action": action,
                    "status": "completed",
                    "backup": {
                        "name": info.name,
                        "timestamp": info.timestamp,
                        "size_mb": round(info.size_bytes / (1024 * 1024), 2),
                        "path": info.path,
                    },
                }

            elif action == "health_check":
                from src.config import DB_PATH
                from src.maintenance.health_check import HealthChecker

                checker = HealthChecker(db_path=DB_PATH)
                report = checker.full_report()
                return {
                    "action": action,
                    "status": "completed",
                    "report": report.to_dict(),
                }

            # Unreachable but satisfies type checker
            return JSONResponse(status_code=400, content={"error": "Unknown action"})

        except Exception:
            logger.exception("Error executing DB action")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    return router
