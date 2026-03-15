#!/usr/bin/env python3
"""Retroactive catalog rebuild from existing LanceDB + staging manifest data.

Populates the SQLite document catalog for files already in the system.
Run after initial P8 SP1 deployment to catalog existing ~99 documents.

Usage:
    python scripts/rebuild_catalog.py              # Full rebuild
    python scripts/rebuild_catalog.py --dry-run    # Preview without writing
    python scripts/rebuild_catalog.py --skip-llm   # Skip LLM re-classification
    python scripts/rebuild_catalog.py --phase 1    # Run specific phase only
    python scripts/rebuild_catalog.py --verbose    # Detailed output
"""

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.catalog.catalog_manager import CatalogManager, DocumentRecord, ExportRecord  # noqa: E402
from src.config import ARCHIVE_PATH, DB_PATH, STATE_DIR  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("rebuild_catalog")


# ── Phase 1: Scan LanceDB ─────────────────────────────────────────────────────


def phase1_scan_lancedb() -> dict[str, dict[str, Any]]:
    """Scan LanceDB child_chunks table for unique documents.

    Groups child chunks by document_id and extracts source_path, chunk count,
    and tags for each unique document.

    Returns:
        Dict mapping document_id -> metadata dict.
    """
    import lancedb

    db = lancedb.connect(str(DB_PATH))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tables = db.table_names()

    if "child_chunks" not in tables:
        logger.error("No child_chunks table found in LanceDB at %s", DB_PATH)
        return {}

    logger.info("Reading child_chunks table...")
    child_table = db.open_table("child_chunks")
    data = child_table.to_arrow().to_pydict()

    total_rows = len(data.get("document_id", []))
    logger.info("Loaded %d child chunk rows", total_rows)

    # Column-oriented dict — access by column name, index by row position
    doc_ids = data.get("document_id", [])
    source_paths = data.get("source_path", [""] * total_rows)
    tags_list = data.get("tags", [""] * total_rows)

    # Group by document_id
    docs: dict[str, dict[str, Any]] = {}
    for i in range(total_rows):
        doc_id = doc_ids[i]
        if not doc_id:
            continue

        if doc_id not in docs:
            docs[doc_id] = {
                "document_id": doc_id,
                "source_path": source_paths[i] if i < len(source_paths) else "",
                "chunk_count": 0,
                "tags": tags_list[i] if i < len(tags_list) else "",
                # Metadata populated in later phases
                "category": "",
                "year": "",
                "summary": "",
                "is_sensitive": False,
                "file_type": "",
                "archive_path": "",
            }
        docs[doc_id]["chunk_count"] += 1

    # Also count parent chunks per document
    if "parent_chunks" in tables:
        try:
            parent_table = db.open_table("parent_chunks")
            parent_data = parent_table.to_arrow().to_pydict()
            parent_doc_ids = parent_data.get("document_id", [])
            for pdid in parent_doc_ids:
                if pdid in docs:
                    docs[pdid].setdefault("parent_count", 0)
                    docs[pdid]["parent_count"] = docs[pdid].get("parent_count", 0) + 1
        except Exception as e:
            logger.debug("Could not read parent_chunks: %s", e)

    logger.info("Phase 1: Found %d unique documents in LanceDB", len(docs))
    return docs


# ── Phase 2: Cross-reference with staging manifest ────────────────────────────


