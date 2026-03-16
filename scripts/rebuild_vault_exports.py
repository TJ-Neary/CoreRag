#!/usr/bin/env python3
"""Re-export Obsidian vault markdown files with improved metadata.

Updates frontmatter with LLM collection tags, summaries, sensitivity flags,
and corrects the content heading. Uses catalog metadata + LanceDB chunk text.

Usage:
    python scripts/rebuild_vault_exports.py              # Full re-export
    python scripts/rebuild_vault_exports.py --dry-run    # Preview only
"""

import argparse
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.catalog.catalog_manager import CatalogManager  # noqa: E402
from src.config import DB_PATH  # noqa: E402
from src.exporter import export_to_vault  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("rebuild_vault")


def reconstruct_text(doc_id: str) -> str | None:
    """Reconstruct document text from LanceDB child chunks."""
    import lancedb

    try:
        db = lancedb.connect(str(DB_PATH))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            table = db.open_table("child_chunks")
        results = (
            table.search().where(f"document_id = '{doc_id}'", prefilter=True).limit(500).to_list()
        )
        if not results:
            return None
        results.sort(key=lambda r: r.get("chunk_index", 0))
        chunks = [r.get("content", "") for r in results if r.get("content")]
        return "\n\n".join(chunks) if chunks else None
    except Exception as e:
        logger.debug("Text reconstruction failed for %s: %s", doc_id, e)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-export vault files with improved metadata")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN — no files will be written")

    catalog = CatalogManager()
    all_docs = catalog.search()

    logger.info("Found %d documents in catalog", len(all_docs))

    exported = 0
    skipped = 0

    for doc in all_docs:
        # Parse comma-delimited tags stored as ",tag1,tag2,"
        tags: list[str] = []
        if doc.tags:
            tags = [t.strip() for t in doc.tags.strip(",").split(",") if t.strip()]

        metadata = {
            "category": doc.category or "Unsorted",
            "year": doc.year or "Unknown",
            "type": doc.file_type or "Document",
            "summary": doc.summary or "",
            "tags": tags,
            "is_sensitive": bool(doc.is_sensitive),
        }

        # Prefer main_rag_doc_id for chunk lookup; fall back to catalog record id
        doc_id = doc.main_rag_doc_id or doc.id
        text = reconstruct_text(doc_id)

        if not text:
            logger.warning(
                "No chunks found for %s (doc_id=%s) — skipping",
                doc.original_filename,
                doc_id,
            )
            skipped += 1
            continue

        if args.dry_run:
            summary_preview = (metadata["summary"] or "none")[:60]
            logger.info(
                "Would re-export: %s  category=%s  sensitive=%s  tags=%s  summary=%s",
                doc.original_filename,
                metadata["category"],
                metadata["is_sensitive"],
                tags[:5],
                summary_preview,
            )
            exported += 1
            continue

        try:
            export_to_vault(text, metadata, doc.original_filename)
            exported += 1
            logger.info("Re-exported: %s", doc.original_filename)
        except Exception as e:
            logger.error("Failed to export %s: %s", doc.original_filename, e)
            skipped += 1

    logger.info(
        "=== Re-export complete: %d %s, %d skipped ===",
        exported,
        "would export" if args.dry_run else "exported",
        skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
