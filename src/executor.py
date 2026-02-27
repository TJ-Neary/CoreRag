import hashlib
import logging
from datetime import datetime
from pathlib import Path

from src import config
from src.archiver import archive_to_target
from src.correction_log import log_correction
from src.exceptions import ProcessingError
from src.exporter import export_to_vault
from src.extractor import extract_text
from src.staging import get_item, update_item

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
        return text  # Fall back to original text rather than blocking


def _index_in_rag(text: str, file_name: str, metadata: dict) -> None:
    """Chunk, embed, and store document text in the LanceDB vector database.

    Enhanced pipeline:
    1. Chunk document into parents + children
    2. Content hash dedup — skip chunks already in the DB
    3. Contextual Retrieval — prepend LLM context to each chunk before embedding
    4. Quality scoring — heuristic score per chunk
    5. Source authority classification
    6. Date extraction from chunk text
    7. Multi-resolution parent summaries
    8. Embed (context_prefix + chunk_text) for richer vectors
    9. Store with all enrichment fields
    """
    try:
        import asyncio

        import lancedb

        from src.chunking.parent_child import ParentChildChunker
        from src.embeddings.embedding_service import create_embedding_service

        db_path = str(config.DB_PATH)
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

        # ── Content hash dedup ──────────────────────────────────────────
        existing_hashes: set[str] = set()
        try:
            if "child_chunks" in db.table_names():
                ct = db.open_table("child_chunks")
                from src.utils.query_sanitize import build_eq_clause

                existing = (
                    ct.search()
                    .where(build_eq_clause("document_id", document_id))
                    .limit(10000)
                    .to_list()
                )
                existing_hashes = {
                    r.get("content_hash", "") for r in existing if r.get("content_hash")
                }
        except Exception:
            pass  # First run, no table yet

        child_hashes = []
        deduped_children = []
        for c in children:
            h = hashlib.sha256(c.content.encode()).hexdigest()
            if h in existing_hashes:
                logger.debug(f"Dedup: skipping chunk {c.id} (hash exists)")
                continue
            child_hashes.append(h)
            deduped_children.append(c)

        if not deduped_children:
            logger.info(f"RAG indexing: all chunks already indexed for {file_name}")
            return

        children = deduped_children

        # ── Source authority ─────────────────────────────────────────────
        source_authority = config.SOURCE_AUTHORITY_DEFAULT
        try:
            from src.classification.source_authority import SourceAuthorityClassifier

            sa_classifier = SourceAuthorityClassifier()
            source_authority = sa_classifier.classify(metadata).value
        except Exception as e:
            logger.debug(f"Source authority classification failed: {e}")

        # ── Chunk quality scoring ────────────────────────────────────────
        quality_scores = []
        try:
            from src.quality.chunk_scorer import ChunkScorer

            scorer = ChunkScorer()
            for c in children:
                score = scorer.score(c.content)
                quality_scores.append(score.overall)
        except Exception:
            quality_scores = [0.0] * len(children)

        # ── Date extraction ──────────────────────────────────────────────
        date_extracted_list: list[str] = []
        date_confidence_list: list[float] = []
        try:
            from src.quality.date_extractor import DateExtractor

            date_ext = DateExtractor()
            for c in children:
                d, conf = date_ext.extract(c.content)
                date_extracted_list.append(d or "")
                date_confidence_list.append(conf)
        except Exception:
            date_extracted_list = [""] * len(children)
            date_confidence_list = [0.0] * len(children)

        # ── Contextual Retrieval ─────────────────────────────────────────
        context_prefixes: list[str] = [""] * len(children)
        if config.CONTEXT_GENERATION:
            try:
                from src.chunking.context_generator import ContextGenerator

                ctx_gen = ContextGenerator()
                child_texts_for_ctx = [c.content for c in children]

                loop = asyncio.new_event_loop()
                try:
                    context_prefixes = loop.run_until_complete(
                        ctx_gen.generate_contexts_batch(text, child_texts_for_ctx, concurrency=3)
                    )
                finally:
                    loop.close()

                ctx_count = sum(1 for cp in context_prefixes if cp)
                logger.info(f"Context generated for {ctx_count}/{len(children)} chunks")
            except Exception as e:
                logger.warning(f"Context generation failed, proceeding without: {e}")

        # ── Embed (context_prefix + chunk_text) ─────────────────────────
        embed_texts = []
        for c, ctx in zip(children, context_prefixes):
            if ctx:
                embed_texts.append(ctx + "\n\n" + c.content)
            else:
                embed_texts.append(c.content)

        embeddings = embedder.embed_documents(embed_texts, show_progress=False)

        # ── Parent summaries ─────────────────────────────────────────────
        parent_summaries: dict[str, str] = {}
        try:
            from src.chunking.summarizer import MultiResolutionSummarizer

            summarizer = MultiResolutionSummarizer()
            for p in parents:
                p_children = [c.content for c in children if c.parent_id == p.id]
                loop = asyncio.new_event_loop()
                try:
                    summary = loop.run_until_complete(
                        summarizer.summarize_parent(p.content, p_children)
                    )
                    parent_summaries[p.id] = summary
                finally:
                    loop.close()
        except Exception as e:
            logger.debug(f"Parent summary generation skipped: {e}")

        # ── Build comma-delimited tags string ────────────────────────────
        raw_tags = metadata.get("tags", [])
        if isinstance(raw_tags, list) and raw_tags:
            tags_str = "," + ",".join(raw_tags) + ","
        else:
            tags_str = ""

        parent_data = []
        for p in parents:
            parent_data.append(
                {
                    "id": p.id,
                    "document_id": p.document_id,
                    "content": p.content,
                    "source_path": file_name,
                    "section_title": p.section_title or "",
                    "token_count": p.token_count,
                    "created_at": datetime.now().isoformat(),
                    "tags": tags_str,
                    "content_hash": hashlib.sha256(p.content.encode()).hexdigest(),
                    "summary": parent_summaries.get(p.id, ""),
                }
            )

        child_data = []
        for i, (c, emb) in enumerate(zip(children, embeddings)):
            child_data.append(
                {
                    "id": c.id,
                    "parent_id": c.parent_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "vector": emb,
                    "chunk_index": c.chunk_index,
                    "source_path": file_name,
                    "tags": tags_str,
                    "content_hash": child_hashes[i],
                    "context_prefix": context_prefixes[i],
                    "quality_score": quality_scores[i],
                    "source_authority": source_authority,
                    "date_extracted": date_extracted_list[i],
                    "date_confidence": date_confidence_list[i],
                }
            )

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

        low_quality = sum(1 for q in quality_scores if q < config.CHUNK_QUALITY_THRESHOLD)
        logger.info(
            f"RAG indexed: {file_name} ({len(parents)} parents, {len(children)} children, "
            f"{low_quality} low-quality, authority={source_authority})"
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
            # Check if document content has changed since last indexing
            doc_id = hashlib.sha256(export_text[:5000].encode()).hexdigest()[:16]
            try:
                from src.utils.versioning import VersionManager

                _vm_check = VersionManager()
                if not _vm_check.is_changed(doc_id, export_text):
                    logger.info(f"Content unchanged for {current_path.name}, skipping RAG re-index")
                else:
                    _index_in_rag(export_text, current_path.name, final_metadata)
            except Exception:
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

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"Execution failed for {item_id}: {e}")
        update_item(item_id, {"status": "error", "error": str(e)})
        raise ProcessingError(f"Execution failed: {e}", file_path=str(original_path)) from e
