"""Unified document ingestion service for CoreRag.

All paths that store content in LanceDB should route through this service
to ensure consistent enrichment (context prefixes, quality scores, source
authority, date extraction, content hash dedup, parent summaries).
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from src import config

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Result of an ingest operation."""

    document_id: str
    parent_chunks: int = 0
    child_chunks: int = 0
    skipped_dedup: int = 0
    source: str = ""


class IngestService:
    """Shared ingestion pipeline with configurable enrichment phases.

    Usage:
        service = IngestService(embedding_service=embedder, db=db)
        result = await service.ingest(text, metadata)
    """

    def __init__(self, embedding_service, db):
        self._embedder = embedding_service
        self._db = db

    async def ingest(
        self,
        text: str,
        metadata: dict,
        *,
        source_path: str = "api_ingest",
        skip_context: bool = False,
        skip_quality: bool = False,
        skip_graph: bool = False,
        skip_parents: bool = False,
    ) -> IngestResult:
        """Ingest text into LanceDB with configurable enrichment.

        The full pipeline (executor) calls with all defaults.
        API ingest may set skip_context=True for speed.
        Quick-capture sets skip_parents=True.
        """
        from src.chunking.parent_child import ParentChildChunker
        from src.utils.query_sanitize import build_eq_clause

        # Generate document ID (same as executor)
        document_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]

        # Chunk
        chunker = ParentChildChunker()
        parents, children = chunker.chunk_document(
            content=text,
            document_id=document_id,
            metadata={
                "source_path": source_path,
                "file_type": "document",
                "file_name": source_path,
                "category": metadata.get("category", ""),
                "year": metadata.get("year", ""),
            },
        )

        if not children:
            return IngestResult(document_id=document_id, source=source_path)

        # ── Content hash dedup ────────────────────────────────────────
        existing_hashes: set[str] = set()
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if "child_chunks" in self._db.table_names():
                    ct = self._db.open_table("child_chunks")
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

        # Compute hashes and dedup (ChildChunk has no content_hash attr)
        child_hashes = []
        deduped_children = []
        skipped = 0
        for c in children:
            h = hashlib.sha256(c.content.encode()).hexdigest()
            if h in existing_hashes:
                skipped += 1
                continue
            child_hashes.append(h)
            deduped_children.append(c)

        if not deduped_children:
            return IngestResult(document_id=document_id, source=source_path, skipped_dedup=skipped)

        children = deduped_children

        # ── Source authority ───────────────────────────────────────────
        source_authority = config.SOURCE_AUTHORITY_DEFAULT
        if not skip_quality:
            try:
                from src.classification.source_authority import SourceAuthorityClassifier

                source_authority = SourceAuthorityClassifier().classify(metadata).value
            except Exception:
                pass

        # ── Chunk quality scoring ─────────────────────────────────────
        quality_scores = [0.0] * len(children)
        if not skip_quality:
            try:
                from src.quality.chunk_scorer import ChunkScorer

                scorer = ChunkScorer()
                quality_scores = [scorer.score(c.content).overall for c in children]
            except Exception:
                pass

        # ── Date extraction ───────────────────────────────────────────
        date_extracted_list = [""] * len(children)
        date_confidence_list = [0.0] * len(children)
        if not skip_quality:
            try:
                from src.quality.date_extractor import DateExtractor

                date_ext = DateExtractor()
                for i, c in enumerate(children):
                    d, conf = date_ext.extract(c.content)
                    date_extracted_list[i] = d or ""  # Convert None to ""
                    date_confidence_list[i] = conf
            except Exception:
                pass

        # ── Contextual retrieval ──────────────────────────────────────
        context_prefixes = [""] * len(children)
        if not skip_context and config.CONTEXT_GENERATION:
            try:
                from src.chunking.context_generator import ContextGenerator

                ctx_gen = ContextGenerator()
                child_texts = [c.content for c in children]
                context_prefixes = await ctx_gen.generate_contexts_batch(
                    text, child_texts, concurrency=3
                )
            except Exception as e:
                logger.warning(f"Context generation failed: {e}")

        # ── Embed (context + content) ─────────────────────────────────
        embed_texts = []
        for c, ctx in zip(children, context_prefixes):
            embed_texts.append(f"{ctx}\n\n{c.content}" if ctx else c.content)
        embeddings = self._embedder.embed_documents(embed_texts, show_progress=False)

        # ── Parent summaries ──────────────────────────────────────────
        parent_summaries: dict[str, str] = {}
        if not skip_parents:
            try:
                from src.chunking.summarizer import MultiResolutionSummarizer

                summarizer = MultiResolutionSummarizer()
                for p in parents:
                    p_children = [c.content for c in children if c.parent_id == p.id]
                    try:
                        summary = await summarizer.summarize_parent(p.content, p_children)
                        parent_summaries[p.id] = summary
                    except Exception:
                        pass
            except Exception:
                pass

        # ── Build tags string ─────────────────────────────────────────
        raw_tags = metadata.get("tags", [])
        tags_str = "," + ",".join(raw_tags) + "," if isinstance(raw_tags, list) and raw_tags else ""

        # ── Build data dicts ──────────────────────────────────────────
        now_iso = datetime.now().isoformat()

        parent_data = []
        if not skip_parents:
            for p in parents:
                parent_data.append(
                    {
                        "id": p.id,
                        "document_id": p.document_id,
                        "content": p.content,
                        "source_path": source_path,
                        "section_title": p.section_title or "",
                        "token_count": p.token_count,
                        "created_at": now_iso,
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
                    "source_path": source_path,
                    "tags": tags_str,
                    "content_hash": child_hashes[i],
                    "context_prefix": context_prefixes[i],
                    "quality_score": quality_scores[i],
                    "source_authority": source_authority,
                    "date_extracted": date_extracted_list[i],
                    "date_confidence": date_confidence_list[i],
                }
            )

        # ── Write to LanceDB ─────────────────────────────────────────
        for table_name, data in [("parent_chunks", parent_data), ("child_chunks", child_data)]:
            if not data:
                continue
            try:
                tbl = self._db.open_table(table_name)
                tbl.add(data)
            except Exception:
                try:
                    self._db.create_table(table_name, data)
                except Exception:
                    tbl = self._db.open_table(table_name)
                    tbl.add(data)

        # ── Entity extraction (knowledge graph) ───────────────────────
        if not skip_graph:
            try:
                from src.graph.knowledge_graph import KnowledgeGraph

                graph_db_path = config.STATE_DIR / "knowledge_graph.db"
                if graph_db_path.exists():
                    graph = KnowledgeGraph(graph_db_path)

                    from src.graph.knowledge_graph import EntityExtractor

                    llm = None
                    try:
                        from src.utils.ollama_llm import OllamaLLM

                        llm = OllamaLLM()
                    except Exception:
                        pass

                    extractor = EntityExtractor(llm=llm)
                    entities, relationships = await extractor.extract(text[:10000], document_id)

                    if entities or relationships:
                        graph.add_from_extraction(entities, relationships)
                        via = "LLM" if llm else "patterns"
                        logger.info(
                            f"Knowledge graph: {len(entities)} entities, "
                            f"{len(relationships)} relationships ({via})"
                        )
            except Exception as e:
                logger.debug(f"Entity extraction skipped: {e}")

        logger.info(
            f"Ingested: {source_path} ({len(parent_data)} parents, {len(child_data)} children, "
            f"{skipped} deduped)"
        )

        return IngestResult(
            document_id=document_id,
            parent_chunks=len(parent_data),
            child_chunks=len(child_data),
            skipped_dedup=skipped,
            source=source_path,
        )
