"""Tests for multi-vault support."""

from unittest.mock import patch

from src.config import VAULT_PATHS


class TestVaultPaths:
    def test_default_vault_always_present(self):
        assert "default" in VAULT_PATHS

    def test_vault_paths_is_dict(self):
        assert isinstance(VAULT_PATHS, dict)


class TestExporterMultiVault:
    def test_export_to_default_vault(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        with patch("src.exporter.VAULT_PATHS", {"default": vault}):
            with patch("src.exporter.VAULT_PATH", vault):
                from src.exporter import export_to_vault

                export_to_vault("Test content", {"category": "Test", "year": "2025"}, "test.txt")
                exported = list((vault / "Ingested").glob("*.md"))
                assert len(exported) == 1

    def test_export_to_named_vault(self, tmp_path):
        work_vault = tmp_path / "work"
        work_vault.mkdir()
        default_vault = tmp_path / "default"
        default_vault.mkdir()
        vaults = {"default": default_vault, "work": work_vault}
        with patch("src.exporter.VAULT_PATHS", vaults):
            with patch("src.exporter.VAULT_PATH", default_vault):
                from src.exporter import export_to_vault

                export_to_vault(
                    "Work doc", {"category": "Work", "year": "2025"}, "work.txt", vault_name="work"
                )
                work_files = list((work_vault / "Ingested").glob("*.md"))
                default_files = list(default_vault.rglob("*.md"))
                assert len(work_files) == 1
                assert len(default_files) == 0

    def test_unknown_vault_falls_back_to_default(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        with patch("src.exporter.VAULT_PATHS", {"default": vault}):
            with patch("src.exporter.VAULT_PATH", vault):
                from src.exporter import export_to_vault

                export_to_vault(
                    "Content",
                    {"category": "Test", "year": "2025"},
                    "test.txt",
                    vault_name="unknown",
                )
                exported = list((vault / "Ingested").glob("*.md"))
                assert len(exported) == 1
