"""Tests for per-agent permission enforcement.

Validates that check_permissions resolves agent permissions from API keys,
and that each v1 endpoint enforces the correct permission flag.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.settings.settings_manager import DEFAULT_PERMISSIONS, SettingsManager

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_settings_mgr(tmp_path: Path, agents: dict | None = None) -> SettingsManager:
    """Create a SettingsManager with test agents at a temp path."""
    mgr = SettingsManager(settings_path=tmp_path / "settings.yaml")
    # Pre-populate with provided agents (bypass create_agent to avoid .env writes)
    mgr.load()
    if agents:
        mgr._data["agents"] = agents
        mgr.save()
        mgr._build_key_cache()
    return mgr


def _full_perms() -> dict[str, bool]:
    """Return a permissions dict with everything enabled."""
    return {p: True for p in DEFAULT_PERMISSIONS}


def _search_only_perms() -> dict[str, bool]:
    """Return permissions with only search_main enabled."""
    perms = {p: False for p in DEFAULT_PERMISSIONS}
    perms["search_main"] = True
    return perms


def _no_perms() -> dict[str, bool]:
    """Return permissions with everything disabled."""
    return {p: False for p in DEFAULT_PERMISSIONS}


# ── Fixtures ─────────────────────────────────────────────────────────────────

AGENT_KEY = "test-agent-key-abc123"
AGENT_KEY_ENV = "CORERAG_AGENT_TESTAGENT_KEY"


@pytest.fixture()
def _inject_agent_key():
    """Inject the test agent key into the environment so key cache resolves it."""
    old = os.environ.get(AGENT_KEY_ENV)
    os.environ[AGENT_KEY_ENV] = AGENT_KEY
    yield
    if old is None:
        os.environ.pop(AGENT_KEY_ENV, None)
    else:
        os.environ[AGENT_KEY_ENV] = old


@pytest.fixture()
def client_with_agent(tmp_path: Path, _inject_agent_key: None):
    """TestClient where a single external agent 'testagent' exists with full perms."""
    mgr = _make_settings_mgr(
        tmp_path,
        agents={
            "_dashboard": {"permissions": _full_perms()},
            "testagent": {
                "api_key_env": AGENT_KEY_ENV,
                "permissions": _full_perms(),
            },
        },
    )
    with patch("src.server._settings_mgr", mgr), patch("src.server._get_settings_mgr", lambda: mgr):
        from src.server import app

        yield TestClient(app)


@pytest.fixture()
def client_open_mode(tmp_path: Path):
    """TestClient with no external agents — open mode."""
    mgr = _make_settings_mgr(
        tmp_path,
        agents={
            "_dashboard": {"permissions": _full_perms()},
            "_mcp": {"permissions": _full_perms()},
        },
    )
    with patch("src.server._settings_mgr", mgr), patch("src.server._get_settings_mgr", lambda: mgr):
        from src.server import app

        yield TestClient(app)


@pytest.fixture()
def client_restricted_agent(tmp_path: Path, _inject_agent_key: None):
    """TestClient with agent that has only search_main (no search_restricted, no ingest, etc)."""
    mgr = _make_settings_mgr(
        tmp_path,
        agents={
            "_dashboard": {"permissions": _full_perms()},
            "testagent": {
                "api_key_env": AGENT_KEY_ENV,
                "permissions": _search_only_perms(),
            },
        },
    )
    with patch("src.server._settings_mgr", mgr), patch("src.server._get_settings_mgr", lambda: mgr):
        from src.server import app

        yield TestClient(app)


@pytest.fixture()
def client_no_perms_agent(tmp_path: Path, _inject_agent_key: None):
    """TestClient with agent that has zero permissions."""
    mgr = _make_settings_mgr(
        tmp_path,
        agents={
            "_dashboard": {"permissions": _full_perms()},
            "testagent": {
                "api_key_env": AGENT_KEY_ENV,
                "permissions": _no_perms(),
            },
        },
    )
    with patch("src.server._settings_mgr", mgr), patch("src.server._get_settings_mgr", lambda: mgr):
        from src.server import app

        yield TestClient(app)


# ── check_permissions resolution tests ───────────────────────────────────────


class TestCheckPermissions:
    """Test the check_permissions dependency resolver."""

    def test_valid_key_resolves_permissions(self, client_with_agent: TestClient):
        """Agent key should resolve to the agent's permissions on request.state."""
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client_with_agent.get(
                "/api/v1/stats",
                headers={"X-API-Key": AGENT_KEY},
            )
        assert response.status_code == 200

    def test_unknown_key_rejected(self, client_with_agent: TestClient):
        """A random/unknown key should be rejected with 401."""
        response = client_with_agent.get(
            "/api/v1/stats",
            headers={"X-API-Key": "completely-unknown-key-xyz"},
        )
        assert response.status_code == 401

    def test_no_key_open_mode(self, client_open_mode: TestClient):
        """No key + no external agents = open mode with full access."""
        with patch("lancedb.connect") as mock_connect:
            mock_db = MagicMock()
            mock_db.table_names.return_value = []
            mock_connect.return_value = mock_db
            response = client_open_mode.get("/api/v1/stats")
        assert response.status_code == 200

    def test_no_key_with_agents_rejected(self, client_with_agent: TestClient):
        """No key + external agents exist = 401."""
        response = client_with_agent.get("/api/v1/stats")
        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]


