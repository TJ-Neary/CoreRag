import hashlib
import logging
from pathlib import Path

from src import config
from src.archiver import archive_to_target
from src.correction_log import log_correction
from src.exceptions import ProcessingError
from src.exporter import export_to_vault
from src.extractor import extract_text
from src.staging import get_item, update_item

logger = logging.getLogger(__name__)


def _redact_pii(text: str, file_name: str, detection_overrides: list[dict] | None = None) -> str:
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
        from src.utils.privacy_audit import PrivacyScanner, load_custom_pii_terms, scan_custom_terms

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
            if match.confidence < config.PII_MIN_CONFIDENCE:
                continue
            # Skip if this match overlaps with a previously kept match
            if match.end_pos > last_start:
                continue
            filtered.append(match)
            last_start = match.start_pos

        # Build keep set from user overrides (selective redaction)
        keep_ranges: set[tuple[int, int, str]] = set()
        if detection_overrides:
            for det in detection_overrides:
                if det.get("action") == "keep":
                    keep_ranges.add(
                        (det.get("start_pos", -1), det.get("end_pos", -1), det.get("type", ""))
                    )

        # Filter out matches that user chose to keep
        if keep_ranges:
            filtered = [
                match
                for match in filtered
                if (match.start_pos, match.end_pos, match.data_type.value) not in keep_ranges
            ]

        redacted = text
        for match in filtered:
            placeholder = f"[REDACTED-{match.data_type.value.upper()}]"
            redacted = redacted[: match.start_pos] + placeholder + redacted[match.end_pos :]

        logger.info(
            f"PII redaction: replaced {len(filtered)} matches in {file_name} "
            f"(tier: {result.privacy_tier.value})"
        )
        return redacted

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"PII redaction failed for {file_name}: {e}", exc_info=True)
        raise ProcessingError(f"PII redaction failed for {file_name}: {e}") from e


def _index_in_rag(text: str, file_name: str, metadata: dict, catalog_id: str = "") -> None:
    """Chunk, embed, and store document text in the LanceDB vector database.

    Delegates to IngestService for the full enrichment pipeline.
    """
    try:
        import asyncio

        import lancedb

        from src.embeddings.embedding_service import get_embedding_service
        from src.ingest_service import IngestService

        db = lancedb.connect(str(config.DB_PATH))
        embedder = get_embedding_service()
        service = IngestService(embedding_service=embedder, db=db)

        with asyncio.Runner() as runner:
            result = runner.run(
                service.ingest(
                    text,
                    metadata,
                    source_path=file_name,
                    skip_graph=True,
                    catalog_id=catalog_id,
                )
            )

        logger.info(
            f"RAG indexed via IngestService: {file_name} "
            f"({result.parent_chunks} parents, {result.child_chunks} children, "
            f"{result.skipped_dedup} deduped)"
        )

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"RAG indexing failed for {file_name}: {e}", exc_info=True)
        raise ProcessingError(f"RAG indexing failed: {e}", file_path=file_name) from e


