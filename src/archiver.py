import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from src.config import ARCHIVE_PATH

SORTING_RULES_PATH = Path("sorting_rules.yaml")


def archive_original(file_path: Path, metadata: dict) -> Path:
    """
    Auto-determines target path based on Rules/AI and archives file.
    """
    # 1. Check User Rules
    user_target = _check_user_rules(file_path, metadata)

    if user_target:
        # Use user rule (relative path string)
        return archive_to_target(file_path, user_target)
    else:
        # Fallback to AI Classification
        category = _sanitize(metadata.get("category", "Unsorted"))
        year = _sanitize(metadata.get("year", "Unknown"))
        return archive_to_target(file_path, f"{category}/{year}")


def archive_to_target(file_path: Path, target_relative_path: str) -> Path:
    """
    Moves file to a specific target relative to ARCHIVE_PATH.
    Handling duplicates with timestamp.
    """
    dest_dir = ARCHIVE_PATH / target_relative_path

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.error(f"Failed to create archive directory {dest_dir}: {e}")
        dest_dir = ARCHIVE_PATH

    dest_path = dest_dir / file_path.name

    # Handle duplicates
    if dest_path.exists():
        timestamp = int(datetime.now().timestamp())
        dest_path = dest_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"

    try:
        shutil.move(str(file_path), str(dest_path))
        logging.info(f"Archived file to: {dest_path}")
        return dest_path
    except Exception as e:
        logging.error(f"Failed to move file to archive: {e}")
        raise e


def _check_user_rules(file_path: Path, metadata: dict) -> str:
    if not SORTING_RULES_PATH.exists():
        return None
    try:
        with open(SORTING_RULES_PATH, "r") as f:
            config = yaml.safe_load(f)
            rules = config.get("rules", [])
        filename = file_path.name.lower()
        for rule in rules:
            condition = rule.get("condition", {})
            ctype = condition.get("type", "filename")
            pattern = condition.get("pattern", "")
            target = rule.get("target", "")
            if not pattern or not target:
                continue
            if ctype == "filename" and re.search(pattern, filename, re.IGNORECASE):
                return target
    except Exception as e:
        logging.error(f"Error reading sorting rules: {e}")
    return None


def _sanitize(filename: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9 \-_]", "", str(filename))
    return safe.strip() or "Unknown"