# ── Per-endpoint permission enforcement ──────────────────────────────────────


class TestSearchPermission:
    """Test search_main and search_restricted enforcement on /search."""

    def test_search_permission_enforced(self, client_no_perms_agent: TestClient):
        """Agent without search_main should get 403 on search."""
        response = client_no_perms_agent.post(
            "/api/v1/search",
            json={"query": "test"},
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "search_main" in response.json()["error"]

    def test_restricted_scope_denied(self, client_restricted_agent: TestClient):
        """Agent with search_main but not search_restricted gets 403 for scope=all."""
        response = client_restricted_agent.post(
            "/api/v1/search",
            json={"query": "test", "search_scope": "all"},
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "search_restricted" in response.json()["error"]

    def test_restricted_scope_allowed(self, client_with_agent: TestClient):
        """Agent with search_restricted should succeed for scope=all."""
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["child_chunks"]

        mock_search = MagicMock()
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []
        mock_child_table = MagicMock()
        mock_child_table.search.return_value = mock_search
        mock_db.open_table.return_value = mock_child_table

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 1024

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "src.embeddings.embedding_service.create_embedding_service",
                return_value=mock_embedder,
            ),
        ):
            response = client_with_agent.post(
                "/api/v1/search",
                json={"query": "test", "search_scope": "all"},
                headers={"X-API-Key": AGENT_KEY},
            )
        assert response.status_code == 200


class TestIngestPermission:
    """Test ingest permission enforcement."""

    def test_ingest_permission_enforced(self, client_restricted_agent: TestClient):
        """Agent without ingest permission should get 403."""
        response = client_restricted_agent.post(
            "/api/v1/ingest",
            json={
                "content": "Some content to ingest that is long enough. " * 50,
                "source": "test",
            },
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "ingest" in response.json()["error"]

    def test_quick_capture_permission_enforced(self, client_restricted_agent: TestClient):
        """Agent without ingest permission should get 403 on quick-capture."""
        response = client_restricted_agent.post(
            "/api/v1/quick-capture",
            json={"text": "Quick note"},
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "ingest" in response.json()["error"]


class TestDeletePermission:
    """Test delete permission enforcement."""

    def test_delete_permission_enforced(self, client_restricted_agent: TestClient):
        """Agent without delete permission should get 403."""
        response = client_restricted_agent.delete(
            "/api/v1/documents/abc123",
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "delete" in response.json()["error"]

    def test_bulk_delete_permission_enforced(self, client_restricted_agent: TestClient):
        """Agent without delete permission should get 403 on bulk-delete."""
        response = client_restricted_agent.post(
            "/api/v1/documents/bulk-delete",
            json={"document_ids": ["doc1"]},
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "delete" in response.json()["error"]


class TestCatalogPermission:
    """Test catalog_read permission enforcement."""

    def test_get_document_permission_enforced(self, client_restricted_agent: TestClient):
        """Agent without catalog_read should get 403 on document retrieval."""
        response = client_restricted_agent.get(
            "/api/v1/documents/abc123",
            headers={"X-API-Key": AGENT_KEY},
        )
        assert response.status_code == 403
        assert "catalog_read" in response.json()["error"]
