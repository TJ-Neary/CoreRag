import logging
from pathlib import Path
from src.extractor import extract_text
from src.intelligence import analyze_document

def process_document(file_path: Path):
    """
    Orchestrates the ingestion:
    1. Immediately stage with 'processing' status (visible in dashboard)
    2. Extract Text
    3. Analyze (PII/Category)
    4. Update staging with results (status -> 'pending')
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

        # 3. Intelligence / PII Analysis (This takes time)
        logging.info("Analyzing document content...")
        metadata, redacted_text = analyze_document(text)

        # Calculate Suggested Filename (with CUI Logic)
        base_name = metadata.get("suggested_name", file_path.stem)
        is_sensitive = metadata.get("is_sensitive", False)

        if is_sensitive and not base_name.upper().startswith("CUI_"):
            base_name = f"CUI_{base_name}"

        logging.info(f"Analysis Complete. Proposed Name: {base_name}")

        # 4. Update Staging with Results (Status: 'pending')
        update_item(item_id, {
            "status": "pending",
            "metadata": metadata,
            "redacted_text": redacted_text,
            "proposed": {
                "filename": base_name,
                "category": metadata.get("category", "Unsorted"),
                "year": metadata.get("year", "Unknown"),
                "type": metadata.get("type", "Doc")
            }
        })

        logging.info(f"--- File Staged for Review: {file_path.name} ---")

    except Exception as e:
        logging.error(f"Critical error during processing of {file_path.name}: {e}", exc_info=True)
