"""Role-based access control for PII content.

Scaffold — provides role definitions and permission checks
but is not yet wired into API routes.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from src.config import STATE_DIR

logger = logging.getLogger(__name__)


class Role(Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass
class User:
    username: str
    role: Role
    api_key: str = ""


class AccessControl:
    """Role-based access control for CoreRag content."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or STATE_DIR / "access_control.yaml"
        self._users: dict[str, User] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load user roles from YAML config."""
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
            for user_data in data.get("users", []):
                role = Role(user_data.get("role", "viewer"))
                user = User(
                    username=user_data["username"],
                    role=role,
                    api_key=user_data.get("api_key", ""),
                )
                self._users[user.username] = user
        except Exception as e:
            logger.debug(f"Could not load access control config: {e}")

    def _save_config(self) -> None:
        """Save user roles to YAML config."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "users": [
                {"username": u.username, "role": u.role.value, "api_key": u.api_key}
                for u in self._users.values()
            ]
        }
        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def add_user(self, username: str, role: Role, api_key: str = "") -> User:
        """Add or update a user."""
        user = User(username=username, role=role, api_key=api_key)
        self._users[username] = user
        self._save_config()
        return user

    def get_user(self, username: str) -> Optional[User]:
        """Get a user by username."""
        return self._users.get(username)

    def can_view_pii(self, username: str) -> bool:
        """Check if user can view PII content (admin/editor only)."""
        user = self._users.get(username)
        if not user:
            return False
        return user.role in (Role.ADMIN, Role.EDITOR)

    def can_edit(self, username: str) -> bool:
        """Check if user can edit content."""
        user = self._users.get(username)
        if not user:
            return False
        return user.role in (Role.ADMIN, Role.EDITOR)

    def can_admin(self, username: str) -> bool:
        """Check if user has admin access."""
        user = self._users.get(username)
        if not user:
            return False
        return user.role == Role.ADMIN

    def filter_results(self, results: list[dict], username: str) -> list[dict]:
        """Filter search results based on user permissions.

        Strips PII-containing content for viewers who lack PII access.
        """
        if self.can_view_pii(username):
            return results

        filtered = []
        for result in results:
            r = result.copy()
            if r.get("is_sensitive"):
                r["content"] = "[Content hidden — PII access required]"
                r.pop("pii_detections", None)
            filtered.append(r)
        return filtered
