"""Readwise integration — sync highlights into CoreRag.

Pulls highlights from the Readwise API and ingests them as documents
for RAG indexing. Tracks last sync timestamp to avoid re-importing.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.config import STATE_DIR
from src.integrations.base import IntegrationPlugin

logger = logging.getLogger(__name__)

READWISE_API_URL = "https://readwise.io/api/v2/highlights/"


class ReadwisePlugin(IntegrationPlugin):
    """Sync Readwise highlights into CoreRag."""

    def __init__(self, state_dir: Path | None = None):
        self._state_dir = state_dir or STATE_DIR / "integrations" / "readwise"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / "state.json"
        self._api_token = os.getenv("READWISE_API_TOKEN", "")

    def name(self) -> str:
        return "readwise"

    def check_connection(self) -> bool:
        """Verify the Readwise API token works."""
        if not self._api_token:
            return False
        try:
            resp = httpx.get(
                "https://readwise.io/api/v2/auth/",
                headers={"Authorization": f"Token {self._api_token}"},
                timeout=10,
            )
            return resp.status_code == 204
        except Exception:
            return False

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "required": ["READWISE_API_TOKEN"],
            "description": "Set READWISE_API_TOKEN environment variable with your Readwise API token.",
        }

    def sync(self) -> dict[str, Any]:
        """Fetch new highlights since last sync and return them as documents."""
        if not self._api_token:
            return {"items_synced": 0, "errors": ["READWISE_API_TOKEN not set"], "last_sync": ""}

        last_sync = self._load_last_sync()
        items_synced = 0
        errors = []
        documents = []

        try:
            page_cursor = None
            while True:
                params: dict[str, Any] = {"page_size": 100}
                if last_sync:
                    params["updated__gt"] = last_sync
                if page_cursor:
                    params["pageCursor"] = page_cursor

                resp = httpx.get(
                    READWISE_API_URL,
                    headers={"Authorization": f"Token {self._api_token}"},
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                for highlight in data.get("results", []):
                    doc = {
                        "content": highlight.get("text", ""),
                        "source": f"readwise:{highlight.get('id', '')}",
                        "metadata": {
                            "category": "Reading",
                            "type": "Highlight",
                            "book_title": highlight.get("book_title", ""),
                            "author": highlight.get("book_author", ""),
                            "highlighted_at": highlight.get("highlighted_at", ""),
                            "tags": [t["name"] for t in highlight.get("tags", [])],
                        },
                    }
                    documents.append(doc)
                    items_synced += 1

                page_cursor = data.get("nextPageCursor")
                if not page_cursor:
                    break

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Readwise sync error: {e}")

        sync_time = datetime.now().isoformat()
        self._save_last_sync(sync_time)

        return {
            "items_synced": items_synced,
            "documents": documents,
            "errors": errors,
            "last_sync": sync_time,
        }

    def _load_last_sync(self) -> str:
        """Load last sync timestamp."""
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                return data.get("last_sync", "")
            except Exception:
                pass
        return ""

    def _save_last_sync(self, timestamp: str) -> None:
        """Save last sync timestamp."""
        self._state_file.write_text(json.dumps({"last_sync": timestamp}))
