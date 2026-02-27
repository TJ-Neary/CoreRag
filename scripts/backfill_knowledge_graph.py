#!/usr/bin/env python3
"""
Backfill knowledge graph from already-indexed documents in LanceDB.

Reads all parent_chunks, runs entity extraction on each,
and stores entities/relationships in the knowledge graph DB.

Usage:
    python scripts/backfill_knowledge_graph.py           # Regex patterns (fast)
    python scripts/backfill_knowledge_graph.py --llm      # LLM extraction (better quality)
    python scripts/backfill_knowledge_graph.py --llm --clear  # Clear graph first, then LLM
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph.knowledge_graph import EntityExtractor, KnowledgeGraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    import lancedb

    parser = argparse.ArgumentParser(description="Backfill knowledge graph from LanceDB")
    parser.add_argument(
        "--llm", action="store_true", help="Use Ollama LLM for extraction (slower but better)"
    )
    parser.add_argument("--clear", action="store_true", help="Clear existing graph before backfill")
    args = parser.parse_args()

    db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
    graph_db_path = (
        Path(os.getenv("CoreRag_STATE_DIR", str(Path.home() / ".corerag"))) / "knowledge_graph.db"
    )

    logger.info(f"Connecting to LanceDB at {db_path}")
    db = lancedb.connect(db_path)

    if "parent_chunks" not in db.table_names():
        logger.error("No parent_chunks table found. Nothing to backfill.")
        return

    table = db.open_table("parent_chunks")
    rows = table.search().limit(10000).to_list()
    logger.info(f"Found {len(rows)} parent chunks")

    graph = KnowledgeGraph(graph_db_path)

    # Optionally clear existing graph
    if args.clear:
        import sqlite3

        conn = sqlite3.connect(graph_db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM entities")
        cursor.execute("DELETE FROM relationships")
        conn.commit()
        conn.close()
        logger.info("Cleared existing graph data")

    # Create extractor — with LLM if requested
    llm = None
    if args.llm:
        try:
            from src.utils.ollama_llm import OllamaLLM

            llm = OllamaLLM()
            logger.info(f"Using OllamaLLM ({llm.model}) for entity extraction")
        except Exception as e:
            logger.warning(f"Failed to initialize OllamaLLM: {e}, falling back to patterns")

    extractor = EntityExtractor(llm=llm)

    stats_before = graph.get_stats()
    logger.info(
        f"Graph before: {stats_before['total_entities']} entities, "
        f"{stats_before['total_relationships']} relationships"
    )

    # Group chunks by document_id to avoid re-extracting
    docs = {}
    for row in rows:
        doc_id = row.get("document_id", "")
        if doc_id not in docs:
            docs[doc_id] = {
                "content": row.get("content", ""),
                "source_path": row.get("source_path", ""),
            }
        else:
            docs[doc_id]["content"] += "\n\n" + row.get("content", "")

    logger.info(f"Grouped into {len(docs)} unique documents")

    total_entities = 0
    total_relationships = 0

    # Use async extraction if LLM is provided
    if llm:
        loop = asyncio.new_event_loop()
        try:
            for i, (doc_id, doc) in enumerate(docs.items()):
                text = doc["content"][:10000]
                source = doc["source_path"]

                try:
                    entities, relationships = loop.run_until_complete(
                        extractor.extract(text, doc_id)
                    )
                except Exception as e:
                    logger.warning(f"  LLM extraction failed for {source}: {e}, using patterns")
                    entities, relationships = extractor._extract_with_patterns(text, doc_id)

                if entities or relationships:
                    graph.add_from_extraction(entities, relationships)
                    total_entities += len(entities)
                    total_relationships += len(relationships)
                    logger.info(
                        f"  [{i+1}/{len(docs)}] {source}: {len(entities)} entities, "
                        f"{len(relationships)} relationships"
                    )
        finally:
            loop.close()
    else:
        for i, (doc_id, doc) in enumerate(docs.items()):
            text = doc["content"][:10000]
            source = doc["source_path"]

            entities, relationships = extractor._extract_with_patterns(text, doc_id)

            if entities or relationships:
                graph.add_from_extraction(entities, relationships)
                total_entities += len(entities)
                total_relationships += len(relationships)
                logger.info(
                    f"  [{i+1}/{len(docs)}] {source}: {len(entities)} entities, "
                    f"{len(relationships)} relationships"
                )

    stats_after = graph.get_stats()
    logger.info(
        f"\nBackfill complete:"
        f"\n  Mode: {'LLM' if llm else 'regex patterns'}"
        f"\n  Documents processed: {len(docs)}"
        f"\n  Entities extracted: {total_entities}"
        f"\n  Relationships extracted: {total_relationships}"
        f"\n  Graph now: {stats_after['total_entities']} entities, "
        f"{stats_after['total_relationships']} relationships"
    )


if __name__ == "__main__":
    main()
