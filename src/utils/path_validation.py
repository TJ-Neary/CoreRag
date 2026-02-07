"""
Path Validation and Traversal Prevention

Prevents path traversal attacks by:
1. Canonicalizing paths (resolving symlinks, .., etc.)
2. Validating paths are within allowed directories
3. Blocking access to sensitive system paths

Use `validate_path()` for any user-supplied or external path input.
"""

from pathlib import Path
from typing import List, Optional, Set

from src.config import ARCHIVE_PATH, INBOX_PATH, STATE_DIR, VAULT_PATH

# System paths that should never be accessed regardless of config
BLOCKED_PATHS: Set[str] = {
    "/etc",
    "/var",
    "/usr",
    "/bin",
    "/sbin",
    "/System",
    "/Library",
    "/private",
    "/root",
}

# Sensitive filenames that should not be read/written
SENSITIVE_FILENAMES: Set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    ".ssh",
    ".gnupg",
    ".aws",
    "credentials",
    "credentials.json",
    ".netrc",
}


class PathValidationError(Exception):
    """Raised when a path fails validation."""

    def __init__(self, message: str, path: str):
        self.path = path
        super().__init__(f"{message}: {path}")


def _get_allowed_directories() -> List[Path]:
    """Get the list of directories that are allowed for file operations."""
    allowed = []

    # Add configured paths (already resolved in config.py)
    if INBOX_PATH:
        allowed.append(INBOX_PATH)

    if ARCHIVE_PATH:
        allowed.append(ARCHIVE_PATH)

    if VAULT_PATH:
        allowed.append(VAULT_PATH)

    # Add state directory
    if STATE_DIR:
        allowed.append(STATE_DIR)

    return allowed


def canonicalize_path(path: str | Path) -> Path:
    """
    Canonicalize a path by expanding user (~) and resolving all symlinks.

    Args:
        path: Path string or Path object

    Returns:
        Fully resolved Path object
    """
    return Path(path).expanduser().resolve()


def is_path_within_directory(path: Path, directory: Path) -> bool:
    """
    Check if a path is within (or equal to) a directory.

    Args:
        path: The path to check
        directory: The allowed directory

    Returns:
        True if path is within or equal to directory
    """
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def is_blocked_system_path(path: Path) -> bool:
    """Check if a path is in a blocked system directory."""
    path_str = str(path)
    for blocked in BLOCKED_PATHS:
        if path_str == blocked or path_str.startswith(blocked + "/"):
            return True
    return False


def has_sensitive_filename(path: Path) -> bool:
    """Check if a path contains a sensitive filename."""
    # Check the filename itself
    if path.name in SENSITIVE_FILENAMES:
        return True

    # Check if any parent directory is sensitive
    for part in path.parts:
        if part in SENSITIVE_FILENAMES:
            return True

    return False


def validate_path(
    path: str | Path,
    allowed_dirs: Optional[List[Path]] = None,
    must_exist: bool = False,
    allow_outside_configured: bool = False,
) -> Path:
    """
    Validate a path for safety and optionally existence.

    Args:
        path: The path to validate
        allowed_dirs: Optional list of allowed directories. If None, uses configured paths.
        must_exist: If True, raises error if path doesn't exist
        allow_outside_configured: If True, allows paths outside configured directories
                                  (still blocks system paths and sensitive files)

    Returns:
        Canonicalized Path object

    Raises:
        PathValidationError: If validation fails
    """
    # Canonicalize
    canonical = canonicalize_path(path)

    # Check for blocked system paths
    if is_blocked_system_path(canonical):
        raise PathValidationError("Access to system path is blocked", str(canonical))

    # Check for sensitive filenames
    if has_sensitive_filename(canonical):
        raise PathValidationError("Access to sensitive file is blocked", str(canonical))

    # Check existence if required
    if must_exist and not canonical.exists():
        raise PathValidationError("Path does not exist", str(canonical))

    # Check if within allowed directories
    if not allow_outside_configured:
        if allowed_dirs is None:
            allowed_dirs = _get_allowed_directories()

        if not any(is_path_within_directory(canonical, d) for d in allowed_dirs):
            allowed_str = ", ".join(str(d) for d in allowed_dirs)
            raise PathValidationError(
                f"Path is outside allowed directories ({allowed_str})", str(canonical)
            )

    return canonical


def validate_relative_path(relative_path: str, base_dir: Path) -> Path:
    """
    Validate a relative path and ensure it stays within the base directory.

    This is useful for user-supplied paths that should be relative to a base.

    Args:
        relative_path: Relative path string (may contain .. etc.)
        base_dir: Base directory the path should stay within

    Returns:
        Canonicalized full path

    Raises:
        PathValidationError: If the resolved path escapes base_dir
    """
    # Resolve the full path
    full_path = (base_dir / relative_path).resolve()

    # Ensure it's still within base_dir
    if not is_path_within_directory(full_path, base_dir.resolve()):
        raise PathValidationError(f"Path traversal detected (escapes {base_dir})", relative_path)

    # Also apply standard validation
    return validate_path(full_path, allowed_dirs=[base_dir.resolve()])


def safe_join(base_dir: str | Path, *parts: str) -> Path:
    """
    Safely join path components, preventing traversal.

    Args:
        base_dir: Base directory
        *parts: Path components to join

    Returns:
        Safe joined path

    Raises:
        PathValidationError: If the result escapes base_dir
    """
    base = canonicalize_path(base_dir)
    result = base

    for part in parts:
        # Remove leading slashes to prevent absolute path injection
        clean_part = part.lstrip("/\\")
        result = result / clean_part

    # Resolve and verify still within base
    resolved = result.resolve()
    if not is_path_within_directory(resolved, base):
        raise PathValidationError(f"Path traversal detected (escapes {base})", "/".join(parts))

    return resolved
