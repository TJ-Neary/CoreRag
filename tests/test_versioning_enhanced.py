"""Tests for VersionManager — version tracking, diffs, and is_changed."""

import pytest

from src.utils.versioning import VersionManager


@pytest.fixture
def vm(tmp_path):
    return VersionManager(state_dir=tmp_path / "versions")


class TestCreateVersion:
    def test_creates_first_version(self, vm):
        v = vm.create_version("doc1", "Hello world", change_type="create")
        assert v.version_number == 1
        assert v.document_id == "doc1"

    def test_increments_version_number(self, vm):
        vm.create_version("doc1", "Version 1")
        v2 = vm.create_version("doc1", "Version 2")
        assert v2.version_number == 2

    def test_skips_duplicate_content(self, vm):
        v1 = vm.create_version("doc1", "Same content")
        v2 = vm.create_version("doc1", "Same content")
        assert v1.version_id == v2.version_id  # Returns existing version

    def test_auto_generates_summary(self, vm):
        vm.create_version("doc1", "Line 1\nLine 2")
        v2 = vm.create_version("doc1", "Line 1\nLine 2\nLine 3")
        assert "Added 1 lines" in v2.change_summary


class TestIsChanged:
    def test_new_document_is_changed(self, vm):
        assert vm.is_changed("new_doc", "any content") is True

    def test_same_content_not_changed(self, vm):
        vm.create_version("doc1", "Hello")
        assert vm.is_changed("doc1", "Hello") is False

    def test_different_content_is_changed(self, vm):
        vm.create_version("doc1", "Hello")
        assert vm.is_changed("doc1", "Goodbye") is True


class TestGetDiff:
    def test_diff_between_versions(self, vm):
        vm.create_version("doc1", "Line A\nLine B")
        vm.create_version("doc1", "Line A\nLine C\nLine D")
        diff = vm.get_diff("doc1", 1, 2)
        assert diff is not None
        assert diff.additions > 0
        assert diff.from_version == 1
        assert diff.to_version == 2

    def test_diff_missing_version_returns_none(self, vm):
        vm.create_version("doc1", "content")
        assert vm.get_diff("doc1", 1, 99) is None


class TestRestoreVersion:
    def test_restore_creates_new_version(self, vm):
        vm.create_version("doc1", "Original")
        vm.create_version("doc1", "Changed")
        restored = vm.restore_version("doc1", 1)
        assert restored is not None
        assert restored.version_number == 3
        assert restored.change_type == "restore"

    def test_restore_missing_version(self, vm):
        assert vm.restore_version("doc1", 99) is None


class TestGetHistory:
    def test_returns_formatted_history(self, vm):
        vm.create_version("doc1", "V1", changed_by="user", change_type="create")
        vm.create_version("doc1", "V2", changed_by="system", change_type="update")
        history = vm.get_history("doc1")
        assert len(history) == 2
        assert history[0]["version"] == 2  # Most recent first
        assert history[1]["version"] == 1

    def test_empty_history_for_unknown(self, vm):
        assert vm.get_history("nonexistent") == []

    def test_limit_parameter(self, vm):
        for i in range(5):
            vm.create_version("doc1", f"Content {i}")
        history = vm.get_history("doc1", limit=3)
        assert len(history) == 3


class TestPersistence:
    def test_versions_survive_reload(self, tmp_path):
        state_dir = tmp_path / "versions"
        vm1 = VersionManager(state_dir=state_dir)
        vm1.create_version("doc1", "Persistent content")

        vm2 = VersionManager(state_dir=state_dir)
        assert len(vm2.get_versions("doc1")) == 1
        content = vm2.get_content("doc1", 1)
        assert content == "Persistent content"
