import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SORTING_RULES_PATH = Path(__file__).resolve().parent.parent / "sorting_rules.yaml"

DEFAULT_STRUCTURE = {
    "folders": {
        "Medical": ["Prescriptions", "Lab Results", "Insurance"],
        "Financial": ["Taxes", "Statements", "Receipts"],
        "Legal": ["Contracts", "Agreements"],
        "Personal": ["Identity", "Correspondence"],
        "Work": ["Projects", "HR"],
        "Unsorted": [],
    },
    "rules": [],
}


def load_folder_structure() -> dict:
    """Read folder structure from sorting_rules.yaml, creating default if missing."""
    if not SORTING_RULES_PATH.exists():
        save_folder_structure(DEFAULT_STRUCTURE)
        return dict(DEFAULT_STRUCTURE)
    try:
        with open(SORTING_RULES_PATH, "r") as f:
            data = yaml.safe_load(f)
        return data if data else dict(DEFAULT_STRUCTURE)
    except Exception as e:
        logger.error(f"Failed to load sorting rules: {e}")
        return dict(DEFAULT_STRUCTURE)


def save_folder_structure(structure: dict) -> None:
    """Write folder structure to sorting_rules.yaml."""
    try:
        with open(SORTING_RULES_PATH, "w") as f:
            yaml.dump(structure, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        logger.error(f"Failed to save sorting rules: {e}")


def get_folder_choices() -> list[str]:
    """Returns a flat list of folder paths for dashboard dropdowns."""
    structure = load_folder_structure()
    folders = structure.get("folders", {})
    choices: list[str] = []
    for parent, children in folders.items():
        choices.append(parent)
        if isinstance(children, list):
            for child in children:
                choices.append(f"{parent}/{child}")
    return sorted(choices)


def ensure_folder_in_structure(folder_path: str) -> None:
    """Adds a user-typed folder path to sorting_rules.yaml if it doesn't exist.

    Handles paths like 'Work/Safe Place/Employee Handbook' by adding
    'Safe Place/Employee Handbook' under the 'Work' parent.
    """
    if not folder_path or folder_path == "Unsorted":
        return

    parts = folder_path.split("/")
    parent = parts[0].strip()
    children = [p.strip() for p in parts[1:] if p.strip()]

    structure = load_folder_structure()
    folders = structure.setdefault("folders", {})

    if parent not in folders:
        folders[parent] = []

    if children:
        # Build the sub-path as a single entry (e.g. "Safe Place/Employee Handbook")
        sub_path = "/".join(children)
        existing = folders[parent] if isinstance(folders[parent], list) else []
        if sub_path not in existing:
            existing.append(sub_path)
            folders[parent] = existing

    save_folder_structure(structure)