def _extract_entities(text: str, file_name: str) -> None:
    """Extract entities and relationships from text, store in knowledge graph."""
    try:
        import asyncio

        from src.graph.knowledge_graph import EntityExtractor, KnowledgeGraph

        graph_db_path = Path(str(config.DB_PATH)).parent / "knowledge_graph.db"
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
        with asyncio.Runner() as runner:
            entities, relationships = runner.run(extractor.extract(text[:10000], document_id))

        if entities or relationships:
            graph.add_from_extraction(entities, relationships)
            via = "LLM" if llm else "patterns"
            logger.info(
                f"Knowledge graph: extracted {len(entities)} entities, "
                f"{len(relationships)} relationships from {file_name} (via {via})"
            )
        else:
            logger.info(f"Knowledge graph: no entities extracted from {file_name}")

    except ProcessingError:
        raise
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
        final_metadata.update(
            {
                "category": proposed.get("category"),
                "year": proposed.get("year"),
                "type": proposed.get("type"),
                "tags": proposed.get("tags", []),
            }
        )

        # Extract full text BEFORE archiving (archive moves the file)
        try:
            export_text = extract_text(current_path)
            if not export_text:
                logger.warning(
                    f"Text extraction returned empty for {current_path.name}, using staged text"
                )
                export_text = item["redacted_text"]
            else:
                logger.info(f"Extracted {len(export_text)} chars from {current_path.name}")
        except Exception as e:
            logger.warning(
                f"Text extraction failed for {current_path.name}: {e}, using staged text"
            )
            export_text = item["redacted_text"]

        # Compute doc_id from unredacted text (consistent ID for both databases)
        doc_id = hashlib.sha256(export_text[:5000].encode()).hexdigest()[:16]

        # If PII is flagged, redact the full text for both Obsidian and RAG.
        # The original file archives untouched, but exported content gets
        # actual PII values replaced with [REDACTED-TYPE] placeholders.
        is_sensitive = item.get("metadata", {}).get("is_sensitive", False)

        # Index in RESTRICTED RAG (unredacted) — before PII redaction
        if is_sensitive and not item.get("skip_restricted_rag", False):
            try:
                import asyncio

                import lancedb

                from src.embeddings.embedding_service import get_embedding_service
                from src.ingest_service import IngestService

                restricted_db = lancedb.connect(str(config.RESTRICTED_DB_PATH))
                restricted_embedder = get_embedding_service()
                restricted_service = IngestService(
                    embedding_service=restricted_embedder, db=restricted_db
                )

                with asyncio.Runner() as runner:
                    runner.run(
                        restricted_service.ingest(
                            export_text,  # Original unredacted text
                            final_metadata,
                            source_path=current_path.name,
                            skip_graph=True,
                            catalog_id=doc_id,
                        )
                    )

                logger.info(f"Restricted RAG indexed (unredacted): {current_path.name}")
            except Exception as e:
                logger.warning(f"Restricted RAG indexing failed (non-fatal): {e}")

        if is_sensitive:
            detection_overrides = item.get("metadata", {}).get("pii_detections", [])
            export_text = _redact_pii(
                export_text, current_path.name, detection_overrides=detection_overrides
            )
            logger.info(f"PII-redacted text will be used for exports of {current_path.name}")

        # Capture file size before archiving (file won't exist at original_path after move)
        try:
            _file_size = current_path.stat().st_size
        except OSError:
            _file_size = 0

        # Archive (moves original file to target folder — always unredacted)
        archive_to_target(current_path, target_folder)

        # Export to Obsidian vault (unless user opted out)
        if not item.get("skip_obsidian"):
            export_to_vault(export_text, final_metadata, current_path.name)
        else:
            logger.info(f"Skipping Obsidian export for {current_path.name} (user opted out)")

        # Index in RAG vector database (unless user opted out)
        # Create VersionManager once for both change-check and version tracking
        from src.utils.versioning import VersionManager

        vm = VersionManager()

        if not item.get("skip_rag"):
            # Check if document content has changed since last indexing
            try:
                if not vm.is_changed(doc_id, export_text):
                    logger.info(f"Content unchanged for {current_path.name}, skipping RAG re-index")
                else:
                    _index_in_rag(export_text, current_path.name, final_metadata, catalog_id=doc_id)
            except Exception as e:
                logger.warning(f"Version check failed for {current_path.name}, re-indexing: {e}")
                _index_in_rag(export_text, current_path.name, final_metadata, catalog_id=doc_id)
            # Extract entities for knowledge graph
            _extract_entities(export_text, current_path.name)
        else:
            logger.info(f"Skipping RAG indexing for {current_path.name} (user opted out)")

        # Track document version
        try:
            document_id = doc_id
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

        # NOTE: Status set to "completed" BEFORE catalog registration intentionally.
        # Catalog failure should not block a successful commit. If catalog registration
        # fails, the doc is still in RAG + archive + vault — just missing from the catalog.
        # The catalog can be rebuilt from LanceDB via scripts/rebuild_catalog.py.
        update_item(item_id, {"status": "completed"})

        # Post-commit integrity validation
        try:
            from src.quality.batch_validator import validate_commit

            validate_commit(
                source_path=current_path.name,
                skip_rag=item.get("skip_rag", False),
            )
        except Exception as e:
            logger.warning(f"Post-commit validation failed for {current_path.name}: {e}")

        # Register in document catalog
        try:
            from src.catalog.catalog_manager import CatalogManager, DocumentRecord, ExportRecord

            catalog = CatalogManager()
            file_size = _file_size

            doc_record = DocumentRecord(
                id=document_id,
                original_filename=original_path.name,
                original_path=str(original_path),
                archive_path=str(config.ARCHIVE_PATH / target_folder / current_path.name),
                main_rag_doc_id=document_id if not item.get("skip_rag") else None,
                restricted_rag_doc_id=(
                    document_id
                    if is_sensitive and not item.get("skip_restricted_rag", False)
                    else None
                ),
                category=final_metadata.get("category", ""),
                year=final_metadata.get("year", ""),
                tags=",".join(final_metadata.get("tags", [])),
                is_sensitive=is_sensitive,
                summary=final_metadata.get("summary", ""),
                file_type=original_path.suffix.lstrip("."),
                file_size=file_size,
            )
            catalog.register(doc_record)

            # Record exports
            catalog.record_export(
                ExportRecord(
                    document_id=document_id,
                    destination="archive",
                    path=str(config.ARCHIVE_PATH / target_folder / current_path.name),
                    redacted=False,
                )
            )
            if not item.get("skip_rag"):
                catalog.record_export(
                    ExportRecord(
                        document_id=document_id,
                        destination="main_rag",
                        path=document_id,
                        redacted=is_sensitive,
                    )
                )
            if is_sensitive and not item.get("skip_restricted_rag", False):
                catalog.record_export(
                    ExportRecord(
                        document_id=document_id,
                        destination="restricted_rag",
                        path=document_id,
                        redacted=False,
                    )
                )
            if not item.get("skip_obsidian"):
                catalog.record_export(
                    ExportRecord(
                        document_id=document_id,
                        destination="obsidian",
                        path=str(config.VAULT_PATH / "Ingested" / current_path.name),
                        redacted=True,
                    )
                )

            tag_count = len(final_metadata.get("tags", []))
            logger.info(f"Catalog: registered {current_path.name} with {tag_count} tags")
        except Exception as e:
            logger.warning(f"Catalog registration failed (non-fatal): {e}")

        return True

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"Execution failed for {item_id}: {e}")
        update_item(item_id, {"status": "error", "error": str(e)})
        raise ProcessingError(f"Execution failed: {e}", file_path=str(original_path)) from e
