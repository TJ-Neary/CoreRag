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
            print(f"Error: Missing required environment variable '{var_name}' in .env file.")
            sys.exit(1)
        return None

    path = Path(value).expanduser().resolve()
    return path


# ── Required Paths ────────────────────────────────────────────────────────────

INBOX_PATH = get_path_var("INBOX_PATH")
VAULT_PATH = get_path_var("VAULT_PATH")
ARCHIVE_PATH = get_path_var("ARCHIVE_PATH")

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
EMBEDDING_MODEL = os.getenv("CORERAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RERANKER_MODEL = os.getenv("CORERAG_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# ── API Keys ──────────────────────────────────────────────────────────────────

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


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
        print("Warning: GOOGLE_API_KEY is missing. Intelligence features will be limited.")
