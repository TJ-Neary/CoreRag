"""Tests for integration plugin architecture."""

from src.integrations.base import IntegrationPlugin
from src.integrations.readwise import ReadwisePlugin


class TestIntegrationBase:
    def test_plugin_interface(self):
        """Verify IntegrationPlugin defines required abstract methods."""
        assert hasattr(IntegrationPlugin, "name")
        assert hasattr(IntegrationPlugin, "sync")
        assert hasattr(IntegrationPlugin, "check_connection")
        assert hasattr(IntegrationPlugin, "get_config_schema")


class TestReadwisePlugin:
    def test_name(self):
        plugin = ReadwisePlugin()
        assert plugin.name() == "readwise"

    def test_check_connection_no_token(self):
        plugin = ReadwisePlugin()
        plugin._api_token = ""
        assert plugin.check_connection() is False

    def test_config_schema(self):
        plugin = ReadwisePlugin()
        schema = plugin.get_config_schema()
        assert "READWISE_API_TOKEN" in schema["required"]

    def test_sync_no_token(self):
        plugin = ReadwisePlugin()
        plugin._api_token = ""
        result = plugin.sync()
        assert result["items_synced"] == 0
        assert len(result["errors"]) > 0

    def test_state_persistence(self, tmp_path):
        plugin = ReadwisePlugin(state_dir=tmp_path / "readwise")
        plugin._save_last_sync("2025-01-01T00:00:00")
        loaded = plugin._load_last_sync()
        assert loaded == "2025-01-01T00:00:00"
