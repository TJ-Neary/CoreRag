"""
CoreRag Dashboard & API Server

App factory that mounts dashboard and API v1 routers.

Run with: python -m src.server
"""

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src import config
from src.api.dashboard_routes import DashboardState, create_dashboard_router
from src.api.v1_routes import create_v1_router, limiter
from src.batch_processor import BatchProcessor
from src.config import validate_config
from src.utils.logging_config import setup_logging
from src.utils.tagging import TagManager

setup_logging()
logger = logging.getLogger(__name__)

# ── Startup / Shutdown ────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run integrity checks and auto-backup on startup."""
    if config.BACKUP_INTEGRITY_CHECK:
        from src.utils.backup_triggers import check_database_integrity

        result = check_database_integrity(config.DB_PATH)
        for error in result["errors"]:
            logger.error("DB integrity: %s", error)
        for warning in result["warnings"]:
            logger.warning("DB integrity: %s", warning)
        if result["table_counts"]:
            logger.info("DB integrity: table counts %s", result["table_counts"])

    if config.BACKUP_ENABLED:
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import create_backup_if_needed

        mgr = BackupManager(data_dir=config.STATE_DIR, max_backups=config.BACKUP_MAX_COUNT)
        create_backup_if_needed(
            mgr,
            cooldown_hours=config.BACKUP_STARTUP_COOLDOWN_HOURS,
            backup_name="startup",
        )

    yield


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="CoreRag API",
    description="Local-first knowledge engine with RAG capabilities",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── API Key Authentication ────────────────────────────────────────────────────
# Set CORERAG_API_KEY in .env or environment to enable authentication.
# If not set, API endpoints are open (for local development).

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> bool:
    """
    Verify API key for protected endpoints.

    If CORERAG_API_KEY is not set, authentication is disabled (local dev mode).
    If set, the X-API-Key header must match.
    """
    expected_key = os.getenv("CORERAG_API_KEY")

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
        raise HTTPException(status_code=403, detail="Invalid API key")

    return True


# ── Initialization ────────────────────────────────────────────────────────────

validate_config()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "ui" / "templates"))

# Shared state
_batch = BatchProcessor()
_batch_lock = threading.Lock()
_tag_manager = TagManager()

# ── Mount Routers ─────────────────────────────────────────────────────────────

_dashboard_state = DashboardState(
    batch=_batch,
    batch_lock=_batch_lock,
    tag_manager=_tag_manager,
    templates=templates,
)

app.include_router(create_dashboard_router(_dashboard_state))
app.include_router(create_v1_router(verify_api_key))

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
