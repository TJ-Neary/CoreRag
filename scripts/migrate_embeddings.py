#!/usr/bin/env python3
"""
Embedding Migration Script

Re-embeds all chunks with a new model and adds enrichment fields introduced
in the retrieval enhancement phases. Handles dimension changes (e.g., 384d → 1024d)
by dropping and recreating tables atomically.

Uses PyArrow tables directly (no pandas dependency).

Enrichment applied to existing data (no LLM required):
- content_hash: SHA256 of chunk text
- quality_score: heuristic quality scoring
- date_extracted / date_confidence: regex date extraction
- source_authority: defaults to "unknown" (metadata not available for backfill)
- context_prefix: empty (requires LLM — skipped for backfill)

Parent chunks also get content_hash and empty summary fields.

Usage:
    python scripts/migrate_embeddings.py                    # Full migration
    python scripts/migrate_embeddings.py --dry-run          # Preview without writing
    python scripts/migrate_embeddings.py --model BAAI/bge-m3  # Explicit model
    python scripts/migrate_embeddings.py --batch-size 64    # Custom batch size
    python scripts/migrate_embeddings.py --enrich-only      # Add new fields without re-embedding
"""

import argparse
import gc
import hashlib
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.config import DB_PATH, EMBEDDING_MODEL  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _compute_enrichment(texts: list[str]) -> dict[str, list]:
    """Compute enrichment fields for a list of chunk texts.

    Returns dict of column_name -> list of values.
    """
    total = len(texts)

    # content_hash
    logger.info("  Computing content hashes...")
    hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]

    # quality_score
    quality_scores = [0.0] * total
    try:
        from src.quality.chunk_scorer import ChunkScorer

        scorer = ChunkScorer()
        logger.info("  Computing quality scores...")
        for i, text in enumerate(texts):
            try:
                score = scorer.score(text)
                quality_scores[i] = score.overall
            except Exception:
                pass
            if (i + 1) % 2000 == 0:
                logger.info(f"    Quality scored {i + 1}/{total}")
        low = sum(1 for s in quality_scores if s < 0.3)
        logger.info(f"  Quality scoring complete ({low} low-quality chunks)")
    except Exception as e:
        logger.warning(f"  Quality scoring failed, using defaults: {e}")

    # date_extracted / date_confidence
    dates = [""] * total
    date_confidences = [0.0] * total
    try:
        from src.quality.date_extractor import DateExtractor

        extractor = DateExtractor()
        logger.info("  Extracting dates...")
        for i, text in enumerate(texts):
            try:
                d, c = extractor.extract(text)
                dates[i] = d or ""
                date_confidences[i] = c
            except Exception:
                pass
            if (i + 1) % 2000 == 0:
                logger.info(f"    Date extracted {i + 1}/{total}")
        found = sum(1 for d in dates if d)
        logger.info(f"  Date extraction complete ({found} dates found)")
    except Exception as e:
        logger.warning(f"  Date extraction failed, using defaults: {e}")

    return {
        "content_hash": hashes,
        "context_prefix": [""] * total,
        "quality_score": quality_scores,
        "source_authority": ["unknown"] * total,
        "date_extracted": dates,
        "date_confidence": date_confidences,
    }


