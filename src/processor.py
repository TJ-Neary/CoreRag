import logging
import re
from pathlib import Path

from src.config import PII_CONTEXT_TRUNCATE, PII_MIN_CONFIDENCE, PII_SAMPLE_MAX_CHARS
from src.exceptions import ProcessingError
from src.extractor import extract_text
from src.intelligence import analyze_document
from src.quality.duplicate_detector import DuplicateDetector
from src.utils.privacy_audit import PrivacyScanner, load_custom_pii_terms, scan_custom_terms

# Lazy-initialized singletons — avoids loading spaCy model at import time
_dedup: DuplicateDetector | None = None
_pii_scanner: PrivacyScanner | None = None
_custom_pii_terms: list | None = None


def _get_dedup() -> DuplicateDetector:
    global _dedup
    if _dedup is None:
        _dedup = DuplicateDetector()
    return _dedup


def _get_pii_scanner() -> PrivacyScanner:
    global _pii_scanner
    if _pii_scanner is None:
        _pii_scanner = PrivacyScanner()
    return _pii_scanner


def _get_custom_pii_terms() -> list:
    global _custom_pii_terms
    if _custom_pii_terms is None:
        _custom_pii_terms = load_custom_pii_terms()
    return _custom_pii_terms


async def process_document(file_path: Path, tags: list[str] | None = None):
    """
    Orchestrates the ingestion:
    1. Immediately stage with 'processing' status (visible in dashboard)
    2. Extract Text
    2b. Duplicate check against index
    3. Analyze (classification + summary via LLM)
    4. PII scan (Presidio + custom dictionary — replaces LLM is_sensitive flag)
    5. Update staging with results (status -> 'pending')
    """
    try:
        logging.info(f"Processing started for: {file_path}")

        # 1. IMMEDIATE STAGING (Status: 'processing')
        # This ensures the GUI sees the file immediately
        from src.staging import add_to_staging, update_item

        initial_metadata = {
            "suggested_name": file_path.name,
            "category": "Analyzing...",
            "year": "...",
            "summary": "AI Analysis in progress...",
        }

        # Add to manifest with 'processing' status
        item_id = add_to_staging(file_path, initial_metadata, "", file_path.name)
        update_item(item_id, {"status": "processing"})
        logging.info(f"Item {item_id} marked as processing.")

        # 2. Text Extraction
        text = extract_text(file_path)
        if not text:
            logging.error(f"Failed to extract text from {file_path}")
            update_item(item_id, {"status": "error", "error": "Text extraction failed"})
            return

        # 2b. Duplicate check (before expensive AI analysis)
        dup_matches = _get_dedup().check_file(file_path)
        duplicate_info = None
        if dup_matches:
            best = dup_matches[0]
            duplicate_info = {
                "is_duplicate": True,
                "match_type": best.match_type,
                "similarity": best.similarity,
                "matched_file": best.file1,
            }
            logging.warning(
                f"Duplicate detected for {file_path.name}: "
                f"{best.match_type} match ({best.similarity:.0%}) with {best.file1}"
            )

        # 3. Intelligence Analysis (classification + summary; PII is handled below)
        logging.info("Analyzing document content...")
        metadata, full_text = await analyze_document(text)

        # 4. PII Detection (Presidio + custom dictionary — replaces LLM is_sensitive)
        pii_sample = text[:PII_SAMPLE_MAX_CHARS]  # Scan first N chars for speed
        scan_result = _get_pii_scanner().scan(pii_sample, file_path=str(file_path))
        custom_matches = scan_custom_terms(pii_sample, _get_custom_pii_terms())

        # Merge and filter by confidence
        all_pii_matches = scan_result.matches + custom_matches
        high_confidence = [m for m in all_pii_matches if m.confidence >= PII_MIN_CONFIDENCE]

        # Sensitivity decision: custom dictionary matches always trigger.
        # Presidio NER-only detections (generic names/addresses) do NOT trigger
        # Only YOUR PII triggers sensitivity:
        # - Custom dictionary matches (your 85 terms — always trigger)
        # - SSN/credit card patterns (universally sensitive regardless of whose)
        # Emails, phone numbers, names, and addresses from other people/orgs
        # are NOT your PII — they stay readable and don't trigger sensitivity.
        always_sensitive_types = {"ssn", "credit_card"}
        has_custom_match = len(custom_matches) > 0
        has_universal_pii = any(
            m.data_type.value.lower() in always_sensitive_types for m in high_confidence
        )
        is_sensitive = has_custom_match or has_universal_pii

        # Build detection summary for the dashboard (no raw PII values)
        pii_detections = []
        for m in high_confidence:
            pii_detections.append(
                {
                    "type": m.data_type.value,
                    "confidence": round(m.confidence, 2),
                    "context": m.context[:PII_CONTEXT_TRUNCATE],  # Truncated, already redacted
                }
            )

        metadata["is_sensitive"] = is_sensitive
        metadata["pii_detections"] = pii_detections
        metadata["pii_source"] = "auto"

        # 4b. LLM-Powered Tagging (replaces keyword auto-tagger)
        # Tags come from the LLM analysis — purpose-driven collection tags,
        # not keyword-matching shotgun tags
        llm_tags = metadata.get("tags", [])
        if isinstance(llm_tags, str):
            llm_tags = [t.strip() for t in llm_tags.split(",") if t.strip()]

        # Add year as a collection tag if extracted
        year = metadata.get("year", "")
        if year and year != "Unknown":
            if year not in llm_tags:
                llm_tags.append(year)

        # Cap at 5 tags total
        metadata["tags"] = llm_tags[:5]
        metadata["suggested_tags"] = llm_tags  # Keep full list for dashboard suggestions
        if metadata["tags"]:
            logging.info(f"LLM-tagged {file_path.name}: {', '.join(metadata['tags'])}")

        if is_sensitive:
            logging.info(
                f"PII scan: {len(high_confidence)} detection(s) in {file_path.name} "
                f"(types: {', '.join(set(m.data_type.value for m in high_confidence))})"
            )
        else:
            logging.info(f"PII scan: no detections in {file_path.name}")

        # Calculate Suggested Filename (with CUI Logic)
        base_name = metadata.get("suggested_name", "") or file_path.stem
        # Clean up: replace spaces with underscores, remove problematic chars
        base_name = re.sub(r"[^\w\-]", "_", base_name).strip("_")
        if not base_name:
            base_name = file_path.stem

        if is_sensitive and not base_name.upper().startswith("CUI_"):
            base_name = f"CUI_{base_name}"

        logging.info(
            f"Analysis Complete. Proposed Name: {base_name}, "
            f"Category: {metadata.get('category')}, Summary: {metadata.get('summary', '')[:80]}"
        )

        # 5. Update Staging with Results (Status: 'pending')
        # metadata dict stores the full analysis results (LLM + PII scan)
        # proposed dict stores the human-editable fields shown on the dashboard
        # redacted_text stores the full extracted text (redaction happens at commit time)
        proposed = {
            "filename": base_name,
            "category": metadata.get("category", "Unsorted"),
            "year": metadata.get("year", "Unknown"),
            "type": metadata.get("type", "Document"),
            "tags": metadata.get("tags", []),
        }

        # Apply learned rule hints from user correction patterns
        if metadata.get("_learned_folder"):
            proposed["target_folder"] = metadata["_learned_folder"]
            logging.info(f"Learned rule applied: folder -> {metadata['_learned_folder']}")
        if metadata.get("_learned_sensitivity") is not None:
            metadata["is_sensitive"] = metadata["_learned_sensitivity"]
            logging.info(f"Learned rule applied: sensitivity -> {metadata['_learned_sensitivity']}")

        update_data = {
            "status": "pending",
            "metadata": metadata,
            "redacted_text": full_text,
            "proposed": proposed,
        }
        if duplicate_info:
            update_data["duplicate"] = duplicate_info

        update_item(item_id, update_data)

        # Register file in dedup index for future checks
        _get_dedup().add_file(file_path)
        _get_dedup()._save_state()

        logging.info(f"--- File Staged for Review: {file_path.name} ---")

    except ProcessingError:
        raise
    except Exception as e:
        logging.error(f"Critical error during processing of {file_path.name}: {e}", exc_info=True)
        raise ProcessingError(str(e), file_path=str(file_path)) from e
