"""
Secure File Operations

Provides utilities for creating files and directories with appropriate
permissions for sensitive data. Key use cases:

1. PII terms dictionary (~/.corerag/pii_terms.yaml) - contains user secrets
2. State directory (~/.corerag/) - contains indexed data and caches
3. API keys and configuration files

Permissions:
- Directories: 0o700 (rwx------)  Owner only
- Sensitive files: 0o600 (rw-------)  Owner only
"""

import logging
import os
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Standard secure permissions
DIR_PERMISSIONS = 0o700  # rwx------
FILE_PERMISSIONS = 0o600  # rw-------


def secure_mkdir(path: Path, mode: int = DIR_PERMISSIONS) -> Path:
    """
    Create a directory with secure permissions.

    Args:
        path: Path to create
        mode: Permission mode (default: 0o700)

    Returns:
        The created/existing path
    """
    path = Path(path).expanduser()

    if path.exists():
        # Verify existing permissions are secure
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if current_mode & 0o077:  # Check if group/other has any access
            logger.warning(f"Tightening permissions on existing directory: {path}")
            os.chmod(path, mode)
    else:
        # Create with secure permissions
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, mode)
        logger.debug(f"Created secure directory: {path}")

    return path


def secure_write(
    path: Path, content: str, mode: int = FILE_PERMISSIONS, encoding: str = "utf-8"
) -> Path:
    """
    Write content to a file with secure permissions.

    Creates parent directories with secure permissions if needed.

    Args:
        path: File path
        content: Content to write
        mode: Permission mode (default: 0o600)
        encoding: File encoding

    Returns:
        The file path
    """
    path = Path(path).expanduser()

    # Ensure parent directory exists and is secure
    if not path.parent.exists():
        secure_mkdir(path.parent)

    # Write with secure permissions
    # First create/truncate with restricted umask
    old_umask = os.umask(0o077)
    try:
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        os.chmod(path, mode)
    finally:
        os.umask(old_umask)

    logger.debug(f"Wrote secure file: {path}")
    return path


def ensure_secure_permissions(path: Path, is_directory: bool = False) -> bool:
    """
    Verify and fix permissions on an existing file or directory.

    Args:
        path: Path to check
        is_directory: Whether path is a directory

    Returns:
        True if permissions were already secure, False if they were fixed
    """
    path = Path(path).expanduser()

    if not path.exists():
        return True  # Nothing to fix

    current_mode = stat.S_IMODE(path.stat().st_mode)
    target_mode = DIR_PERMISSIONS if is_directory else FILE_PERMISSIONS

    # Check if group or other has any access
    if current_mode & 0o077:
        logger.warning(f"Fixing insecure permissions on: {path}")
        os.chmod(path, target_mode)
        return False

    return True


def secure_state_directory(state_dir: Optional[Path] = None) -> Path:
    """
    Ensure the CoreRag state directory exists with secure permissions.

    This should be called early in application startup.

    Args:
        state_dir: State directory path (default: ~/.corerag)

    Returns:
        The state directory path
    """
    if state_dir is None:
        from src.config import STATE_DIR

        state_dir = STATE_DIR

    state_dir = Path(state_dir).expanduser()

    # Create or verify the state directory
    secure_mkdir(state_dir)

    # Check key subdirectories
    sensitive_subdirs = [
        "pii_terms.yaml",  # PII dictionary file
        "profiles",  # User profiles
        "sessions",  # Session data
    ]

    # Fix permissions on existing sensitive paths
    for name in sensitive_subdirs:
        subpath = state_dir / name
        if subpath.exists():
            is_dir = subpath.is_dir()
            ensure_secure_permissions(subpath, is_directory=is_dir)

    return state_dir


def create_pii_terms_file(terms: list[dict], path: Optional[Path] = None) -> Path:
    """
    Create or update the PII terms YAML file with secure permissions.

    Args:
        terms: List of term dicts with 'value' and 'type' keys
        path: File path (default: ~/.corerag/pii_terms.yaml)

    Returns:
        The file path
    """
    import yaml

    if path is None:
        from src.config import STATE_DIR

        path = STATE_DIR / "pii_terms.yaml"

    content = yaml.dump({"terms": terms}, default_flow_style=False)
    return secure_write(path, content)
