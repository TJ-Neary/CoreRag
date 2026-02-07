"""Integration plugin base class.

All external integrations (Readwise, Pocket, etc.) must inherit from
IntegrationPlugin and implement the required methods.
"""

from abc import ABC, abstractmethod
from typing import Any


class IntegrationPlugin(ABC):
    """Abstract base class for external integrations."""

    @abstractmethod
    def name(self) -> str:
        """Return the integration name."""

    @abstractmethod
    def sync(self) -> dict[str, Any]:
        """Run a sync cycle.

        Returns dict with keys: items_synced, errors, last_sync.
        """

    @abstractmethod
    def check_connection(self) -> bool:
        """Verify the integration connection is working."""

    @abstractmethod
    def get_config_schema(self) -> dict[str, Any]:
        """Return the configuration schema for this integration."""
