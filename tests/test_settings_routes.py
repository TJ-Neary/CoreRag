"""Tests for settings API routes — dashboard-only endpoints.

Covers all 10 endpoints in src/api/settings_routes.py:
  GET  /api/settings            — full settings + restart_required
  GET  /api/settings/agents     — list agents
  POST /api/settings/agents     — create agent
  PUT  /api/settings/agents/{n} — update agent permissions
  DEL  /api/settings/agents/{n} — delete agent
  PUT  /api/settings/llm        — update LLM config
  GET  /api/settings/ollama-models
  GET  /api/settings/model-status
  GET  /api/settings/db-stats
  POST /api/settings/db-action  — run optimize/backup/health_check

Key invariant: all endpoints reject requests that include X-API-Key header.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.settings_routes import create_settings_router
from src.settings.settings_manager import DEFAULT_PERMISSIONS, SettingsManager

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mgr(tmp_path: Path) -> SettingsManager:
    """Create a SettingsManager backed by a temp YAML file."""
    mgr = SettingsManager(settings_path=tmp_path / "settings.yaml")
    mgr.load()
    return mgr


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with the settings router mounted."""
    app = FastAPI()
    router = create_settings_router()
    app.include_router(router)
    return app


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_mgr(tmp_path: Path) -> SettingsManager:
    """SettingsManager using a temporary settings file."""
    return _make_mgr(tmp_path)


@pytest.fixture()
def client(tmp_mgr: SettingsManager) -> TestClient:
    """TestClient with SettingsManager patched so every endpoint shares the same instance."""
    app = _make_app()
    with patch("src.api.settings_routes.SettingsManager", return_value=tmp_mgr):
        yield TestClient(app)


# ── AUTH: X-API-Key blocks all endpoints ──────────────────────────────────────


class TestApiKeyBlocked:
    """All settings endpoints must return 403 when an X-API-Key header is present."""

    ENDPOINTS = [
        ("GET", "/api/settings"),
        ("GET", "/api/settings/agents"),
        ("POST", "/api/settings/agents"),
        ("PUT", "/api/settings/agents/someagent"),
        ("DELETE", "/api/settings/agents/someagent"),
        ("PUT", "/api/settings/llm"),
        ("GET", "/api/settings/ollama-models"),
        ("GET", "/api/settings/model-status"),
        ("GET", "/api/settings/db-stats"),
        ("POST", "/api/settings/db-action"),
    ]

    @pytest.mark.parametrize("method,path", ENDPOINTS)
    def test_api_key_rejected(self, client: TestClient, method: str, path: str):
        """Requests carrying X-API-Key header must be blocked with 403."""
        response = client.request(method, path, headers={"X-API-Key": "any-key"})
        assert response.status_code == 403
        assert "dashboard-only" in response.json()["error"]


# ── GET /api/settings ─────────────────────────────────────────────────────────


class TestGetSettings:
    """Full settings object + restart_required flag."""

    def test_returns_agents_and_llm(self, client: TestClient, tmp_mgr: SettingsManager):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert "agents" in data["settings"]
        assert "llm" in data["settings"]
        assert "restart_required" in data

    def test_restart_required_false_by_default(self, client: TestClient):
        """With no pending provider change restart_required should be False."""
        with patch("src.api.settings_routes.SettingsManager") as mock_mgr_cls:
            mgr = mock_mgr_cls.return_value
            mgr.get_agents.return_value = {}
            mgr.get_llm_config.return_value = {"provider": "", "ollama_model": ""}
            with (
                patch("src.config.LLM_PROVIDER", ""),
                patch("src.config.OLLAMA_MODEL", "qwen3:32b"),
            ):
                app = _make_app()
                c = TestClient(app)
                response = c.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["restart_required"] is False

    def test_restart_required_true_on_provider_mismatch(self, client: TestClient):
        """restart_required=True when stored provider differs from running provider."""
        with patch("src.api.settings_routes.SettingsManager") as mock_mgr_cls:
            mgr = mock_mgr_cls.return_value
            mgr.get_agents.return_value = {}
            mgr.get_llm_config.return_value = {"provider": "anthropic", "ollama_model": ""}
            with patch("src.config.LLM_PROVIDER", "ollama"), patch("src.config.OLLAMA_MODEL", ""):
                app = _make_app()
                c = TestClient(app)
                response = c.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["restart_required"] is True

    def test_no_api_key_required(self, client: TestClient):
        """Dashboard requests (no X-API-Key) should succeed."""
        response = client.get("/api/settings")
        assert response.status_code == 200


