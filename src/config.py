import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.exceptions import ConfigurationError

# Load environment variables
load_dotenv()


def get_path_var(var_name: str, required: bool = True) -> Path:
    """Retrieves a path from environment variables, resolving it to an absolute path."""
    value = os.getenv(var_name)
    if not value:
        # Defaults if not set (fallback)
        if var_name == "INBOX_PATH":
            return Path.home() / "Desktop" / "Inbox"
        if var_name == "VAULT_PATH":
            return Path.home() / "Documents" / "ObsidianVault"
        if var_name == "ARCHIVE_PATH":
            return Path.home() / "Documents"

        if required:
            print(
                f"Error: Missing required environment variable '{var_name}' in .env file.",
                file=sys.stderr,
            )
            sys.exit(1)
        return None  # type: ignore[return-value]

    path = Path(value).expanduser().resolve()
    return path


# ── Required Paths ────────────────────────────────────────────────────────────

INBOX_PATH = get_path_var("INBOX_PATH")
VAULT_PATH = get_path_var("VAULT_PATH")
ARCHIVE_PATH = get_path_var("ARCHIVE_PATH")

# ── Multi-Vault Support ──────────────────────────────────────────────────────
# Format: "Work=/path/one,Personal=/path/two"
_vault_paths_raw = os.getenv("CORERAG_VAULT_PATHS", "")
VAULT_PATHS: dict[str, Path] = {"default": VAULT_PATH}
if _vault_paths_raw:
    for entry in _vault_paths_raw.split(","):
        entry = entry.strip()
        if "=" in entry:
            name, path_str = entry.split("=", 1)
            VAULT_PATHS[name.strip()] = Path(path_str.strip()).expanduser().resolve()

# ── CoreRag Data Paths ────────────────────────────────────────────────────────

STATE_DIR = Path(os.getenv("CORERAG_STATE_DIR", str(Path.home() / ".corerag")))
DB_PATH = Path(os.getenv("CORERAG_DB_PATH", str(STATE_DIR / "lancedb")))
QUEUE_DIR = STATE_DIR / "queue"
CHECKPOINT_DIR = STATE_DIR / "checkpoints"
HEALTH_DIR = STATE_DIR / "health"
FEEDBACK_DIR = STATE_DIR / "feedback"
EXPORT_DIR = STATE_DIR / "exports"
LOG_DIR = STATE_DIR / "logs"

# ── LLM / Model Configuration ────────────────────────────────────────────────

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
EMBEDDING_MODEL = os.getenv("CORERAG_EMBEDDING_MODEL", "BAAI/bge-m3")

# Model → dimension mapping for supported embedding models
EMBEDDING_DIMENSIONS_MAP: dict[str, int] = {
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "multi-qa-mpnet-base-dot-v1": 768,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "BAAI/bge-m3": 1024,
}