def migrate_embeddings(
    target_model: str | None = None,
    dry_run: bool = False,
    batch_size: int = 32,
    enrich_only: bool = False,
) -> dict:
    """Re-embed all chunks with a new embedding model and add enrichment fields.

    Args:
        target_model: Model to migrate to (default: config EMBEDDING_MODEL).
        dry_run: If True, preview changes without writing.
        batch_size: Batch size for embedding.
        enrich_only: If True, add new columns without re-embedding.

    Returns:
        Migration statistics dict.
    """
    import lancedb

    target_model = target_model or EMBEDDING_MODEL
    db = lancedb.connect(str(DB_PATH))

    # Check tables exist
    tables = db.table_names()
    has_children = "child_chunks" in tables
    has_parents = "parent_chunks" in tables

    if not has_children:
        logger.warning("No child_chunks table found — nothing to migrate.")
        return {"status": "skipped", "reason": "no_data"}

    child_table = db.open_table("child_chunks")
    total_children = child_table.count_rows()

    parent_count = 0
    if has_parents:
        parent_table = db.open_table("parent_chunks")
        parent_count = parent_table.count_rows()

    logger.info(f"Migration target: {target_model}")
    logger.info(f"Child chunks: {total_children}")
    logger.info(f"Parent chunks: {parent_count}")
    logger.info(f"Enrich only: {enrich_only}")

    if dry_run:
        action = "enrich" if enrich_only else "re-embed + enrich"
        logger.info(
            f"[DRY RUN] Would {action} {total_children} child chunks + {parent_count} parents"
        )
        return {
            "status": "dry_run",
            "total_children": total_children,
            "total_parents": parent_count,
            "target_model": target_model,
        }

    start_time = time.time()

    # ── Read existing child data as list of dicts ─────────────────────────
    logger.info("Reading existing child chunks...")
    all_children = child_table.to_arrow().to_pydict()

    texts = all_children["content"]
    existing_columns = set(all_children.keys())
    logger.info(f"  Existing columns: {sorted(existing_columns)}")

    # ── Re-embed (unless enrich_only) ─────────────────────────────────────
    new_dim = None
    if not enrich_only:
        from src.embeddings.embedding_service import EmbeddingService

        embedder = EmbeddingService(model_name=target_model, batch_size=batch_size)
        new_dim = embedder.dimension
        logger.info(f"New embedding dimension: {new_dim}")
        logger.info(f"Re-embedding {total_children} chunks...")

        # Truncate long texts for embedding (prevents MPS stalls on dense batches).
        # BGE-M3 max_seq_length is 8192 tokens; 2000 chars (~500 tokens) retains
        # core semantics while keeping batch GPU memory bounded.
        max_embed_chars = 2000
        embed_texts = [t[:max_embed_chars] if len(t) > max_embed_chars else t for t in texts]
        long_count = sum(1 for t in texts if len(t) > max_embed_chars)
        if long_count:
            logger.info(f"  Truncated {long_count} chunks > {max_embed_chars} chars for embedding")

        new_embeddings = []
        for i in range(0, len(embed_texts), batch_size):
            batch = embed_texts[i : i + batch_size]
            batch_embs = embedder.embed_documents(batch, show_progress=False)
            new_embeddings.extend(batch_embs)

            done = min(i + batch_size, len(texts))
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            logger.info(f"  Embedded {done}/{len(texts)} ({rate:.0f} chunks/sec)")

            gc.collect()

        all_children["vector"] = new_embeddings

    # ── Enrich child chunks ───────────────────────────────────────────────
    logger.info("Enriching child chunks...")
    enrichment = _compute_enrichment(texts)

    for col, values in enrichment.items():
        if col not in existing_columns:
            all_children[col] = values
            logger.info(f"  Added column: {col}")
        else:
            # Fill empty/missing values in existing columns
            existing = all_children[col]
            updated = 0
            for j in range(len(existing)):
                if existing[j] is None or existing[j] == "" or existing[j] == 0.0:
                    existing[j] = values[j]
                    updated += 1
            if updated > 0:
                logger.info(f"  Filled {updated} empty values in: {col}")

    # ── Swap child_chunks table ───────────────────────────────────────────
    logger.info("Swapping child_chunks table...")
    db.drop_table("child_chunks")
    db.create_table("child_chunks", all_children)

    # Rebuild FTS index
    try:
        new_child_table = db.open_table("child_chunks")
        new_child_table.create_fts_index("content", replace=True)
        logger.info("FTS index rebuilt on child_chunks")
    except Exception as e:
        logger.warning(f"FTS index rebuild failed (non-fatal): {e}")

    # ── Enrich + swap parent_chunks ───────────────────────────────────────
    if has_parents:
        logger.info("Reading existing parent chunks...")
        all_parents = parent_table.to_arrow().to_pydict()
        parent_existing = set(all_parents.keys())

        if "content_hash" not in parent_existing:
            logger.info("  Computing parent content hashes...")
            all_parents["content_hash"] = [
                hashlib.sha256(t.encode()).hexdigest() for t in all_parents["content"]
            ]
            logger.info(f"  Added content_hash to {parent_count} parents")

        if "summary" not in parent_existing:
            all_parents["summary"] = [""] * parent_count
            logger.info("  Added summary (empty — LLM enrichment skipped for backfill)")

        logger.info("Swapping parent_chunks table...")
        db.drop_table("parent_chunks")
        db.create_table("parent_chunks", all_parents)
        logger.info("Parent chunks migrated")

    # ── Save embedding cache ──────────────────────────────────────────────
    if not enrich_only:
        embedder.save_cache()

    elapsed = time.time() - start_time
    logger.info(f"Migration complete in {elapsed:.1f}s")

    result = {
        "status": "complete",
        "total_children": total_children,
        "total_parents": parent_count,
        "target_model": target_model,
        "elapsed_seconds": round(elapsed, 1),
        "enrich_only": enrich_only,
    }
    if new_dim:
        result["new_dimension"] = new_dim
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate embedding model for CoreRag")
    parser.add_argument("--model", type=str, help="Target embedding model")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size")
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Add new schema fields without re-embedding vectors",
    )
    args = parser.parse_args()

    result = migrate_embeddings(
        target_model=args.model,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        enrich_only=args.enrich_only,
    )

    logger.info(f"Result: {result}")


if __name__ == "__main__":
    main()
