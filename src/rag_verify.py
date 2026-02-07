"""RAG verification: compare original documents against indexed RAG content.

Extracts text from archived originals and compares against parent chunks
stored in LanceDB to verify completeness and fidelity.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from src.utils.query_sanitize import build_eq_clause

logger = logging.getLogger(__name__)


def _get_rag_text(file_name: str) -> Optional[str]:
    """Pull all parent chunks for a file from LanceDB and concatenate in order."""
    try:
        import lancedb

        from src.config import DB_PATH

        db = lancedb.connect(DB_PATH)

        try:
            parent_table = db.open_table("parent_chunks")
        except Exception:
            logger.warning("parent_chunks table not found")
            return None

        results = (
            parent_table.search()
            .where(build_eq_clause("source_path", file_name), prefilter=True)
            .limit(1000)
            .to_list()
        )

        if not results:
            return None

        # Sort by ID to maintain document order
        results.sort(key=lambda r: r.get("id", ""))
        return "\n".join(r.get("content", "") for r in results)

    except Exception as e:
        logger.error(f"Failed to get RAG text for {file_name}: {e}")
        return None


def _get_rag_file_list() -> list[str]:
    """Get list of all unique source_path values in the RAG index."""
    try:
        import lancedb

        from src.config import DB_PATH

        db = lancedb.connect(DB_PATH)

        try:
            parent_table = db.open_table("parent_chunks")
        except Exception:
            return []

        results = parent_table.search().limit(10000).to_list()
        return list(set(r.get("source_path", "") for r in results if r.get("source_path")))

    except Exception:
        return []


def _sample_words(text: str, interval: int = 100) -> list[tuple[int, str]]:
    """Extract every Nth word with its position index."""
    words = text.split()
    return [(i, words[i]) for i in range(0, len(words), interval) if i < len(words)]


def verify_file(file_name: str, archive_path: str) -> dict:
    """Compare a single file's original text against its RAG content.

    Args:
        file_name: The filename as stored in RAG source_path
        archive_path: Base path to search for the archived original

    Returns:
        Dict with verification metrics
    """
    from src.extractor import extract_text

    result: dict[str, Any] = {
        "file_name": file_name,
        "status": "unknown",
        "original_chars": 0,
        "rag_chars": 0,
        "char_ratio": 0.0,
        "original_words": 0,
        "rag_words": 0,
        "word_coverage": 0.0,
        "spot_checks_total": 0,
        "spot_checks_passed": 0,
        "spot_check_rate": 0.0,
        "issues": [],
    }

    # Find the archived original
    archive_base = Path(archive_path)
    matches = list(archive_base.rglob(file_name))
    if not matches:
        result["status"] = "original_not_found"
        result["issues"].append(f"Archived file not found under {archive_path}")
        return result

    original_file = matches[0]

    # Extract text from original
    try:
        original_text = extract_text(original_file)
        if not original_text:
            result["status"] = "extraction_failed"
            result["issues"].append("Text extraction returned empty")
            return result
    except Exception as e:
        result["status"] = "extraction_failed"
        result["issues"].append(f"Text extraction error: {e}")
        return result

    # Get RAG content
    rag_text = _get_rag_text(file_name)
    if not rag_text:
        result["status"] = "not_in_rag"
        result["issues"].append("File not found in RAG index")
        result["original_chars"] = len(original_text)
        result["original_words"] = len(original_text.split())
        return result

    # Character counts
    result["original_chars"] = len(original_text)
    result["rag_chars"] = len(rag_text)
    result["char_ratio"] = round(len(rag_text) / len(original_text), 3) if original_text else 0

    # Word counts
    original_words = original_text.split()
    rag_words = rag_text.split()
    result["original_words"] = len(original_words)
    result["rag_words"] = len(rag_words)

    # Word coverage: what % of original words appear in RAG text
    rag_word_set = set(w.lower().strip(".,;:!?()[]{}\"'") for w in rag_words)
    original_word_set = set(w.lower().strip(".,;:!?()[]{}\"'") for w in original_words)
    if original_word_set:
        matched = original_word_set & rag_word_set
        result["word_coverage"] = round(len(matched) / len(original_word_set), 3)

    # Spot checks: sample every 100th word from original, check if it's in RAG
    samples = _sample_words(original_text, interval=100)
    result["spot_checks_total"] = len(samples)
    passed = 0
    failed_spots = []
    for idx, word in samples:
        clean_word = word.lower().strip(".,;:!?()[]{}\"'")
        if len(clean_word) < 3:
            passed += 1  # Skip trivial words
            continue
        if clean_word in rag_text.lower():
            passed += 1
        else:
            failed_spots.append(f"word #{idx}: '{word}'")

    result["spot_checks_passed"] = passed
    result["spot_check_rate"] = round(passed / len(samples), 3) if samples else 1.0

    if failed_spots and len(failed_spots) <= 5:
        result["issues"].append(f"Spot check misses: {', '.join(failed_spots)}")
    elif failed_spots:
        result["issues"].append(f"{len(failed_spots)} spot check misses")

    # Overall status
    if result["char_ratio"] >= 0.90 and result["word_coverage"] >= 0.85:
        result["status"] = "good"
    elif result["char_ratio"] >= 0.70 and result["word_coverage"] >= 0.70:
        result["status"] = "acceptable"
    else:
        result["status"] = "degraded"
        result["issues"].append(
            f"Content may be incomplete (char ratio: {result['char_ratio']}, "
            f"word coverage: {result['word_coverage']})"
        )

    return result


def verify_all(archive_path: Optional[str] = None) -> list[dict]:
    """Verify all files in the RAG index against their archived originals.

    Args:
        archive_path: Base path to search for originals.
                      Defaults to ARCHIVE_PATH from env.

    Returns:
        List of per-file verification results
    """
    if not archive_path:
        from src.config import ARCHIVE_PATH

        archive_path = str(ARCHIVE_PATH)

    file_names = _get_rag_file_list()
    if not file_names:
        return []

    results = []
    for fn in sorted(file_names):
        logger.info(f"Verifying: {fn}")
        results.append(verify_file(fn, archive_path))

    # Summary stats
    good = sum(1 for r in results if r["status"] == "good")
    acceptable = sum(1 for r in results if r["status"] == "acceptable")
    degraded = sum(1 for r in results if r["status"] == "degraded")
    missing = sum(1 for r in results if r["status"] in ("not_in_rag", "original_not_found"))

    logger.info(
        f"RAG verification complete: {good} good, {acceptable} acceptable, "
        f"{degraded} degraded, {missing} missing ({len(results)} total)"
    )

    return results
