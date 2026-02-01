import fcntl
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CORRECTIONS_PATH = Path("corrections_log.json")
MAX_EXAMPLES = 10  # Number of recent corrections to include in prompts


def _load_corrections() -> list[dict]:
    if not CORRECTIONS_PATH.exists():
        return []
    try:
        with open(CORRECTIONS_PATH, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                content = f.read()
                return json.loads(content) if content else []
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Failed to load corrections: {e}")
        return []


def _save_corrections(corrections: list[dict]) -> None:
    try:
        with open(CORRECTIONS_PATH, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.truncate()
                json.dump(corrections, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Failed to save corrections: {e}")


def log_correction(item: dict) -> None:
    """Compare AI-suggested values against human-edited proposed values and log diffs."""
    metadata = item.get("metadata", {})
    proposed = item.get("proposed", {})

    diffs = {}

    # Compare filename
    ai_name = metadata.get("suggested_name", "")
    human_name = proposed.get("filename", "")
    if ai_name and human_name and ai_name != human_name:
        # Strip CUI_ prefix for comparison since it's auto-added
        clean_human = human_name.removeprefix("CUI_")
        if ai_name != clean_human:
            diffs["filename"] = {"ai": ai_name, "human": clean_human}

    # Compare category
    ai_cat = metadata.get("category", "")
    human_cat = proposed.get("category", "")
    if ai_cat and human_cat and ai_cat != human_cat:
        diffs["category"] = {"ai": ai_cat, "human": human_cat}

    # Compare year
    ai_year = metadata.get("year", "")
    human_year = proposed.get("year", "")
    if ai_year and human_year and ai_year != human_year:
        diffs["year"] = {"ai": ai_year, "human": human_year}

    # Compare type
    ai_type = metadata.get("type", "")
    human_type = proposed.get("type", "")
    if ai_type and human_type and ai_type != human_type:
        diffs["type"] = {"ai": ai_type, "human": human_type}

    # Compare PII sensitivity — track when human overrides auto-detection
    pii_source = metadata.get("pii_source", "auto")
    if pii_source == "manual":
        ai_sensitive = len(metadata.get("pii_detections", [])) > 0
        human_sensitive = metadata.get("is_sensitive", False)
        if ai_sensitive and not human_sensitive:
            diffs["pii_override"] = {"ai": "sensitive", "human": "not_sensitive"}
        elif not ai_sensitive and human_sensitive:
            diffs["pii_override"] = {"ai": "not_sensitive", "human": "sensitive"}

    # Compare target folder
    ai_folder = f"{ai_cat}/{ai_year}" if ai_cat and ai_year else ""
    human_folder = proposed.get("target_folder", "")
    if human_folder and ai_folder and human_folder != ai_folder:
        diffs["target_folder"] = {"ai": ai_folder, "human": human_folder}

    if not diffs:
        return

    entry = {
        "timestamp": datetime.now().isoformat(),
        "original_file": Path(item.get("original_path", "")).name,
        "summary": metadata.get("summary", ""),
        "corrections": diffs,
    }

    corrections = _load_corrections()
    corrections.append(entry)

    # Keep only last 50 entries to avoid unbounded growth
    if len(corrections) > 50:
        corrections = corrections[-50:]

    _save_corrections(corrections)
    logger.info(f"Logged {len(diffs)} correction(s) for {entry['original_file']}")


def get_recent_examples() -> str:
    """Format recent corrections as few-shot examples for the analysis prompt."""
    corrections = _load_corrections()
    if not corrections:
        return ""

    recent = corrections[-MAX_EXAMPLES:]
    lines = []
    for c in recent:
        parts = []
        for field, vals in c["corrections"].items():
            if field == "pii_override":
                parts.append(f"PII: AI marked sensitive but human confirmed no PII")
            else:
                parts.append(f"{field}: '{vals['ai']}' -> '{vals['human']}'")
        correction_str = "; ".join(parts)
        lines.append(f"- File: {c['original_file']} | Corrections: {correction_str}")

    return (
        "\n\nLearn from these past corrections where a human reviewer fixed AI suggestions:\n"
        + "\n".join(lines)
        + "\nApply these patterns to improve your classifications.\n"
    )
