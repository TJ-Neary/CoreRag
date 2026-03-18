"""
Tests for path validation and traversal prevention.

Covers: canonicalize_path, is_path_within_directory, is_blocked_system_path,
has_sensitive_filename, validate_path, validate_relative_path, safe_join,
PathValidationError.

Run with: pytest tests/test_path_validation.py -v
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.path_validation import (
    PathValidationError,
    canonicalize_path,
    has_sensitive_filename,
    is_blocked_system_path,
    is_path_within_directory,
    safe_join,
    validate_path,
    validate_relative_path,
)

# ---------------------------------------------------------------------------
# canonicalize_path
# ---------------------------------------------------------------------------


class TestCanonicalizePath:
    """Tests for canonicalize_path()."""

    def test_returns_path_object(self) -> None:
        result = canonicalize_path("/tmp")
        assert isinstance(result, Path)

    def test_expands_home_directory(self) -> None:
        result = canonicalize_path("~")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_resolves_dotdot(self, tmp_path: Path) -> None:
        child = tmp_path / "subdir"
        child.mkdir()
        dotdot_path = str(child) + "/../"
        result = canonicalize_path(dotdot_path)
        # After resolution, no ".." should remain
        assert ".." not in str(result)
        assert result == tmp_path.resolve()

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        result = canonicalize_path(tmp_path)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# is_path_within_directory
# ---------------------------------------------------------------------------


class TestIsPathWithinDirectory:
    """Tests for is_path_within_directory()."""

    def test_exact_match_is_within(self, tmp_path: Path) -> None:
        assert is_path_within_directory(tmp_path, tmp_path) is True

    def test_child_is_within(self, tmp_path: Path) -> None:
        child = tmp_path / "child" / "file.txt"
        assert is_path_within_directory(child, tmp_path) is True

    def test_sibling_is_not_within(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        child_of_a = dir_a / "file.txt"
        assert is_path_within_directory(child_of_a, dir_b) is False

    def test_parent_is_not_within_child(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        assert is_path_within_directory(tmp_path, child) is False


# ---------------------------------------------------------------------------
# is_blocked_system_path
# ---------------------------------------------------------------------------


class TestIsBlockedSystemPath:
    """Tests for is_blocked_system_path()."""

    def test_etc_is_blocked(self) -> None:
        assert is_blocked_system_path(Path("/etc")) is True

    def test_etc_passwd_is_blocked(self) -> None:
        assert is_blocked_system_path(Path("/etc/passwd")) is True

    def test_usr_bin_is_blocked(self) -> None:
        assert is_blocked_system_path(Path("/usr/bin/python")) is True

    def test_var_log_is_blocked(self) -> None:
        assert is_blocked_system_path(Path("/var/log/system.log")) is True

    def test_tmp_is_not_blocked(self) -> None:
        assert is_blocked_system_path(Path("/tmp")) is False

    def test_home_subdir_is_not_blocked(self) -> None:
        home_subdir = Path.home() / "Documents" / "test_project"
        assert is_blocked_system_path(home_subdir) is False

    def test_private_is_blocked(self) -> None:
        # /private is macOS real path for /tmp on some systems
        assert is_blocked_system_path(Path("/private/etc/passwd")) is True


# ---------------------------------------------------------------------------
# has_sensitive_filename
# ---------------------------------------------------------------------------


class TestHasSensitiveFilename:
    """Tests for has_sensitive_filename()."""

    def test_dotenv_is_sensitive(self) -> None:
        assert has_sensitive_filename(Path("/home/user/.env")) is True

    def test_id_rsa_is_sensitive(self) -> None:
        assert has_sensitive_filename(Path("/home/user/.ssh/id_rsa")) is True

    def test_credentials_json_is_sensitive(self) -> None:
        assert has_sensitive_filename(Path("/some/dir/credentials.json")) is True

    def test_ssh_dir_component_is_sensitive(self) -> None:
        # .ssh appears as a path component, not just filename
        assert has_sensitive_filename(Path("/home/user/.ssh/known_hosts")) is True

    def test_normal_file_is_not_sensitive(self) -> None:
        assert has_sensitive_filename(Path("/home/user/documents/report.pdf")) is False

    def test_dotenv_local_is_sensitive(self) -> None:
        assert has_sensitive_filename(Path("/app/.env.local")) is True


# ---------------------------------------------------------------------------
# validate_path — using allow_outside_configured=True to isolate tests
# ---------------------------------------------------------------------------


def _patch_system_path_for_tmp(func):
    """Decorator: patch is_blocked_system_path so pytest tmp_path (/private/var/...) is allowed."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        original = is_blocked_system_path

        def _allow_tmp(p):
            resolved = str(Path(p).resolve())
            if "/pytest-" in resolved:
                return False
            return original(p)

        with patch("src.utils.path_validation.is_blocked_system_path", side_effect=_allow_tmp):
            return func(*args, **kwargs)

    return wrapper


