"""Tests for SettingsManager — agent CRUD, permissions, key cache, YAML persistence."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import yaml

from src.settings.settings_manager import (
    DEFAULT_PERMISSIONS,
    FACTORY_DEFAULTS,
    SettingsManager,
)

# ── Load / Save ──────────────────────────────────────────────────────────────


def test_load_creates_defaults(tmp_path: Path) -> None:
    """No file on disk → creates settings.yaml with factory defaults."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    assert settings_file.exists()
    data = yaml.safe_load(settings_file.read_text())
    assert "_dashboard" in data["agents"]
    assert "_mcp" in data["agents"]
    assert data["agents"]["_dashboard"]["permissions"]["server_admin"] is True
    assert data["default_permissions"]["search_main"] is False


def test_load_reads_existing(tmp_path: Path) -> None:
    """Pre-existing file is loaded correctly."""
    settings_file = tmp_path / "settings.yaml"
    custom_data = {
        "agents": {
            "_dashboard": {
                "permissions": {"search_main": True, "search_restricted": True},
            },
        },
        "llm": {"provider": "ollama"},
        "default_permissions": dict(DEFAULT_PERMISSIONS),
    }
    settings_file.write_text(yaml.safe_dump(custom_data))

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    agent = mgr.get_agent("_dashboard")
    assert agent is not None
    assert agent["permissions"]["search_restricted"] is True
    assert mgr.get_llm_config()["provider"] == "ollama"


def test_mtime_cache(tmp_path: Path) -> None:
    """Second access with unchanged mtime reuses cached data (no reload)."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    # Capture the data object identity
    first_data_id = id(mgr._data)

    # Access again — _ensure_loaded should see same mtime and skip reload
    mgr._ensure_loaded()
    assert id(mgr._data) == first_data_id


def test_mtime_change_triggers_reload(tmp_path: Path) -> None:
    """Modifying the file on disk triggers a reload on next access."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    # Overwrite file externally with different content
    modified_data = yaml.safe_load(settings_file.read_text())
    modified_data["llm"]["provider"] = "anthropic"
    settings_file.write_text(yaml.safe_dump(modified_data))

    # Force mtime difference (some filesystems have 1s granularity)
    new_mtime = mgr._mtime + 1.0
    os.utime(settings_file, (new_mtime, new_mtime))

    # _ensure_loaded should detect the change
    mgr._ensure_loaded()
    assert mgr.get_llm_config()["provider"] == "anthropic"


# ── Agent CRUD ───────────────────────────────────────────────────────────────


def test_create_agent(tmp_path: Path) -> None:
    """create_agent generates a key, writes .env, and saves settings."""
    settings_file = tmp_path / "settings.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("")

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv_file):
        key = mgr.create_agent("kendra")

    assert isinstance(key, str)
    assert len(key) > 20  # token_urlsafe(32) produces ~43 chars

    # Agent exists in settings
    agent = mgr.get_agent("kendra")
    assert agent is not None
    assert agent["name"] == "kendra"
    assert agent["api_key_env"] == "CORERAG_AGENT_KENDRA_KEY"
    # Default permissions applied
    assert agent["permissions"]["search_main"] is False

    # Key was written to .env
    env_content = dotenv_file.read_text()
    assert "CORERAG_AGENT_KENDRA_KEY" in env_content

    # Key is in os.environ (cleanup after test)
    assert os.environ.get("CORERAG_AGENT_KENDRA_KEY") == key
    os.environ.pop("CORERAG_AGENT_KENDRA_KEY", None)


def test_create_agent_invalid_name(tmp_path: Path) -> None:
    """Names with spaces or special chars raise ValueError."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    import pytest

    with pytest.raises(ValueError, match="Invalid agent name"):
        mgr.create_agent("bad name!")

    with pytest.raises(ValueError, match="Invalid agent name"):
        mgr.create_agent("")

    with pytest.raises(ValueError, match="Invalid agent name"):
        mgr.create_agent("a" * 65)  # Too long


def test_create_agent_duplicate(tmp_path: Path) -> None:
    """Attempting to create an agent that already exists raises ValueError."""
    settings_file = tmp_path / "settings.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("")

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    import pytest

    with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv_file):
        mgr.create_agent("myagent")

    with pytest.raises(ValueError, match="already exists"):
        with patch(
            "src.settings.settings_manager._find_dotenv_path",
            return_value=dotenv_file,
        ):
            mgr.create_agent("myagent")

    # Cleanup
    os.environ.pop("CORERAG_AGENT_MYAGENT_KEY", None)


def test_get_agent_by_key(tmp_path: Path) -> None:
    """Resolves agent from an API key value via the key cache."""
    settings_file = tmp_path / "settings.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("")

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv_file):
        key = mgr.create_agent("lookup_test")

    result = mgr.get_agent_by_key(key)
    assert result is not None
    assert result["name"] == "lookup_test"

    # Cleanup
    os.environ.pop("CORERAG_AGENT_LOOKUP_TEST_KEY", None)


def test_get_agent_by_key_unknown(tmp_path: Path) -> None:
    """Unknown key returns None."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    assert mgr.get_agent_by_key("nonexistent-key-value") is None