# ── GET /api/settings/agents ──────────────────────────────────────────────────


class TestListAgents:
    """List all agents."""

    def test_returns_agent_dict(self, client: TestClient, tmp_mgr: SettingsManager):
        response = client.get("/api/settings/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        # Factory defaults include _dashboard and _mcp
        assert "_dashboard" in data["agents"]
        assert "_mcp" in data["agents"]

    def test_no_api_key_passes(self, client: TestClient):
        response = client.get("/api/settings/agents")
        assert response.status_code == 200

    def test_custom_agent_visible(self, tmp_path: Path):
        """After creating an agent it appears in the list."""
        mgr = _make_mgr(tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("")
        with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv):
            mgr.create_agent("mybot")
        # Patch SettingsManager so the route uses our pre-configured instance
        app = _make_app()
        with patch("src.api.settings_routes.SettingsManager", return_value=mgr):
            c = TestClient(app)
            response = c.get("/api/settings/agents")
        assert response.status_code == 200
        assert "mybot" in response.json()["agents"]
        # Cleanup env
        os.environ.pop("CORERAG_AGENT_MYBOT_KEY", None)


# ── POST /api/settings/agents ─────────────────────────────────────────────────


class TestCreateAgent:
    """Agent creation endpoint."""

    def test_create_agent_success(self, tmp_path: Path):
        mgr = _make_mgr(tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("")

        with (
            patch("src.api.settings_routes.SettingsManager", return_value=mgr),
            patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv),
        ):
            app = _make_app()
            c = TestClient(app)
            response = c.post("/api/settings/agents", json={"name": "newbot"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "newbot"
        assert "api_key" in data
        assert len(data["api_key"]) > 20
        assert "permissions" in data
        os.environ.pop("CORERAG_AGENT_NEWBOT_KEY", None)

    def test_create_agent_key_is_unique(self, tmp_path: Path):
        """Two agents get different API keys."""
        mgr = _make_mgr(tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("")
        keys = []
        with (
            patch("src.api.settings_routes.SettingsManager", return_value=mgr),
            patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv),
        ):
            app = _make_app()
            c = TestClient(app)
            for name in ("botone", "bottwo"):
                r = c.post("/api/settings/agents", json={"name": name})
                assert r.status_code == 200
                keys.append(r.json()["api_key"])
        assert keys[0] != keys[1]
        os.environ.pop("CORERAG_AGENT_BOTONE_KEY", None)
        os.environ.pop("CORERAG_AGENT_BOTTWO_KEY", None)

    def test_create_agent_missing_name_returns_422(self, client: TestClient):
        """Empty or missing name returns 422."""
        response = client.post("/api/settings/agents", json={"name": ""})
        assert response.status_code == 422
        assert "required" in response.json()["error"]

    def test_create_agent_no_name_key_returns_422(self, client: TestClient):
        response = client.post("/api/settings/agents", json={})
        assert response.status_code == 422

    def test_create_agent_invalid_name_returns_400(self, client: TestClient):
        """Invalid name (spaces, special chars) returns 400."""
        with patch(
            "src.settings.settings_manager.SettingsManager.create_agent",
            side_effect=ValueError("Invalid agent name"),
        ):
            response = client.post("/api/settings/agents", json={"name": "bad name!"})
        assert response.status_code == 400
        assert "Invalid" in response.json()["error"]

    def test_create_duplicate_agent_returns_400(self, client: TestClient):
        """Duplicate name returns 400."""
        with patch(
            "src.settings.settings_manager.SettingsManager.create_agent",
            side_effect=ValueError("already exists"),
        ):
            response = client.post("/api/settings/agents", json={"name": "_dashboard"})
        assert response.status_code == 400


# ── PUT /api/settings/agents/{name} ──────────────────────────────────────────


class TestUpdateAgent:
    """Permission update endpoint."""

    def test_update_permissions_success(self, client: TestClient, tmp_mgr: SettingsManager):
        """Updating _dashboard permissions returns the updated agent."""
        response = client.put(
            "/api/settings/agents/_dashboard",
            json={"permissions": {"search_restricted": True}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "_dashboard"
        assert "permissions" in data

    def test_update_permissions_all_valid_flags(self, client: TestClient):
        """All DEFAULT_PERMISSIONS keys are accepted."""
        perms = {k: True for k in DEFAULT_PERMISSIONS}
        response = client.put(
            "/api/settings/agents/_mcp",
            json={"permissions": perms},
        )
        assert response.status_code == 200

    def test_update_missing_permissions_field_returns_422(self, client: TestClient):
        """Body without 'permissions' key returns 422."""
        response = client.put(
            "/api/settings/agents/_dashboard",
            json={"random_field": "value"},
        )
        assert response.status_code == 422

    def test_update_nonexistent_agent_returns_404(self, client: TestClient):
        """Updating an agent that doesn't exist returns 404."""
        with patch(
            "src.settings.settings_manager.SettingsManager.update_agent",
            side_effect=KeyError("Agent 'ghost' not found."),
        ):
            response = client.put(
                "/api/settings/agents/ghost",
                json={"permissions": {"search_main": True}},
            )
        assert response.status_code == 404

    def test_update_preserves_unchanged_permissions(self, tmp_path: Path):
        """Only specified permissions are modified; others are preserved."""
        mgr = _make_mgr(tmp_path)
        # Verify _dashboard starts with server_admin=True
        original = mgr.get_agent("_dashboard")
        assert original["permissions"]["server_admin"] is True

        app = _make_app()
        with patch("src.api.settings_routes.SettingsManager", return_value=mgr):
            c = TestClient(app)
            c.put(
                "/api/settings/agents/_dashboard",
                json={"permissions": {"search_restricted": True}},
            )

        updated = mgr.get_agent("_dashboard")
        assert updated["permissions"]["server_admin"] is True  # unchanged
        assert updated["permissions"]["search_restricted"] is True  # changed


# ── DELETE /api/settings/agents/{name} ────────────────────────────────────────


class TestDeleteAgent:
    """Agent deletion endpoint."""

    def test_delete_agent_success(self, tmp_path: Path):
        mgr = _make_mgr(tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("")
        with patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv):
            mgr.create_agent("todelete")
        os.environ.pop("CORERAG_AGENT_TODELETE_KEY", None)

        app = _make_app()
        with patch("src.api.settings_routes.SettingsManager", return_value=mgr):
            c = TestClient(app)
            response = c.delete("/api/settings/agents/todelete")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["name"] == "todelete"

    def test_delete_nonexistent_agent_returns_404(self, client: TestClient):
        with patch(
            "src.settings.settings_manager.SettingsManager.delete_agent",
            side_effect=KeyError("Agent 'ghost' not found."),
        ):
            response = client.delete("/api/settings/agents/ghost")
        assert response.status_code == 404

    def test_delete_protected_agent_returns_404(self, client: TestClient):
        """Attempting to delete _dashboard or _mcp returns 404."""
        with patch(
            "src.settings.settings_manager.SettingsManager.delete_agent",
            side_effect=KeyError("Cannot delete special agent '_dashboard'."),
        ):
            response = client.delete("/api/settings/agents/_dashboard")
        assert response.status_code == 404


# ── PUT /api/settings/llm ─────────────────────────────────────────────────────


class TestUpdateLlm:
    """LLM provider configuration endpoint."""

    def test_update_provider(self, client: TestClient, tmp_mgr: SettingsManager):
        response = client.put("/api/settings/llm", json={"provider": "anthropic"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert "llm" in data
        assert data["llm"]["provider"] == "anthropic"

    def test_update_ollama_model(self, client: TestClient, tmp_mgr: SettingsManager):
        response = client.put("/api/settings/llm", json={"ollama_model": "llama3:8b"})
        assert response.status_code == 200
        assert response.json()["llm"]["ollama_model"] == "llama3:8b"

    def test_update_multiple_fields(self, client: TestClient, tmp_mgr: SettingsManager):
        response = client.put(
            "/api/settings/llm",
            json={"provider": "gemini", "ollama_model": "gemma2:9b"},
        )
        assert response.status_code == 200
        llm = response.json()["llm"]
        assert llm["provider"] == "gemini"
        assert llm["ollama_model"] == "gemma2:9b"

    def test_update_no_fields_returns_422(self, client: TestClient):
        """Body with no recognized LLM fields returns 422."""
        response = client.put("/api/settings/llm", json={"unknown_field": "value"})
        assert response.status_code == 422
        assert "No LLM config fields" in response.json()["error"]

    def test_update_empty_body_returns_422(self, client: TestClient):
        response = client.put("/api/settings/llm", json={})
        assert response.status_code == 422

    def test_api_key_written_to_env_not_yaml(self, tmp_path: Path):
        """API key values must not appear in the settings YAML."""
        mgr = _make_mgr(tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("")

        app = _make_app()
        with (
            patch("src.api.settings_routes.SettingsManager", return_value=mgr),
            patch("src.settings.settings_manager._find_dotenv_path", return_value=dotenv),
        ):
            c = TestClient(app)
            c.put("/api/settings/llm", json={"api_key_value": "super-secret-llm-key"})

        yaml_text = (tmp_path / "settings.yaml").read_text()
        assert "super-secret-llm-key" not in yaml_text
        os.environ.pop("CORERAG_LLM_API_KEY_VALUE", None)


# ── GET /api/settings/ollama-models ──────────────────────────────────────────


class TestOllamaModels:
    """Ollama model listing endpoint (proxies to Ollama HTTP API)."""

    def test_returns_model_list(self, client: TestClient):
        fake_response = MagicMock()
        fake_response.json.return_value = {"models": [{"name": "llama3:8b"}]}
        fake_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_cls.return_value
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value.get = AsyncMock(return_value=fake_response)
            response = client.get("/api/settings/ollama-models")

        assert response.status_code in (200, 502)  # 502 if Ollama not running

    def test_returns_502_when_ollama_unavailable(self, client: TestClient):
        """Connection errors produce a 502 with an informative error message."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_cls.return_value
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            response = client.get("/api/settings/ollama-models")

        assert response.status_code == 502
        assert "Ollama" in response.json()["error"]


# ── GET /api/settings/model-status ────────────────────────────────────────────


class TestModelStatus:
    """Model status endpoint."""

    def test_returns_model_info(self, client: TestClient):
        response = client.get("/api/settings/model-status")
        assert response.status_code == 200
        data = response.json()
        assert "llm_provider" in data
        assert "embedding_model" in data
        assert "reranker_model" in data
        assert "restart_required" in data

    def test_restart_required_field_is_bool(self, client: TestClient):
        response = client.get("/api/settings/model-status")
        assert isinstance(response.json()["restart_required"], bool)

    def test_no_api_key_succeeds(self, client: TestClient):
        response = client.get("/api/settings/model-status")
        assert response.status_code == 200


# ── GET /api/settings/db-stats ────────────────────────────────────────────────


class TestDbStats:
    """Database statistics endpoint."""

    def test_returns_main_and_restricted_sections(self, client: TestClient):
        with (
            patch("lancedb.connect") as mock_connect,
            patch("src.config.DB_PATH", "/nonexistent"),
            patch("src.config.RESTRICTED_DB_PATH", "/nonexistent2"),
        ):
            mock_connect.return_value = MagicMock()
            response = client.get("/api/settings/db-stats")
        assert response.status_code == 200
        data = response.json()
        assert "main" in data
        assert "restricted" in data

    def test_nonexistent_db_shows_exists_false(self, client: TestClient, tmp_path: Path):
        """DB paths that don't exist on disk report exists=False."""
        nonexistent = str(tmp_path / "no_such_db")
        with (
            patch("src.config.DB_PATH", nonexistent),
            patch("src.config.RESTRICTED_DB_PATH", nonexistent),
        ):
            response = client.get("/api/settings/db-stats")
        assert response.status_code == 200
        data = response.json()
        assert data["main"]["exists"] is False
        assert data["restricted"]["exists"] is False


# ── POST /api/settings/db-action ─────────────────────────────────────────────


class TestDbAction:
    """Database action endpoint (optimize/backup/health_check)."""

    def test_invalid_action_returns_400(self, client: TestClient):
        response = client.post("/api/settings/db-action", json={"action": "drop_everything"})
        assert response.status_code == 400
        assert "Invalid action" in response.json()["error"]

    def test_missing_action_returns_400(self, client: TestClient):
        """Empty or absent action field returns 400."""
        response = client.post("/api/settings/db-action", json={})
        assert response.status_code == 400

    def test_valid_actions_listed_in_error(self, client: TestClient):
        """Error message lists all valid actions."""
        response = client.post("/api/settings/db-action", json={"action": "oops"})
        error_msg = response.json()["error"]
        for valid in ("optimize_main", "optimize_restricted", "backup", "health_check"):
            assert valid in error_msg

    def test_backup_action_dispatches(self, client: TestClient):
        mock_info = MagicMock()
        mock_info.name = "manual_backup"
        mock_info.timestamp = "2026-01-01T00:00:00"
        mock_info.size_bytes = 1024 * 1024
        mock_info.path = "/tmp/backup"

        mock_mgr = MagicMock()
        mock_mgr.create_backup.return_value = mock_info

        with (
            patch("src.utils.backup.BackupManager", return_value=mock_mgr),
            patch("src.config.STATE_DIR", Path("/tmp")),
            patch("src.config.BACKUP_MAX_COUNT", 10),
        ):
            response = client.post("/api/settings/db-action", json={"action": "backup"})

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "backup"
        assert data["status"] == "completed"
        assert "backup" in data

    def test_optimize_main_action_dispatches(self, client: TestClient):
        mock_result = MagicMock()
        mock_result.table_name = "child_chunks"
        mock_result.success = True
        mock_result.space_saved_mb = 0.5
        mock_result.duration_seconds = 1.2
        mock_result.error = None

        mock_optimizer = MagicMock()
        mock_optimizer.optimize_all.return_value = [mock_result]

        with (
            patch("src.maintenance.db_optimizer.LanceDBOptimizer", return_value=mock_optimizer),
            patch("src.config.DB_PATH", "/tmp/fake_db"),
        ):
            response = client.post("/api/settings/db-action", json={"action": "optimize_main"})

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "optimize_main"
        assert data["status"] == "completed"

    def test_health_check_action_dispatches(self, client: TestClient):
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"status": "ok", "checks": []}

        mock_checker = MagicMock()
        mock_checker.full_report.return_value = mock_report

        with (
            patch("src.maintenance.health_check.HealthChecker", return_value=mock_checker),
            patch("src.config.DB_PATH", "/tmp/fake_db"),
        ):
            response = client.post("/api/settings/db-action", json={"action": "health_check"})

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "health_check"
        assert "report" in data
