import logging
import re
from pathlib import Path
from src.extractor import extract_text
from src.intelligence import analyze_document
from src.quality.duplicate_detector import DuplicateDetector
from src.utils.privacy_audit import PrivacyScanner, load_custom_pii_terms, scan_custom_terms
from src.classification.auto_tagger import AutoTagger

# Singleton detector so state persists across files in a batch
_dedup = DuplicateDetector()

# Singleton scanner so Presidio model only loads once
_pii_scanner = PrivacyScanner()

# Load custom PII terms once at import time
_custom_pii_terms = load_custom_pii_terms()

# Lazy-initialized auto-tagger (loads embedding service on first use for hybrid tagging)
_auto_tagger = None


def _get_auto_tagger() -> AutoTagger:
    """Lazy-initialize auto-tagger with embedding support when available."""
    global _auto_tagger
    if _auto_tagger is None:
        embedder = None
        try:
            from src.embeddings.embedding_service import create_embedding_service
            svc = create_embedding_service()
            embedder = svc.embed_query
            logging.info("Auto-tagger initialized with embedding support (hybrid mode)")
        except Exception as e:
            logging.info(f"Auto-tagger using keyword-only mode: {e}")
        _auto_tagger = AutoTagger(embedder=embedder)
    return _auto_tagger


def process_document(file_path: Path):
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
            "summary": "AI Analysis in progress..."
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
        dup_matches = _dedup.check_file(file_path)
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
        metadata, full_text = analyze_document(text)

        # 4. PII Detection (Presidio + custom dictionary — replaces LLM is_sensitive)
        pii_sample = text[:20000]  # Scan first 20K chars for speed
        scan_result = _pii_scanner.scan(pii_sample, file_path=str(file_path))
        custom_matches = scan_custom_terms(pii_sample, _custom_pii_terms)

        # Merge and filter by confidence
        all_pii_matches = scan_result.matches + custom_matches
        high_confidence = [m for m in all_pii_matches if m.confidence >= 0.70]

        is_sensitive = len(high_confidence) > 0

        # Build detection summary for the dashboard (no raw PII values)
        pii_detections = []
        for m in high_confidence:
            pii_detections.append({
                "type": m.data_type.value,
                "confidence": round(m.confidence, 2),
                "context": m.context[:80],  # Truncated, already redacted by scanner
            })

        metadata["is_sensitive"] = is_sensitive
        metadata["pii_detections"] = pii_detections
        metadata["pii_source"] = "auto"

        # 4b. Auto-Tagging (keyword-based classification)
        try:
            tag_result = _get_auto_tagger().tag(text, file_path=str(file_path))
            metadata["tags"] = tag_result.assigned_tags
            metadata["suggested_tags"] = tag_result.suggested_tags
            if tag_result.assigned_tags:
                logging.info(
                    f"Auto-tagged {file_path.name}: {', '.join(tag_result.assigned_tags)}"
                )
        except Exception as e:
            logging.warning(f"Auto-tagging failed for {file_path.name}: {e}")
            metadata["tags"] = []
            metadata["suggested_tags"] = []

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
        base_name = re.sub(r'[^\w\-]', '_', base_name).strip('_')
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
        update_data = {
            "status": "pending",
            "metadata": metadata,
            "redacted_text": full_text,
            "proposed": {
                "filename": base_name,
                "category": metadata.get("category", "Unsorted"),
                "year": metadata.get("year", "Unknown"),
                "type": metadata.get("type", "Document"),
                "tags": metadata.get("tags", []),
            }
        }
        if duplicate_info:
            update_data["duplicate"] = duplicate_info

        update_item(item_id, update_data)

        # Register file in dedup index for future checks
        _dedup.add_file(file_path)
        _dedup._save_state()

        logging.info(f"--- File Staged for Review: {file_path.name} ---")

    except Exception as e:
        logging.error(f"Critical error during processing of {file_path.name}: {e}", exc_info=True)