EMBEDDING_DIMENSIONS = EMBEDDING_DIMENSIONS_MAP.get(EMBEDDING_MODEL, 384)
EMBEDDING_BATCH_SIZE = 32  # Tuned for M4 Max 48GB
RERANKER_MODEL = os.getenv("CORERAG_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANKER_BATCH_SIZE = 32

# ── Processing Thresholds ────────────────────────────────────────────────────

PII_MIN_CONFIDENCE = 0.70  # Minimum confidence for PII detection match
PII_SAMPLE_MAX_CHARS = 20000  # Max chars to scan for PII (performance)
PII_CONTEXT_TRUNCATE = 80  # Truncate PII context snippets for display
SEMANTIC_CACHE_THRESHOLD = 0.92  # Similarity threshold for search cache hits

# ── Retrieval Enhancement ───────────────────────────────────────────────────

CONTEXT_GENERATION = os.getenv("CORERAG_CONTEXT_GENERATION", "true").lower() == "true"
CHUNK_QUALITY_THRESHOLD = float(os.getenv("CORERAG_CHUNK_QUALITY_THRESHOLD", "0.3"))
SOURCE_AUTHORITY_DEFAULT = os.getenv("CORERAG_SOURCE_AUTHORITY_DEFAULT", "unknown")
CORRECTIVE_RAG_ENABLED = os.getenv("CORERAG_CORRECTIVE_RAG", "true").lower() == "true"

# ── Memory Safety ────────────────────────────────────────────────────────────

BATCH_MEMORY_PAUSE_PCT = 92  # Pause batch/commit at this RAM %
BATCH_MEMORY_RESUME_PCT = 88  # Resume when RAM drops below this %
SAFE_MEMORY_PAUSE_PCT = 75  # SafeProcessor pause threshold (background indexing)
SAFE_MEMORY_RESUME_PCT = 65  # SafeProcessor resume threshold
MEMORY_CHECK_INTERVAL_SEC = 2  # Seconds between memory checks when paused
COMMIT_BATCH_SIZE = 5  # Files between memory checks during commit

# ── Backup Configuration ─────────────────────────────────────────────────────

BACKUP_ENABLED = os.getenv("CORERAG_BACKUP_ENABLED", "true").lower() == "true"
BACKUP_STARTUP_COOLDOWN_HOURS = float(os.getenv("CORERAG_BACKUP_STARTUP_COOLDOWN", "24"))
BACKUP_COMMIT_COOLDOWN_HOURS = float(os.getenv("CORERAG_BACKUP_COMMIT_COOLDOWN", "1"))
BACKUP_MAX_COUNT = int(os.getenv("CORERAG_BACKUP_MAX_COUNT", "10"))
BACKUP_INTEGRITY_CHECK = os.getenv("CORERAG_BACKUP_INTEGRITY_CHECK", "true").lower() == "true"

# ── Server Configuration ─────────────────────────────────────────────────────

SERVER_HOST = os.getenv("CORERAG_SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("CORERAG_SERVER_PORT", "8000"))
SERVER_PORT_MAX_ATTEMPTS = 10
SERVER_PORT_FILE = STATE_DIR / "server.port"


def get_server_url() -> str:
    """Get the URL of the running CoreRag server.

    Reads the port from the port file if it exists, otherwise uses the
    configured default port.
    """
    port = SERVER_PORT
    if SERVER_PORT_FILE.exists():
        try:
            port = int(SERVER_PORT_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return f"http://{SERVER_HOST}:{port}"


# ── LLM Provider Configuration ─────────────────────────────────────────────

LLM_PROVIDER = os.getenv("CORERAG_LLM_PROVIDER", "")  # auto-detect if empty
LLM_MODEL = os.getenv("CORERAG_LLM_MODEL", "")  # provider default if empty
ANSWER_MAX_EVIDENCE_CHUNKS = int(os.getenv("CORERAG_ANSWER_MAX_EVIDENCE", "10"))

# ── API Keys ──────────────────────────────────────────────────────────────────

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


def validate_config():
    """Validates that critical paths actually exist or can be created."""
    from src.utils.secure_file import secure_state_directory

    if not INBOX_PATH.exists():
        try:
            INBOX_PATH.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ConfigurationError(
                f"Inbox path does not exist and cannot be created: {INBOX_PATH}",
                config_key="INBOX_PATH",
            ) from e

    if not VAULT_PATH.exists():
        try:
            VAULT_PATH.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ConfigurationError(
                f"Vault path does not exist and cannot be created: {VAULT_PATH}",
                config_key="VAULT_PATH",
            ) from e

    if not ARCHIVE_PATH.exists():
        try:
            ARCHIVE_PATH.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ConfigurationError(
                f"Could not create Archive path: {ARCHIVE_PATH}",
                config_key="ARCHIVE_PATH",
            ) from e

    # Ensure state directory exists with secure permissions (contains PII terms, etc.)
    try:
        secure_state_directory(STATE_DIR)
    except Exception as e:
        raise ConfigurationError(
            f"Could not secure state directory: {STATE_DIR}",
            config_key="CORERAG_STATE_DIR",
        ) from e

    if not GOOGLE_API_KEY:
        print(
            "Warning: GOOGLE_API_KEY is missing. Intelligence features will be limited.",
            file=sys.stderr,
        )
