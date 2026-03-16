"""
CoreRag Dashboard & API Server

App factory that mounts dashboard and API v1 routers.

Run with: python -m src.server
"""

import atexit
import logging
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src import config
from src.api.dashboard_routes import DashboardState, create_dashboard_router
from src.api.settings_routes import create_settings_router
from src.api.v1_routes import create_v1_router, limiter
from src.batch_processor import BatchProcessor
from src.config import validate_config
from src.settings.settings_manager import DEFAULT_PERMISSIONS, SettingsManager
from src.utils.logging_config import setup_logging
from src.utils.tagging import TagManager

setup_logging()
logger = logging.getLogger(__name__)

# ── Startup / Shutdown ────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run integrity checks and auto-backup on startup."""
    if config.BACKUP_INTEGRITY_CHECK:
        from src.maintenance.health_check import HealthChecker

        report = HealthChecker(db_path=config.DB_PATH).quick_check()
        for error in report.errors:
            logger.error("DB integrity: %s", error)
        for warning in report.warnings:
            logger.warning("DB integrity: %s", warning)
        if report.tables:
            counts = {t.name: t.rows for t in report.tables}
            logger.info("DB integrity: table counts %s", counts)

    if config.BACKUP_ENABLED:
        from src.utils.backup import BackupManager
        from src.utils.backup_triggers import create_backup_if_needed

        mgr = BackupManager(data_dir=config.STATE_DIR, max_backups=config.BACKUP_MAX_COUNT)
        create_backup_if_needed(
            mgr,
            cooldown_hours=config.BACKUP_STARTUP_COOLDOWN_HOURS,
            backup_name="startup",
        )

    settings = _get_settings_mgr()
    registered_agents = settings.get_agents()
    if not any(n for n in registered_agents if not n.startswith("_")):
        logger.warning("No external agents configured — API running in open mode")

    # Prune completed items from staging manifest
    try:
        from src.staging import cleanup_manifest

        pruned = cleanup_manifest()
        if pruned:
            logger.info(f"Staging manifest: pruned {pruned} completed items")
    except Exception as e:
        logger.debug(f"Manifest cleanup skipped: {e}")

    # Database integrity check — auto-clean orphaned parents
    try:
        from src.quality.batch_validator import validate_database_integrity

        integrity = validate_database_integrity()
        if integrity.get("orphaned_parents_cleaned", 0) > 0:
            logger.info(
                f"DB integrity: cleaned {integrity['orphaned_parents_cleaned']} orphaned parents"
            )
    except Exception as e:
        logger.debug(f"Integrity check skipped: {e}")

    # Initialize shared services for API routes (same as MCP server does)
    try:
        import lancedb

        from src.embeddings.embedding_service import create_embedding_service
        from src.search.hybrid_search import HybridSearcher
        from src.search.reranker import CrossEncoderReranker

        db = lancedb.connect(str(config.DB_PATH))
        restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
        embedding_service = create_embedding_service()
        reranker = CrossEncoderReranker()
        hybrid_searcher = HybridSearcher(db=db, restricted_db=restricted_db)
        hybrid_searcher.ensure_fts_index()

        app.state.db = db
        app.state.embedding_service = embedding_service
        app.state.reranker = reranker
        app.state.hybrid_searcher = hybrid_searcher
        logger.info(
            "Shared services initialized: EmbeddingService (%s), HybridSearcher, Reranker",
            embedding_service.model_name,
        )
    except Exception as e:
        logger.warning("Shared services not initialized (non-fatal): %s", e)
        # API routes will fall back to per-request initialization

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

# ── Per-Agent Permission Middleware ───────────────────────────────────────────
# Agents authenticate via API key; permissions are resolved from settings.yaml.
# If no external agents are configured, the API runs in "open mode" for
# localhost development.

_settings_mgr: SettingsManager | None = None


def _get_settings_mgr() -> SettingsManager:
    """Lazy-init SettingsManager singleton."""
    global _settings_mgr
    if _settings_mgr is None:
        _settings_mgr = SettingsManager()
    return _settings_mgr


async def check_permissions(request: Request) -> dict[str, bool]:
    """Resolve agent permissions from API key. Returns permissions dict.

    If no external agents are configured, runs in "open mode" with full
    permissions (localhost trust). Otherwise requires a valid X-API-Key header
    that maps to a registered agent.
    """
    api_key = request.headers.get("X-API-Key", "")
    mgr = _get_settings_mgr()

    if not api_key:
        # No key — check if open mode (no external agents configured)
        agents = mgr.get_agents()
        external_agents = [n for n in agents if not n.startswith("_")]
        if not external_agents:
            # Open mode: localhost trust, full permissions
            request.state.agent_name = "_open"
            perms: dict[str, bool] = {p: True for p in DEFAULT_PERMISSIONS}
            request.state.permissions = perms
            return perms
        raise HTTPException(status_code=401, detail="API key required")

    agent = mgr.get_agent_by_key(api_key)
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")

    request.state.agent_name = agent["name"]
    perms = dict(agent.get("permissions", DEFAULT_PERMISSIONS))
    request.state.permissions = perms
    return perms


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
app.include_router(create_v1_router(check_permissions))

app.include_router(create_settings_router())

# ── Port Discovery ────────────────────────────────────────────────────────────


def _port_is_available(host: str, port: int) -> bool:
    """Check if a port is available by attempting to bind to it."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(
    host: str = config.SERVER_HOST,
    preferred: int = config.SERVER_PORT,
    max_attempts: int = config.SERVER_PORT_MAX_ATTEMPTS,
) -> int:
    """Find an available port starting from the preferred port.

    Tries preferred, preferred+1, ..., up to max_attempts.
    Raises RuntimeError if no port is available.
    """
    for offset in range(max_attempts):
        port = preferred + offset
        if _port_is_available(host, port):
            if offset > 0:
                logger.warning("Port %d in use, falling back to port %d", preferred, port)
            return port
        logger.debug("Port %d is in use, trying next", port)

    raise RuntimeError(
        f"No available port found in range {preferred}-{preferred + max_attempts - 1}"
    )


def _write_port_file(port: int) -> None:
    """Write the active server port to the port file for service discovery."""
    port_file = config.SERVER_PORT_FILE
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(port))


def _remove_port_file() -> None:
    """Remove the port file on shutdown."""
    try:
        config.SERVER_PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass  # Best-effort cleanup


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = find_available_port()
    _write_port_file(port)
    atexit.register(_remove_port_file)
    uvicorn.run(app, host=config.SERVER_HOST, port=port)
