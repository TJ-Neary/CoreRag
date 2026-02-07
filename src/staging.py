import fcntl
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.exceptions import DatabaseError

STAGING_MANIFEST_PATH = Path("staging_manifest.json")


def _read_locked(f):
    """Read JSON from a file with a shared (read) lock."""
    fcntl.flock(f, fcntl.LOCK_SH)
    try:
        content = f.read()
        return json.loads(content) if content else {}
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)


def _write_locked(f, data):
    """Write JSON to a file with an exclusive (write) lock."""
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2)
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)


def load_manifest():
    if not STAGING_MANIFEST_PATH.exists():
        return {}
    try:
        with open(STAGING_MANIFEST_PATH, "r") as f:
            return _read_locked(f)
    except Exception as e:
        logging.error(f"Failed to load manifest: {e}")
        raise DatabaseError(
            f"Failed to load staging manifest: {e}", table_name="staging_manifest"
        ) from e


def save_manifest(data):
    try:
        with open(STAGING_MANIFEST_PATH, "w") as f:
            _write_locked(f, data)
    except Exception as e:
        logging.error(f"Failed to save manifest: {e}")
        raise DatabaseError(
            f"Failed to save staging manifest: {e}", table_name="staging_manifest"
        ) from e


def _load_modify_save(modifier):
    """Atomically load, modify, and save the manifest under an exclusive lock.

    The modifier callable receives the manifest dict and should return a value.
    The (possibly mutated) manifest is saved back after the modifier runs.
    """
    STAGING_MANIFEST_PATH.touch(exist_ok=True)
    try:
        with open(STAGING_MANIFEST_PATH, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                content = f.read()
                manifest = json.loads(content) if content else {}
                result = modifier(manifest)
                f.seek(0)
                f.truncate()
                json.dump(manifest, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return result
    except Exception as e:
        logging.error(f"Failed to modify manifest: {e}")
        raise DatabaseError(
            f"Failed to modify staging manifest: {e}", table_name="staging_manifest"
        ) from e


def add_to_staging(
    original_path: Path, metadata: dict, redacted_text: str, suggested_filename: str
):
    item_id = str(uuid.uuid4())

    def _add(manifest):
        manifest[item_id] = {
            "id": item_id,
            "original_path": str(original_path.resolve()),
            "status": "pending",
            "timestamp_ingested": datetime.now().isoformat(),
            "metadata": metadata,
            "redacted_text": redacted_text,
            "proposed": {
                "filename": suggested_filename,
                "category": metadata.get("category", "Unsorted"),
                "year": metadata.get("year", "Unknown"),
                "type": metadata.get("type", "Doc"),
                "tags": metadata.get("tags", []),
            },
        }

    _load_modify_save(_add)
    logging.info(f"Added item {item_id} to staging manifest.")
    return item_id


def get_pending_items():
    manifest = load_manifest()
    return {
        k: v
        for k, v in manifest.items()
        if v["status"] == "pending" or v.get("status") == "processing"
    }


def update_item(item_id: str, updates: dict):
    def _update(manifest):
        if item_id not in manifest:
            return False
        # Deep merge for 'proposed' if present
        if "proposed" in updates:
            manifest[item_id]["proposed"].update(updates["proposed"])
            remaining = {k: v for k, v in updates.items() if k != "proposed"}
            manifest[item_id].update(remaining)
        else:
            manifest[item_id].update(updates)
        return True

    result = _load_modify_save(_update)
    if result:
        logging.info(f"Updated item {item_id}.")
    return result or False


def get_item(item_id: str):
    manifest = load_manifest()
    return manifest.get(item_id)
