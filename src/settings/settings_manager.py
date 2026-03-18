"""Settings manager for CoreRag — agent CRUD, permissions, YAML persistence."""

import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import set_key as dotenv_set_key

from src.config import SETTINGS_PATH

logger = logging.getLogger(__name__)

DEFAULT_PERMISSIONS: dict[str, bool] = {
    "search_main": False,
    "search_restricted": False,
    "ingest": False,
    "delete": False,
    "server_admin": False,
    "catalog_read": False,
    "catalog_write": False,
}

FACTORY_DEFAULTS: dict[str, Any] = {
    "agents": {
        "_dashboard": {
            "permissions": {
                "search_main": True,
                "search_restricted": False,
                "ingest": False,
                "delete": False,
                "server_admin": True,
                "catalog_read": True,
                "catalog_write": True,
            },
            "chat_provider": "",
        },
        "_mcp": {
            "permissions": {
                "search_main": True,
                "search_restricted": False,
                "ingest": True,
                "delete": False,
                "server_admin": True,
                "catalog_read": True,
                "catalog_write": False,
            },
        },
    },
    "llm": {"provider": "", "model": "", "ollama_model": "qwen3:32b"},
    "default_permissions": dict(DEFAULT_PERMISSIONS),
}

AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _find_dotenv_path() -> Path:
    """Locate the project .env file.

    Walks up from the package directory to find .env, falling back to CWD.
    """
    # Try common locations relative to this package
    candidates = [
        Path(__file__).resolve().parent.parent.parent / ".env",  # project root
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Default: project root (will be created by dotenv_set_key if needed)
    return candidates[0]


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy a dict tree of primitives (avoids import copy)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


class SettingsManager:
    """Central configuration manager for CoreRag agent access control.

    Manages per-agent API keys and permission toggles with YAML persistence.
    API key *values* are stored in environment / ``.env`` file — the settings
    YAML only records the env-var name (``api_key_env``).
    """

    def __init__(self, settings_path: Path | None = None) -> None:
        self._path: Path = settings_path or SETTINGS_PATH
        self._data: dict[str, Any] | None = None
        self._mtime: float = 0.0
        self._key_cache: dict[str, str] = {}  # api_key_value → agent_name
        self._last_stat_check: float = 0.0

    # ── Load / Save ──────────────────────────────────────────────────────

    def load(self) -> None:
        """Load settings from YAML, creating defaults if the file is missing."""
        if self._path.exists():
            mtime = self._path.stat().st_mtime
            raw = self._path.read_text(encoding="utf-8")
            self._data = yaml.safe_load(raw) or {}
            self._mtime = mtime
        else:
            self._data = _deep_copy_dict(FACTORY_DEFAULTS)
            self.save()

        # Ensure top-level keys exist (forward-compat when new sections are added)
        for key in ("agents", "llm", "default_permissions"):
            if key not in self._data:
                self._data[key] = _deep_copy_dict(FACTORY_DEFAULTS.get(key, {}))

        # Legacy migration: honour existing CORERAG_API_KEY
        self._migrate_legacy_key()

        self._build_key_cache()

    def save(self) -> None:
        """Persist current settings to YAML with secure permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.safe_dump(self._data, default_flow_style=False, sort_keys=False)
        old_umask = os.umask(0o077)
        try:
            self._path.write_text(content, encoding="utf-8")
            os.chmod(self._path, 0o600)
        finally:
            os.umask(old_umask)
        self._mtime = self._path.stat().st_mtime

    # ── Agent CRUD ───────────────────────────────────────────────────────

    def get_agents(self) -> dict[str, Any]:
        """Return all agent configs."""
        self._ensure_loaded()
        return dict(self._data.get("agents", {}))

    def get_agent(self, name: str) -> dict[str, Any] | None:
        """Return a single agent config with ``name`` injected, or None."""
        self._ensure_loaded()
        agent = self._data.get("agents", {}).get(name)
        if agent is None:
            return None
        result = dict(agent)
        result["name"] = name
        return result

    def get_agent_by_key(self, api_key: str) -> dict[str, Any] | None:
        """Look up an agent by its resolved API key value.

        Returns the agent config dict (with ``name``) or None.
        """
        self._ensure_loaded()
        agent_name = self._key_cache.get(api_key)
        if agent_name is None:
            return None
        return self.get_agent(agent_name)

    def create_agent(self, name: str) -> str:
        """Create a new agent with default permissions.

        Returns:
            The generated API key string.

        Raises:
            ValueError: If the name is invalid or already exists.
        """
        self._ensure_loaded()

        if not AGENT_NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid agent name '{name}'. "
                "Use 1-64 alphanumeric characters, hyphens, or underscores."
            )

        agents = self._data.setdefault("agents", {})
        if name in agents:
            raise ValueError(f"Agent '{name}' already exists.")

        api_key = secrets.token_urlsafe(32)
        env_var = f"CORERAG_AGENT_{name.upper()}_KEY"

        # Write key to .env
        dotenv_path = _find_dotenv_path()
        dotenv_set_key(str(dotenv_path), env_var, api_key)
        # Also inject into current process so key cache picks it up
        os.environ[env_var] = api_key

        default_perms = dict(self._data.get("default_permissions", DEFAULT_PERMISSIONS))

        agents[name] = {
            "api_key_env": env_var,
            "permissions": default_perms,
        }
        self.save()
        self._build_key_cache()

        logger.info("Created agent '%s' (env: %s)", name, env_var)
        return api_key

    def update_agent(self, name: str, permissions: dict[str, bool]) -> None:
        """Update permission flags for an existing agent.

        Raises:
            KeyError: If the agent does not exist.
        """
        self._ensure_loaded()
        agents = self._data.get("agents", {})
        if name not in agents:
            raise KeyError(f"Agent '{name}' not found.")

        # Validate permission keys — reject unknown keys to prevent future exploits
        invalid_keys = set(permissions.keys()) - set(DEFAULT_PERMISSIONS.keys())
        if invalid_keys:
            raise ValueError(f"Unknown permission keys: {invalid_keys}")

        current_perms = agents[name].setdefault("permissions", {})
        current_perms.update(permissions)
        self.save()

    def delete_agent(self, name: str) -> None:
        """Remove an agent from settings and clean up its .env entry.

        Raises:
            KeyError: If the agent does not exist or is a protected special agent.
        """
        self._ensure_loaded()
        agents = self._data.get("agents", {})

        if name in ("_dashboard", "_mcp"):
            raise KeyError(f"Cannot delete special agent '{name}'.")

        if name not in agents:
            raise KeyError(f"Agent '{name}' not found.")

        agent = agents.pop(name)
        self.save()
        self._build_key_cache()

        # Remove env var from .env file
        env_var = agent.get("api_key_env", "")
        if env_var:
            self._remove_env_var(env_var)
            os.environ.pop(env_var, None)

        logger.info("Deleted agent '%s'", name)

    # ── LLM Config ───────────────────────────────────────────────────────

    def get_llm_config(self) -> dict[str, Any]:
        """Return the llm configuration section."""
        self._ensure_loaded()
        return dict(self._data.get("llm", {}))

    def update_llm_config(self, **kwargs: Any) -> None:
        """Update LLM settings.  ``api_key`` fields are written to ``.env``."""
        self._ensure_loaded()
        llm = self._data.setdefault("llm", {})
        for key, value in kwargs.items():
            if "api_key" in key.lower() and value:
                # Write secret to .env, not to YAML
                env_var = f"CORERAG_LLM_{key.upper()}"
                dotenv_path = _find_dotenv_path()
                dotenv_set_key(str(dotenv_path), env_var, str(value))
                os.environ[env_var] = str(value)
                llm[key] = f"env:{env_var}"
            else:
                llm[key] = value
        self.save()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _build_key_cache(self) -> None:
        """Build a mapping of resolved API key values to agent names."""
        cache: dict[str, str] = {}
        for agent_name, agent_cfg in self._data.get("agents", {}).items():
            if not isinstance(agent_cfg, dict):
                continue
            env_var = agent_cfg.get("api_key_env", "")
            if env_var:
                key_value = os.environ.get(env_var, "")
                if key_value:
                    cache[key_value] = agent_name
        self._key_cache = cache

    _RELOAD_INTERVAL = 5.0  # seconds

    def _ensure_loaded(self) -> None:
        """Reload settings if the file has been modified since last load."""
        if self._data is None:
            self.load()
            return
        now = time.monotonic()
        if now - self._last_stat_check < self._RELOAD_INTERVAL:
            return
        self._last_stat_check = now
        if self._path.exists():
            mtime = self._path.stat().st_mtime
            if mtime != self._mtime:
                self.load()

    def _migrate_legacy_key(self) -> None:
        """If CORERAG_API_KEY env var exists and no _legacy agent, create one."""
        legacy_key = os.environ.get("CORERAG_API_KEY", "")
        if not legacy_key:
            return

        agents = self._data.setdefault("agents", {})
        if "_legacy" in agents:
            return

        perms = {perm: True for perm in DEFAULT_PERMISSIONS}
        perms["search_restricted"] = False  # Must be explicitly enabled
        agents["_legacy"] = {
            "api_key_env": "CORERAG_API_KEY",
            "permissions": perms,
        }
        logger.warning(
            "Migrated legacy CORERAG_API_KEY to _legacy agent with search_restricted=False. "
            "Review permissions in the Settings tab."
        )
        self.save()

    @staticmethod
    def _remove_env_var(env_var: str) -> None:
        """Remove an env var line from the project .env file."""
        dotenv_path = _find_dotenv_path()
        if not dotenv_path.exists():
            return
        lines = dotenv_path.read_text(encoding="utf-8").splitlines(keepends=True)
        filtered = [line for line in lines if not line.lstrip().startswith(f"{env_var}=")]
        dotenv_path.write_text("".join(filtered), encoding="utf-8")
