import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from src.staging import get_item, update_item, load_manifest, save_manifest
from src.archiver import archive_to_target
from src.exporter import export_to_vault
from src.extractor import extract_text
from src.correction_log import log_correction

logger = logging.getLogger(__name__)


def _redact_pii(text: str, file_name: str) -> str:
    """Apply PII redaction for Obsidian and RAG exports.

    Uses three detection layers:
    1. Presidio NER + regex patterns (SSNs, emails, phones, names, etc.)
    2. Custom PII dictionary (~/.corerag/pii_terms.yaml) for user-defined terms
    3. Technical secret patterns (API keys, passwords, etc.)

    Replaces matches with type-specific placeholders like [REDACTED-SSN],
    [REDACTED-EMAIL], etc. This keeps the document readable and searchable
    while stripping actual sensitive values before they reach Claude via MCP.
    """
    try:
        from src.utils.privacy_audit import (
            PrivacyScanner, load_custom_pii_terms, scan_custom_terms
        )

        scanner = PrivacyScanner()  # hybrid: Presidio NER + regex patterns
        result = scanner.scan(text, file_path=file_name)

        # Also match custom PII dictionary terms
        custom_terms = load_custom_pii_terms()
        custom_matches = scan_custom_terms(text, custom_terms)

        # Merge all matches
        all_matches = result.matches + custom_matches

        if not all_matches:
            logger.info(f"PII redaction: no matches found in {file_name}")
            return text

        # Sort matches by position descending so replacements don't shift offsets
        sorted_matches = sorted(all_matches, key=lambda m: m.start_pos, reverse=True)

        # Deduplicate overlapping matches (keep highest confidence)
        filtered = []
        last_start = len(text) + 1
        for match in sorted_matches:
            if match.confidence < 0.70:
                continue
            # Skip if this match overlaps with a previously kept match
            if match.end_pos > last_start:
                continue
            filtered.append(match)
            last_start = match.start_pos

        redacted = text
        for match in filtered:
            placeholder = f"[REDACTED-{match.data_type.value.upper()}]"
            redacted = redacted[:match.start_pos] + placeholder + redacted[match.end_pos:]

        logger.info(
            f"PII redaction: replaced {len(filtered)} matches in {file_name} "
            f"(tier: {result.privacy_tier.value})"
        )
        return redacted

    except Exception as e:
        logger.error(f"PII redaction failed for {file_name}: {e}", exc_info=True)
        return text  # Fall back to original text rather than blocking


def _index_in_rag(text: str, file_name: str, metadata: dict) -> None:
    """Chunk, embed, and store document text in the LanceDB vector database."""
    try:
        import lancedb
        from src.chunking.parent_child import ParentChildChunker
        from src.embeddings.embedding_service import create_embedding_service

        db_path = os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        db = lancedb.connect(db_path)
        chunker = ParentChildChunker()
        embedder = create_embedding_service()

        document_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]

        parents, children = chunker.chunk_document(
            content=text,
            document_id=document_id,
            metadata={
                "source_path": file_name,
                "file_type": "document",
                "file_name": file_name,
                "category": metadata.get("category", ""),
                "year": metadata.get("year", ""),
            },
        )

        if not children:
            logger.warning(f"RAG indexing: no chunks created for {file_name}")
            return

        child_texts = [c.content for c in children]
        embeddings = embedder.embed_documents(child_texts, show_progress=False)

        # Build comma-delimited tags string for LIKE-based filtering
        # Format: ",tag1,tag2," — enables WHERE tags LIKE '%,tag1,%'
        raw_tags = metadata.get("tags", [])
        if isinstance(raw_tags, list) and raw_tags:
            tags_str = "," + ",".join(raw_tags) + ","
        else:
            tags_str = ""

        parent_data = []
        for p in parents:
            parent_data.append({
                "id": p.id,
                "document_id": p.document_id,
                "content": p.content,
                "source_path": file_name,
                "section_title": p.section_title or "",
                "token_count": p.token_count,
                "created_at": datetime.now().isoformat(),
                "tags": tags_str,
            })

        child_data = []
        for c, emb in zip(children, embeddings):
            child_data.append({
                "id": c.id,
                "parent_id": c.parent_id,
                "document_id": c.document_id,
                "content": c.content,
                "vector": emb,
                "chunk_index": c.chunk_index,
                "source_path": file_name,
                "tags": tags_str,
            })

        # Store parents
        try:
            parent_table = db.open_table("parent_chunks")
            parent_table.add(parent_data)
        except Exception:
            try:
                db.create_table("parent_chunks", parent_data)
            except Exception:
                parent_table = db.open_table("parent_chunks")
                parent_table.add(parent_data)

        # Store children (with vectors)
        try:
            child_table = db.open_table("child_chunks")
            child_table.add(child_data)
        except Exception:
            try:
                db.create_table("child_chunks", child_data)
            except Exception:
                child_table = db.open_table("child_chunks")
                child_table.add(child_data)

        logger.info(
            f"RAG indexed: {file_name} ({len(parents)} parents, {len(children)} children)"
        )

    except Exception as e:
        logger.error(f"RAG indexing failed for {file_name}: {e}", exc_info=True)