def phase2_cross_reference_manifest(docs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Enrich documents with metadata from staging_manifest.json.

    Matches by filename between LanceDB source_path and manifest original_path.

    Args:
        docs: Dict from phase1, mapping document_id -> metadata.

    Returns:
        Same dict, enriched with category/year/summary/tags/is_sensitive.
    """
    manifest_paths = [
        STATE_DIR / "staging_manifest.json",
        Path("staging_manifest.json"),
    ]

    manifest_data: dict[str, Any] = {}
    for mp in manifest_paths:
        if mp.exists():
            try:
                raw = mp.read_text()
                manifest_data = json.loads(raw)
                logger.info("Phase 2: Loaded manifest from %s (%d entries)", mp, len(manifest_data))
                break
            except Exception as e:
                logger.warning("Failed to read manifest %s: %s", mp, e)

    if not manifest_data:
        logger.warning("Phase 2: No staging manifest found — metadata will be limited")
        return docs

    # Build filename -> manifest entry lookup for O(1) matching
    manifest_by_name: dict[str, dict[str, Any]] = {}
    for _item_id, item in manifest_data.items():
        if not isinstance(item, dict):
            continue
        orig_path = item.get("original_path", "")
        if orig_path:
            name = Path(orig_path).name
            manifest_by_name[name] = item

    # Cross-reference by filename
    matched = 0
    for _doc_id, doc in docs.items():
        source_name = Path(doc["source_path"]).name if doc["source_path"] else ""
        if not source_name:
            continue

        item = manifest_by_name.get(source_name)
        if not item:
            continue

        matched += 1
        meta = item.get("metadata", {})
        proposed = item.get("proposed", {})

        doc["category"] = (
            proposed.get("category") or meta.get("category") or doc.get("category", "")
        )
        doc["year"] = proposed.get("year") or meta.get("year") or doc.get("year", "")
        doc["summary"] = meta.get("summary", "") or doc.get("summary", "")
        doc["is_sensitive"] = meta.get("is_sensitive", False)

        # Tags: merge from proposed/meta
        raw_tags = proposed.get("tags") or meta.get("tags", [])
        if isinstance(raw_tags, list) and raw_tags:
            doc["tags"] = ",".join(raw_tags)

        # File type from original filename
        doc["file_type"] = Path(source_name).suffix.lstrip(".")

    logger.info("Phase 2: Matched %d/%d documents with manifest metadata", matched, len(docs))
    return docs


# ── Phase 3: LLM Re-classification (optional) ─────────────────────────────────


def phase3_llm_reclassify(docs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Re-classify documents through the improved LLM analysis pipeline.

    Attempts to find and extract text from each document's archived original,
    then runs analyze_document() for fresh classification.

    This is the slow phase (~30s per file). Skip with --skip-llm.

    Args:
        docs: Dict from earlier phases.

    Returns:
        Same dict, with LLM-refreshed category/year/summary/tags.
    """
    import asyncio

    from src.extractor import extract_text
    from src.intelligence import analyze_document

    total = len(docs)
    reclassified = 0

    for i, (doc_id, doc) in enumerate(docs.items(), 1):
        source_path = Path(doc["source_path"]) if doc["source_path"] else None
        source_name = source_path.name if source_path else doc_id[:12]
        logger.info("Phase 3: [%d/%d] Re-classifying %s...", i, total, source_name)

        # Try to find the file for text extraction
        text = None
        search_paths = []
        if source_path:
            search_paths.append(source_path)
            search_paths.append(ARCHIVE_PATH / source_path.name)
            # Legacy archive locations
            search_paths.append(Path.home() / "Documents" / "Knowledge" / source_path.name)
            search_paths.append(Path.home() / "Documents" / source_path.name)

        if doc.get("archive_path"):
            search_paths.insert(0, Path(doc["archive_path"]))

        for sp in search_paths:
            if sp.exists():
                try:
                    text = extract_text(sp)
                    if text and len(text.strip()) > 50:
                        break
                except Exception:
                    pass

        if not text:
            logger.warning("  Could not find/extract text for %s, skipping LLM", source_name)
            continue

        try:
            metadata, _redacted = asyncio.run(analyze_document(text))
            doc["category"] = metadata.get("category", doc.get("category", ""))
            doc["year"] = metadata.get("year", doc.get("year", ""))
            doc["summary"] = metadata.get("summary", doc.get("summary", ""))
            new_tags = metadata.get("tags", [])
            if isinstance(new_tags, list) and new_tags:
                doc["tags"] = ",".join(new_tags)
            reclassified += 1
            logger.info(
                "  -> %s / %s / tags: %s",
                metadata.get("category", "?"),
                metadata.get("year", "?"),
                new_tags,
            )
        except Exception as e:
            logger.warning("  LLM re-classification failed: %s", e)

    logger.info("Phase 3: Re-classified %d/%d documents", reclassified, total)
    return docs


# ── Phase 4: Locate archived originals ─────────────────────────────────────────


def phase4_locate_originals(docs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Locate archived original files on disk.

    Searches ARCHIVE_PATH (~/Documents/PKM/) and legacy locations for each
    document's original file. Records the archive_path for the catalog.

    Args:
        docs: Dict from earlier phases.

    Returns:
        Same dict, with archive_path populated where files were found.
    """
    search_dirs = [
        ARCHIVE_PATH,
        Path.home() / "Documents",
        Path.home() / "Documents" / "Knowledge",  # Legacy location
    ]

    # Filter to existing directories
    existing_dirs = [d for d in search_dirs if d.exists()]
    if not existing_dirs:
        logger.warning("Phase 4: No search directories exist")
        return docs

    found = 0
    not_found = 0

    for _doc_id, doc in docs.items():
        source_name = Path(doc["source_path"]).name if doc["source_path"] else ""
        if not source_name:
            continue

        # Skip if already located
        if doc.get("archive_path"):
            found += 1
            continue

        # Search for the file
        located = False
        for search_dir in existing_dirs:
            try:
                for match in search_dir.rglob(source_name):
                    doc["archive_path"] = str(match)
                    found += 1
                    located = True
                    break
            except PermissionError:
                continue
            if located:
                break

        if not located:
            not_found += 1
            logger.debug("  Not found: %s", source_name)

    logger.info(
        "Phase 4: Located %d/%d archived originals (%d not found)",
        found,
        len(docs),
        not_found,
    )
    return docs


# ── Registration ──────────────────────────────────────────────────────────────


def register_in_catalog(docs: dict[str, dict[str, Any]], *, dry_run: bool = False) -> int:
    """Register all discovered documents in the SQLite catalog.

    Args:
        docs: Dict mapping document_id -> metadata dict.
        dry_run: If True, only preview what would be written.

    Returns:
        Number of documents registered (or would-be-registered in dry run).
    """
    if dry_run:
        logger.info("DRY RUN: Would register %d documents:", len(docs))
        for doc_id, doc in docs.items():
            source_name = Path(doc["source_path"]).name if doc["source_path"] else doc_id[:12]
            logger.info(
                "  %s: category=%s, year=%s, tags=%s, chunks=%d",
                source_name,
                doc.get("category") or "?",
                doc.get("year") or "?",
                doc.get("tags", ""),
                doc.get("chunk_count", 0),
            )
        return len(docs)

    catalog = CatalogManager()
    registered = 0
    skipped = 0

    for doc_id, doc in docs.items():
        source_name = Path(doc["source_path"]).name if doc["source_path"] else doc_id[:12]

        try:
            # Check if already registered
            existing = catalog.get(doc_id)
            if existing:
                logger.debug("  Already cataloged: %s", source_name)
                skipped += 1
                continue

            record = DocumentRecord(
                id=doc_id,
                original_filename=source_name,
                original_path=doc.get("source_path", ""),
                archive_path=doc.get("archive_path", ""),
                main_rag_doc_id=doc_id,
                category=doc.get("category") or "Unsorted",
                year=doc.get("year", ""),
                tags=doc.get("tags", ""),
                is_sensitive=bool(doc.get("is_sensitive")),
                summary=doc.get("summary", ""),
                file_type=doc.get("file_type", ""),
                file_size=0,
                chunk_count=doc.get("chunk_count", 0),
                parent_count=doc.get("parent_count", 0),
            )
            catalog.register(record)

            # Record LanceDB export
            catalog.record_export(
                ExportRecord(
                    document_id=doc_id,
                    destination="main_rag",
                    path=doc_id,
                    redacted=bool(doc.get("is_sensitive")),
                )
            )

            registered += 1
            logger.debug("  Registered: %s", source_name)
        except Exception as e:
            logger.warning("  Failed to register %s: %s", source_name, e)

    logger.info(
        "Registered %d new documents in catalog (%d already existed)",
        registered,
        skipped,
    )
    return registered


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    """Run the catalog rebuild pipeline."""
    parser = argparse.ArgumentParser(
        description="Rebuild catalog from existing LanceDB + manifest data"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--skip-llm", action="store_true", help="Skip LLM re-classification (Phase 3)"
    )
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run specific phase only")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=== Catalog Rebuild Script ===")
    logger.info("LanceDB path: %s", DB_PATH)
    logger.info("Archive path: %s", ARCHIVE_PATH)

    docs: dict[str, dict[str, Any]] = {}

    # Phase 1: Scan LanceDB
    if not args.phase or args.phase >= 1:
        docs = phase1_scan_lancedb()
        if not docs:
            logger.error("No documents found in LanceDB. Nothing to rebuild.")
            return 1

    # Phase 2: Cross-reference manifest
    if not args.phase or args.phase >= 2:
        docs = phase2_cross_reference_manifest(docs)

    # Phase 3: LLM re-classification (optional)
    if (not args.phase or args.phase == 3) and not args.skip_llm:
        docs = phase3_llm_reclassify(docs)
    elif args.skip_llm:
        logger.info("Phase 3: Skipped (--skip-llm)")

    # Phase 4: Locate originals
    if not args.phase or args.phase >= 4:
        docs = phase4_locate_originals(docs)

    # Register in catalog
    count = register_in_catalog(docs, dry_run=args.dry_run)

    qualifier = "would be " if args.dry_run else ""
    logger.info("=== Rebuild complete: %d documents %scataloged ===", count, qualifier)
    return 0


if __name__ == "__main__":
    sys.exit(main())