class TestValidatePath:
    """Tests for validate_path()."""

    @_patch_system_path_for_tmp
    def test_valid_path_returns_canonical(self, tmp_path: Path) -> None:
        result = validate_path(tmp_path, allow_outside_configured=True)
        assert isinstance(result, Path)
        assert result == tmp_path.resolve()

    def test_system_path_raises(self) -> None:
        with pytest.raises(PathValidationError, match="system path"):
            validate_path("/etc/passwd", allow_outside_configured=True)

    def test_sensitive_filename_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathValidationError, match="sensitive"):
            validate_path(tmp_path / ".env", allow_outside_configured=True)

    @_patch_system_path_for_tmp
    def test_must_exist_raises_when_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(PathValidationError, match="does not exist"):
            validate_path(missing, allow_outside_configured=True, must_exist=True)

    @_patch_system_path_for_tmp
    def test_must_exist_passes_when_present(self, tmp_path: Path) -> None:
        real_file = tmp_path / "real.txt"
        real_file.write_text("hello")
        result = validate_path(real_file, allow_outside_configured=True, must_exist=True)
        assert result.exists()

    def test_outside_allowed_dirs_raises(self, tmp_path: Path) -> None:
        other_dir = tmp_path / "other"
        allowed = [tmp_path / "allowed"]
        with pytest.raises(PathValidationError):
            validate_path(other_dir, allowed_dirs=allowed)

    @_patch_system_path_for_tmp
    def test_within_allowed_dirs_passes(self, tmp_path: Path) -> None:
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        target = allowed_dir / "file.txt"
        result = validate_path(target, allowed_dirs=[allowed_dir])
        assert result == target.resolve()

    @_patch_system_path_for_tmp
    def test_path_with_spaces(self, tmp_path: Path) -> None:
        spacey = tmp_path / "my documents" / "report.pdf"
        result = validate_path(spacey, allow_outside_configured=True)
        assert "my documents" in str(result)

    def test_dotdot_traversal_blocked_by_system_path(self) -> None:
        # A path that resolves to /etc via traversal should be blocked
        with pytest.raises(PathValidationError, match="system path"):
            validate_path("/tmp/../etc/passwd", allow_outside_configured=True)

    def test_null_byte_in_path_does_not_cause_bypass(self, tmp_path: Path) -> None:
        # Python's Path strips/errors on null bytes before we ever check —
        # confirm it raises rather than silently allowing traversal.
        with pytest.raises((PathValidationError, ValueError)):
            validate_path("/etc/passwd\x00.txt", allow_outside_configured=True)

    def test_absolute_injection_blocked(self) -> None:
        with pytest.raises(PathValidationError):
            validate_path("/etc/passwd", allow_outside_configured=True)


# ---------------------------------------------------------------------------
# validate_relative_path
# ---------------------------------------------------------------------------


class TestValidateRelativePath:
    """Tests for validate_relative_path()."""

    @_patch_system_path_for_tmp
    def test_safe_relative_path_passes(self, tmp_path: Path) -> None:
        result = validate_relative_path("subdir/file.txt", tmp_path)
        assert str(result).startswith(str(tmp_path))

    def test_dotdot_traversal_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathValidationError):
            validate_relative_path("../../../etc/passwd", tmp_path)

    def test_double_dotdot_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathValidationError):
            validate_relative_path("sub/../../..", tmp_path)

    @_patch_system_path_for_tmp
    def test_path_stays_within_base(self, tmp_path: Path) -> None:
        result = validate_relative_path("a/b/c.txt", tmp_path)
        assert is_path_within_directory(result, tmp_path.resolve())


# ---------------------------------------------------------------------------
# safe_join
# ---------------------------------------------------------------------------


class TestSafeJoin:
    """Tests for safe_join()."""

    def test_normal_join_succeeds(self, tmp_path: Path) -> None:
        result = safe_join(tmp_path, "subdir", "file.txt")
        assert str(result).startswith(str(tmp_path))

    def test_traversal_via_dotdot_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PathValidationError):
            safe_join(tmp_path, "..", "etc", "passwd")

    def test_absolute_path_injection_stripped(self, tmp_path: Path) -> None:
        # Leading slash is stripped so "/etc/passwd" becomes "etc/passwd" under base
        result = safe_join(tmp_path, "/etc/passwd")
        assert str(result).startswith(str(tmp_path))
        assert result == tmp_path.resolve() / "etc" / "passwd"

    def test_windows_backslash_stripped(self, tmp_path: Path) -> None:
        # Leading backslash stripped on join
        result = safe_join(tmp_path, "\\subdir\\file.txt")
        assert str(result).startswith(str(tmp_path))

    def test_multiple_safe_parts(self, tmp_path: Path) -> None:
        result = safe_join(tmp_path, "a", "b", "c.txt")
        assert result == (tmp_path / "a" / "b" / "c.txt").resolve()


# ---------------------------------------------------------------------------
# PathValidationError
# ---------------------------------------------------------------------------


class TestPathValidationError:
    """Tests for the PathValidationError exception."""

    def test_exception_stores_path(self) -> None:
        err = PathValidationError("blocked", "/etc/passwd")
        assert err.path == "/etc/passwd"

    def test_exception_message_includes_path(self) -> None:
        err = PathValidationError("blocked", "/etc/passwd")
        assert "/etc/passwd" in str(err)
        assert "blocked" in str(err)

    def test_is_exception(self) -> None:
        with pytest.raises(PathValidationError):
            raise PathValidationError("test", "/bad/path")