def test_update_agent_permissions(tmp_path: Path) -> None:
    """Permission updates persist after save/reload."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    mgr.update_agent("_dashboard", {"search_restricted": True, "delete": True})

    # Re-read from disk
    mgr2 = SettingsManager(settings_path=settings_file)
    mgr2.load()
    agent = mgr2.get_agent("_dashboard")
    assert agent is not None
    assert agent["permissions"]["search_restricted"] is True
    assert agent["permissions"]["delete"] is True
    # Unchanged perms are preserved
    assert agent["permissions"]["server_admin"] is True


def test_update_agent_not_found(tmp_path: Path) -> None:
    """Updating a nonexistent agent raises KeyError."""
    import pytest

    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with pytest.raises(KeyError, match="not found"):
        mgr.update_agent("ghost", {"search_main": True})


def test_delete_agent(tmp_path: Path) -> None:
    """delete_agent removes from settings and cleans .env."""
    settings_file = tmp_path / "settings.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("")

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv_file):
        key = mgr.create_agent("disposable")
        mgr.delete_agent("disposable")

    assert mgr.get_agent("disposable") is None
    assert mgr.get_agent_by_key(key) is None

    # .env line removed
    env_content = dotenv_file.read_text()
    assert "CORERAG_AGENT_DISPOSABLE_KEY" not in env_content


def test_delete_special_agent_rejected(tmp_path: Path) -> None:
    """Cannot delete _dashboard or _mcp."""
    import pytest

    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with pytest.raises(KeyError, match="Cannot delete special agent"):
        mgr.delete_agent("_dashboard")

    with pytest.raises(KeyError, match="Cannot delete special agent"):
        mgr.delete_agent("_mcp")


# ── Legacy Migration ─────────────────────────────────────────────────────────


def test_legacy_migration(tmp_path: Path) -> None:
    """CORERAG_API_KEY in env → creates _legacy agent with all perms True."""
    settings_file = tmp_path / "settings.yaml"

    with patch.dict(os.environ, {"CORERAG_API_KEY": "legacy-secret-key-123"}):
        mgr = SettingsManager(settings_path=settings_file)
        mgr.load()

    agent = mgr.get_agent("_legacy")
    assert agent is not None
    assert agent["api_key_env"] == "CORERAG_API_KEY"
    # All permissions granted for legacy key
    for perm in DEFAULT_PERMISSIONS:
        assert agent["permissions"][perm] is True


def test_legacy_migration_skips_if_exists(tmp_path: Path) -> None:
    """If _legacy agent already exists, migration is a no-op."""
    settings_file = tmp_path / "settings.yaml"
    pre_data = {
        "agents": {
            "_dashboard": FACTORY_DEFAULTS["agents"]["_dashboard"],
            "_mcp": FACTORY_DEFAULTS["agents"]["_mcp"],
            "_legacy": {
                "api_key_env": "CORERAG_API_KEY",
                "permissions": {"search_main": True},
            },
        },
        "llm": dict(FACTORY_DEFAULTS["llm"]),
        "default_permissions": dict(DEFAULT_PERMISSIONS),
    }
    settings_file.write_text(yaml.safe_dump(pre_data))

    with patch.dict(os.environ, {"CORERAG_API_KEY": "legacy-secret-key-123"}):
        mgr = SettingsManager(settings_path=settings_file)
        mgr.load()

    # Original _legacy config preserved (only search_main, not all perms)
    agent = mgr.get_agent("_legacy")
    assert agent is not None
    assert "delete" not in agent["permissions"]


# ── LLM Config ───────────────────────────────────────────────────────────────


def test_get_llm_config(tmp_path: Path) -> None:
    """LLM config section is returned correctly."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    llm = mgr.get_llm_config()
    assert llm["ollama_model"] == "qwen3:32b"
    assert llm["provider"] == ""


def test_update_llm_config(tmp_path: Path) -> None:
    """Non-secret LLM fields are written to YAML."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    mgr.update_llm_config(provider="ollama", ollama_model="llama3:8b")

    mgr2 = SettingsManager(settings_path=settings_file)
    mgr2.load()
    assert mgr2.get_llm_config()["provider"] == "ollama"
    assert mgr2.get_llm_config()["ollama_model"] == "llama3:8b"


def test_update_llm_config_api_key(tmp_path: Path) -> None:
    """API key fields are written to .env, not stored as plaintext in YAML."""
    settings_file = tmp_path / "settings.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("")

    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv_file):
        mgr.update_llm_config(api_key="secret-test-key-456")

    # YAML stores the env var reference, not the plaintext key
    data = yaml.safe_load(settings_file.read_text())
    assert data["llm"]["api_key"] == "env:CORERAG_LLM_API_KEY"

    # Actual key written to .env
    env_content = dotenv_file.read_text()
    assert "secret-test-key-456" in env_content

    # Cleanup
    os.environ.pop("CORERAG_LLM_API_KEY", None)


# ── get_agents ───────────────────────────────────────────────────────────────


def test_get_agents(tmp_path: Path) -> None:
    """get_agents returns all agent configs."""
    settings_file = tmp_path / "settings.yaml"
    mgr = SettingsManager(settings_path=settings_file)
    mgr.load()

    agents = mgr.get_agents()
    assert "_dashboard" in agents
    assert "_mcp" in agents
    assert isinstance(agents["_dashboard"], dict)