def _extract_entities(text: str, file_name: str) -> None:
    """Extract entities and relationships from text, store in knowledge graph."""
    try:
        import asyncio
        from src.graph.knowledge_graph import KnowledgeGraph, EntityExtractor

        graph_db_path = Path(
            os.getenv("CORERAG_DB_PATH", str(Path.home() / ".corerag" / "lancedb"))
        ).parent / "knowledge_graph.db"
        graph = KnowledgeGraph(graph_db_path)

        # Try to use Ollama for better multi-word entity extraction
        llm = None
        try:
            from src.utils.ollama_llm import OllamaLLM
            llm = OllamaLLM()
        except Exception:
            pass

        extractor = EntityExtractor(llm=llm)
        document_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]

        # Use async extract() which tries LLM first, falls back to regex patterns
        loop = asyncio.new_event_loop()
        try:
            entities, relationships = loop.run_until_complete(
                extractor.extract(text[:10000], document_id)
            )
        finally:
            loop.close()

        if entities or relationships:
            graph.add_from_extraction(entities, relationships)
            via = "LLM" if llm else "patterns"
            logger.info(
                f"Knowledge graph: extracted {len(entities)} entities, "
                f"{len(relationships)} relationships from {file_name} (via {via})"
            )
        else:
            logger.info(f"Knowledge graph: no entities extracted from {file_name}")

    except Exception as e:
        logger.warning(f"Entity extraction failed for {file_name}: {e}")


def execute_approved_item(item_id: str):
    """
    Finalizes an item:
    1. Renames original file if needed.
    2. Archives to the approved folder.
    3. Exports to Vault.
    4. Indexes in RAG database.
    5. Updates Status to 'completed'.
    """
    item = get_item(item_id)
    if not item:
        logger.error(f"Item {item_id} not found.")
        return False

    if item["status"] != "approved":
        logger.error(f"Item {item_id} is not approved (Status: {item['status']})")
        return False

    original_path = Path(item["original_path"])
    if not original_path.exists():
        logger.error(f"Original file missing: {original_path}")
        update_item(item_id, {"status": "error", "error": "File missing"})
        return False

    proposed = item["proposed"]
    target_filename = proposed.get("filename")
    target_folder = proposed.get("target_folder")

    current_path = original_path
    if target_filename:
        if not Path(target_filename).suffix:
            target_filename += original_path.suffix

        if target_filename != original_path.name:
            new_path = original_path.with_name(target_filename)
            try:
                original_path.rename(new_path)
                current_path = new_path
                logger.info(f"Renamed {original_path.name} -> {target_filename}")
            except Exception as e:
                logger.error(f"Failed to rename file: {e}")
                update_item(item_id, {"status": "error", "error": f"Rename failed: {e}"})
                return False

    try:
        if not target_folder:
            target_folder = f"{item['metadata'].get('category')}/{item['metadata'].get('year')}"

        # Build final metadata from human-reviewed proposed values
        final_metadata = item["metadata"].copy()
        final_metadata.update({
            "category": proposed.get("category"),
            "year": proposed.get("year"),
            "type": proposed.get("type"),
            "tags": proposed.get("tags", []),
        })

        # Extract full text BEFORE archiving (archive moves the file)
        try:
            export_text = extract_text(current_path)
            if not export_text:
                logger.warning(f"Text extraction returned empty for {current_path.name}, using staged text")
                export_text = item["redacted_text"]
            else:
                logger.info(f"Extracted {len(export_text)} chars from {current_path.name}")
        except Exception as e:
            logger.warning(f"Text extraction failed for {current_path.name}: {e}, using staged text")
            export_text = item["redacted_text"]

        # If PII is flagged, redact the full text for both Obsidian and RAG.
        # The original file archives untouched, but exported content gets
        # actual PII values replaced with [REDACTED-TYPE] placeholders.
        is_sensitive = item.get("metadata", {}).get("is_sensitive", False)
        if is_sensitive:
            export_text = _redact_pii(export_text, current_path.name)
            logger.info(f"PII-redacted text will be used for exports of {current_path.name}")

        # Archive (moves original file to target folder — always unredacted)
        archive_to_target(current_path, target_folder)

        # Export to Obsidian vault (unless user opted out)
        if not item.get("skip_obsidian"):
            export_to_vault(export_text, final_metadata, current_path.name)
        else:
            logger.info(f"Skipping Obsidian export for {current_path.name} (user opted out)")

        # Index in RAG vector database (unless user opted out)
        if not item.get("skip_rag"):
            _index_in_rag(export_text, current_path.name, final_metadata)
            # Extract entities for knowledge graph
            _extract_entities(export_text, current_path.name)
        else:
            logger.info(f"Skipping RAG indexing for {current_path.name} (user opted out)")

        # Track document version
        try:
            from src.utils.versioning import VersionManager
            vm = VersionManager()
            document_id = hashlib.sha256(export_text[:5000].encode()).hexdigest()[:16]
            vm.create_version(
                document_id=document_id,
                content=export_text,
                changed_by="system",
                change_type="create",
                change_summary=f"Ingested from {original_path.name}",
                metadata={"source": str(original_path), "category": final_metadata.get("category")},
            )
            logger.info(f"Version tracked for {current_path.name}")
        except Exception as e:
            logger.warning(f"Version tracking failed for {current_path.name}: {e}")

        # Register tags in central tag registry
        try:
            from src.utils.tagging import TagManager
            _tm = TagManager()
            for tag in final_metadata.get("tags", []):
                _tm.create_tag(tag)
                _tm.add_tag(document_id, tag)
        except Exception as e:
            logger.warning(f"Tag registry update failed for {current_path.name}: {e}")

        # Log any human corrections for AI learning
        log_correction(item)

        update_item(item_id, {"status": "completed"})
        return True

    except Exception as e:
        logger.error(f"Execution failed for {item_id}: {e}")
        update_item(item_id, {"status": "error", "error": str(e)})
        return False
