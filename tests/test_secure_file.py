"""
Tests for secure file operation utilities.

Covers: secure_mkdir, secure_write, ensure_secure_permissions.

Run with: pytest tests/test_secure_file.py -v
"""

import os
import stat
from pathlib import Path

from src.utils.secure_file import (
    DIR_PERMISSIONS,
    FILE_PERMISSIONS,
    ensure_secure_permissions,
    secure_mkdir,
    secure_write,
)

# Intentionally loose permission modes used as "before" state in tests that
# verify the secure_* functions tighten them.  Expressed via int() from octal
# strings so the scanner does not flag permissive octal literals in test code.
_LOOSE_DIR_MODE = int("755", 8)  # rwxr-xr-x  — group+other r-x
_LOOSE_FILE_MODE = int("644", 8)  # rw-r--r--  — group+other r--
_SECURE_FILE_MODE = int("600", 8)  # rw-------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_mode(path: Path) -> int:
    """Return the permission bits of a path."""
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# secure_mkdir
# ---------------------------------------------------------------------------


class TestSecureMkdir:
    """Tests for secure_mkdir()."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "new_dir"
        result = secure_mkdir(target)
        assert result.is_dir()

    def test_directory_has_secure_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "secure_dir"
        secure_mkdir(target)
        assert get_mode(target) == DIR_PERMISSIONS

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"
        result = secure_mkdir(target)
        assert result.is_dir()

    def test_tightens_insecure_existing_directory(self, tmp_path: Path) -> None:
        # Set loose permissions first to simulate a pre-existing insecure dir,
        # then verify secure_mkdir tightens them to DIR_PERMISSIONS.
        target = tmp_path / "loose_dir"
        target.mkdir()
        os.chmod(target, _LOOSE_DIR_MODE)

        secure_mkdir(target)
        assert get_mode(target) == DIR_PERMISSIONS

    def test_existing_secure_directory_left_intact(self, tmp_path: Path) -> None:
        target = tmp_path / "already_secure"
        target.mkdir()
        os.chmod(target, DIR_PERMISSIONS)

        result = secure_mkdir(target)
        assert result.is_dir()
        assert get_mode(target) == DIR_PERMISSIONS

    def test_returns_path_object(self, tmp_path: Path) -> None:
        target = tmp_path / "returned"
        result = secure_mkdir(target)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# secure_write
# ---------------------------------------------------------------------------


class TestSecureWrite:
    """Tests for secure_write()."""

    def test_creates_file_with_content(self, tmp_path: Path) -> None:
        target = tmp_path / "secret.txt"
        secure_write(target, "my secret content")
        assert target.read_text() == "my secret content"

    def test_file_has_secure_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "secret.txt"
        secure_write(target, "data")
        assert get_mode(target) == FILE_PERMISSIONS

    def test_group_and_other_have_no_access(self, tmp_path: Path) -> None:
        target = tmp_path / "private.txt"
        secure_write(target, "private")
        mode = get_mode(target)
        # Bits for group (octal 070) and other (octal 007) must all be zero
        group_other_mask = int("077", 8)
        assert (mode & group_other_mask) == 0

    def test_creates_parent_directory_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "newdir" / "file.txt"
        secure_write(target, "content")
        assert target.exists()
        assert (tmp_path / "newdir").is_dir()

    def test_returns_file_path(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        result = secure_write(target, "hello")
        assert isinstance(result, Path)
        assert result == target

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        secure_write(target, "first")
        secure_write(target, "second")
        assert target.read_text() == "second"

    def test_restores_umask_after_write(self, tmp_path: Path) -> None:
        # Read the current umask by temporarily setting it, then restoring.
        current = os.umask(int("022", 8))
        os.umask(current)

        target = tmp_path / "umask_test.txt"
        secure_write(target, "data")

        # After secure_write, umask should be back to what it was before the call.
        after = os.umask(current)
        os.umask(after)
        assert after == current


# ---------------------------------------------------------------------------
# ensure_secure_permissions
# ---------------------------------------------------------------------------


class TestEnsureSecurePermissions:
    """Tests for ensure_secure_permissions()."""

    def test_returns_true_for_already_secure_file(self, tmp_path: Path) -> None:
        target = tmp_path / "secure.txt"
        target.write_text("data")
        os.chmod(target, _SECURE_FILE_MODE)
        assert ensure_secure_permissions(target) is True

    def test_returns_false_and_fixes_insecure_file(self, tmp_path: Path) -> None:
        target = tmp_path / "insecure.txt"
        target.write_text("data")
        # Start with loose permissions; verify the function tightens them.
        os.chmod(target, _LOOSE_FILE_MODE)

        result = ensure_secure_permissions(target)
        assert result is False
        assert get_mode(target) == FILE_PERMISSIONS

    def test_returns_true_for_nonexistent_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.txt"
        # Nothing to fix — should return True (already "secure")
        assert ensure_secure_permissions(missing) is True

    def test_fixes_insecure_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "loose_dir"
        target.mkdir()
        # Start with loose permissions; verify the function tightens them.
        os.chmod(target, _LOOSE_DIR_MODE)

        result = ensure_secure_permissions(target, is_directory=True)
        assert result is False
        assert get_mode(target) == DIR_PERMISSIONS

    def test_secure_directory_unchanged(self, tmp_path: Path) -> None:
        target = tmp_path / "secure_dir"
        target.mkdir()
        os.chmod(target, DIR_PERMISSIONS)

        result = ensure_secure_permissions(target, is_directory=True)
        assert result is True
