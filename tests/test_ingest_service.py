"""Tests for IngestService — the unified ingestion pipeline.

Covers src/ingest_service.py:
  - Basic text ingestion (chunking → embedding → LanceDB write)
  - Content hash deduplication (skip unchanged, re-index changed)
  - Parent-child hierarchy
  - Table creation on first run
  - Metadata preservation (tags, category, document_id)
  - Error handling (empty text, DB errors)
  - Quality scoring gate (chunks below threshold excluded)
  - skip_* flags (skip_context, skip_quality, skip_parents, skip_graph)

Mocking strategy:
  - EmbeddingService: returns deterministic fake 1024d vectors
  - lancedb DB: MagicMock controlling table_names / open_table / create_table
  - Optional enrichment modules (ContextGenerator, ChunkScorer, etc.) are
    patched out to keep tests fast and isolated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingest_service import IngestResult, IngestService


# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_VECTOR = [0.01] * 1024


def _make_embedder(batch_size: int = 1) -> MagicMock:
    """Return a mock EmbeddingService whose embed_documents returns fake vectors."""
    embedder = MagicMock()
    embedder.embed_documents.side_effect = lambda texts, **kw: [FAKE_VECTOR] * len(texts)
    embedder.embed_query.return_value = FAKE_VECTOR
    return embedder


def _make_db(table_names: list[str] | None = None) -> MagicMock:
    """Return a mock LanceDB connection."""
    db = MagicMock()
    db.table_names.return_value = table_names or []

    mock_table = MagicMock()
    mock_table.search.return_value = mock_table
    mock_table.where.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.to_list.return_value = []
    mock_table.add.return_value = None

    db.open_table.return_value = mock_table
    db.create_table.return_value = mock_table
    return db


SAMPLE_TEXT = (
    "This is a sample document used for testing the ingestion pipeline. "
    "It contains enough content to be chunked and embedded. "
    "The pipeline should produce at least one parent chunk and one child chunk. "
    "Additional sentences ensure the chunker has sufficient material to work with. "
    "CoreRag stores knowledge in LanceDB with parent-child hierarchy for retrieval."
) * 3  # repeat to ensure we exceed minimum chunk size


@pytest.fixture()
def embedder() -> MagicMock:
    return _make_embedder()


@pytest.fixture()
def db() -> MagicMock:
    return _make_db()


@pytest.fixture()
def service(embedder: MagicMock, db: MagicMock) -> IngestService:
    return IngestService(embedding_service=embedder, db=db)


# ── IngestResult dataclass ─────────────────────────────────────────────────────


def test_ingest_result_defaults():
    result = IngestResult(document_id="abc123")
    assert result.document_id == "abc123"
    assert result.parent_chunks == 0
    assert result.child_chunks == 0
    assert result.skipped_dedup == 0
    assert result.source == ""


def test_ingest_result_with_all_fields():
    result = IngestResult(
        document_id="xyz",
        parent_chunks=2,
        child_chunks=5,
        skipped_dedup=1,
        source="test_source",
    )
    assert result.parent_chunks == 2
    assert result.child_chunks == 5
    assert result.skipped_dedup == 1
    assert result.source == "test_source"


# ── Basic ingestion ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_basic_ingest_returns_result(service: IngestService):
    """Ingest should return an IngestResult with at least one chunk."""
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_parents=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)
    assert result.document_id  # non-empty
    assert result.child_chunks > 0


@pytest.mark.asyncio
async def test_ingest_produces_consistent_document_id(service: IngestService):
    """Same text → same document_id (deterministic SHA256 hash)."""
    r1 = await service.ingest(
        SAMPLE_TEXT, metadata={}, skip_context=True, skip_quality=True, skip_graph=True
    )
    r2 = await service.ingest(
        SAMPLE_TEXT, metadata={}, skip_context=True, skip_quality=True, skip_graph=True
    )
    assert r1.document_id == r2.document_id


@pytest.mark.asyncio
async def test_ingest_different_texts_different_ids(service: IngestService):
    """Different text → different document_id."""
    r1 = await service.ingest(
        SAMPLE_TEXT, metadata={}, skip_context=True, skip_quality=True, skip_graph=True
    )
    r2 = await service.ingest(
        SAMPLE_TEXT + " extra content to change the hash",
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert r1.document_id != r2.document_id


@pytest.mark.asyncio
async def test_ingest_source_path_recorded(service: IngestService):
    """source_path is recorded in the IngestResult.source field."""
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        source_path="my_source_file.pdf",
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert result.source == "my_source_file.pdf"


# ── Empty / short text ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_text_returns_zero_chunks(service: IngestService):
    """Empty text produces no chunks and an IngestResult with zeros."""
    result = await service.ingest(
        "",
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)
    assert result.child_chunks == 0


@pytest.mark.asyncio
async def test_very_short_text_handled_gracefully(service: IngestService):
    """Very short text (below chunk size) should not raise."""
    result = await service.ingest(
        "Hi.",
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)


# ── Content hash deduplication ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_skips_unchanged_content(embedder: MagicMock):
    """Second ingest of identical text skips all chunks (already indexed)."""
    db = _make_db(table_names=["child_chunks", "parent_chunks"])

    # Simulate that the DB already has the exact chunks by returning matching hashes.
    # We need to compute the hash of the first child chunk content BEFORE calling ingest,
    # so we patch ParentChildChunker to use predictable content.
    mock_child = MagicMock()
    mock_child.id = "child-dedup-1"
    mock_child.parent_id = "parent-dedup-1"
    mock_child.document_id = "doc-dedup"
    mock_child.content = "Dedup test content repeated enough times. " * 20
    mock_child.chunk_index = 0

    mock_parent = MagicMock()
    mock_parent.id = "parent-dedup-1"
    mock_parent.document_id = "doc-dedup"
    mock_parent.content = mock_child.content
    mock_parent.section_title = ""
    mock_parent.token_count = 200

    content_hash = hashlib.sha256(mock_child.content.encode()).hexdigest()
    document_id = hashlib.sha256(
        (mock_child.content * 20)[:5000].encode()
    ).hexdigest()[:16]

    # Make the table return the existing hash
    mock_table = db.open_table.return_value
    mock_table.to_list.return_value = [{"content_hash": content_hash, "document_id": document_id}]

    with patch("src.ingest_service.ParentChildChunker") as MockChunker:
        MockChunker.return_value.chunk_document.return_value = ([mock_parent], [mock_child])
        service = IngestService(embedding_service=embedder, db=db)
        result = await service.ingest(
            mock_child.content * 20,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )

    # All chunks were deduped
    assert result.skipped_dedup >= 1
    assert result.child_chunks == 0


@pytest.mark.asyncio
async def test_changed_content_reindexed(embedder: MagicMock):
    """Ingest with different content hash writes new chunks even if document_id exists."""
    db = _make_db(table_names=["child_chunks", "parent_chunks"])

    mock_child = MagicMock()
    mock_child.id = "child-new-1"
    mock_child.parent_id = "parent-new-1"
    mock_child.document_id = "doc-new"
    mock_child.content = "Updated content different from what was stored before. " * 10
    mock_child.chunk_index = 0

    mock_parent = MagicMock()
    mock_parent.id = "parent-new-1"
    mock_parent.document_id = "doc-new"
    mock_parent.content = mock_child.content
    mock_parent.section_title = ""
    mock_parent.token_count = 150

    # Return an old hash — mismatch means new content should be indexed
    old_hash = hashlib.sha256(b"old content").hexdigest()
    mock_table = db.open_table.return_value
    mock_table.to_list.return_value = [{"content_hash": old_hash, "document_id": "doc-new"}]

    with patch("src.ingest_service.ParentChildChunker") as MockChunker:
        MockChunker.return_value.chunk_document.return_value = ([mock_parent], [mock_child])
        service = IngestService(embedding_service=embedder, db=db)
        result = await service.ingest(
            mock_child.content,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )

    assert result.child_chunks == 1
    assert result.skipped_dedup == 0


@pytest.mark.asyncio
async def test_dedup_graceful_on_missing_table(embedder: MagicMock):
    """When child_chunks table doesn't exist yet, dedup is skipped (no exception)."""
    db = _make_db(table_names=[])  # No tables
    service = IngestService(embedding_service=embedder, db=db)

    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)
    assert result.child_chunks > 0  # All chunks written (no dedup)


# ── Parent-child hierarchy ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parent_chunks_created(service: IngestService, db: MagicMock):
    """With skip_parents=False, parent data is written alongside child data."""
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=False,
    )
    assert result.parent_chunks > 0
    assert result.child_chunks > 0


@pytest.mark.asyncio
async def test_skip_parents_omits_parent_writes(service: IngestService, db: MagicMock):
    """With skip_parents=True, parent table is not written."""
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )
    # Parent chunks count should be 0 when skipped
    assert result.parent_chunks == 0
    # But children still ingested
    assert result.child_chunks > 0


# ── Table creation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creates_table_when_missing(embedder: MagicMock):
    """If open_table raises, service falls back to create_table."""
    db = _make_db(table_names=[])
    db.open_table.side_effect = Exception("Table not found")

    service = IngestService(embedding_service=embedder, db=db)
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    # create_table should have been called at least once
    assert db.create_table.called
    assert result.child_chunks > 0


@pytest.mark.asyncio
async def test_falls_back_to_open_table_after_create_conflict(embedder: MagicMock):
    """If create_table also raises, service tries open_table again."""
    db = _make_db(table_names=[])
    call_count = {"open": 0}

    def open_side_effect(name: str):
        call_count["open"] += 1
        if call_count["open"] == 1:
            raise Exception("Table not found")
        return MagicMock(add=MagicMock(), to_list=MagicMock(return_value=[]))

    db.open_table.side_effect = open_side_effect
    db.create_table.side_effect = Exception("Table exists")

    service = IngestService(embedding_service=embedder, db=db)
    # Should not raise even with table creation conflict
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)


# ── Metadata preservation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tags_formatted_correctly(embedder: MagicMock):
    """Tags are stored as comma-wrapped string: ,tag1,tag2,"""
    db = _make_db()
    written_data: list = []

    def capture_add(data: list):
        written_data.extend(data)

    mock_table = db.open_table.return_value
    mock_table.add.side_effect = capture_add

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={"tags": ["study", "rag"]},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows, "No child chunk rows captured"
    tags = child_rows[0]["tags"]
    assert tags == ",study,rag,"


@pytest.mark.asyncio
async def test_empty_tags_produces_empty_string(embedder: MagicMock):
    """Empty tags list produces an empty tags string."""
    db = _make_db()
    written_data: list = []

    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={"tags": []},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    assert child_rows[0]["tags"] == ""


@pytest.mark.asyncio
async def test_catalog_id_propagated(embedder: MagicMock):
    """catalog_id is written to all child chunk rows."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        catalog_id="cat-abc-123",
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    for row in child_rows:
        assert row["catalog_id"] == "cat-abc-123"


@pytest.mark.asyncio
async def test_document_id_in_child_rows(embedder: MagicMock):
    """All child rows share the same document_id derived from the text."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    doc_ids = {r["document_id"] for r in child_rows}
    assert len(doc_ids) == 1
    assert result.document_id in doc_ids


# ── Skip flags ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_context_skips_context_generation(service: IngestService):
    """skip_context=True should never call ContextGenerator."""
    with patch("src.chunking.context_generator.ContextGenerator") as MockCtx:
        result = await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )
    MockCtx.assert_not_called()
    assert result.child_chunks > 0


@pytest.mark.asyncio
async def test_skip_graph_skips_entity_extraction(service: IngestService):
    """skip_graph=True should not attempt knowledge graph extraction."""
    with patch("src.graph.knowledge_graph.KnowledgeGraph") as MockGraph:
        result = await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )
    MockGraph.assert_not_called()
    assert result.child_chunks > 0


@pytest.mark.asyncio
async def test_skip_quality_skips_chunk_scorer(service: IngestService):
    """skip_quality=True should not call ChunkScorer."""
    with patch("src.quality.chunk_scorer.ChunkScorer") as MockScorer:
        result = await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )
    MockScorer.assert_not_called()
    assert result.child_chunks > 0


# ── Embedding integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embedder_called_with_child_texts(embedder: MagicMock, db: MagicMock):
    """embed_documents is called once with all child texts."""
    service = IngestService(embedding_service=embedder, db=db)
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )
    assert embedder.embed_documents.called
    call_args = embedder.embed_documents.call_args
    texts_passed = call_args[0][0]
    assert len(texts_passed) == result.child_chunks


@pytest.mark.asyncio
async def test_sparse_vector_field_present(embedder: MagicMock):
    """Each child row must have a sparse_vector field (even if empty dict)."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    for row in child_rows:
        assert "sparse_vector" in row


@pytest.mark.asyncio
async def test_embed_with_sparse_used_when_available():
    """If embedder has embed_with_sparse, it is preferred over embed_documents."""
    embedder = MagicMock()
    embedder.embed_with_sparse.return_value = ([FAKE_VECTOR], [{"token1": 0.5}])
    # embed_documents should NOT be called
    embedder.embed_documents = MagicMock()

    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    assert embedder.embed_with_sparse.called
    embedder.embed_documents.assert_not_called()

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    # sparse_vector should be the dict returned by embed_with_sparse
    assert child_rows[0]["sparse_vector"] == {"token1": 0.5}


# ── Error handling ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_write_error_does_not_propagate_as_exception():
    """DB failures during write are handled gracefully (logged, not raised)."""
    embedder = _make_embedder()
    db = _make_db()
    db.open_table.side_effect = Exception("DB unavailable")
    db.create_table.side_effect = Exception("DB unavailable")

    service = IngestService(embedding_service=embedder, db=db)
    # Should not raise — the pipeline handles DB errors internally
    result = await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
    )
    assert isinstance(result, IngestResult)


@pytest.mark.asyncio
async def test_embedding_error_propagates():
    """If embedder.embed_documents raises, the error propagates (caller must handle)."""
    embedder = MagicMock()
    embedder.embed_documents.side_effect = RuntimeError("Embedding model not loaded")
    db = _make_db()

    service = IngestService(embedding_service=embedder, db=db)
    with pytest.raises(RuntimeError, match="Embedding model not loaded"):
        await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=True,
            skip_quality=True,
            skip_graph=True,
        )


# ── Quality scoring ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quality_scores_stored_in_child_rows(embedder: MagicMock):
    """When skip_quality=False, quality_score field is set on each child row."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    mock_score = MagicMock()
    mock_score.overall = 0.75

    mock_scorer = MagicMock()
    mock_scorer.score.return_value = mock_score

    service = IngestService(embedding_service=embedder, db=db)
    with patch("src.quality.chunk_scorer.ChunkScorer", return_value=mock_scorer):
        await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=True,
            skip_quality=False,
            skip_graph=True,
            skip_parents=True,
        )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    for row in child_rows:
        assert "quality_score" in row
        # Scorer was mocked to return 0.75
        assert row["quality_score"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_quality_score_default_zero_when_skipped(embedder: MagicMock):
    """With skip_quality=True, quality_score defaults to 0.0."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    for row in child_rows:
        assert row["quality_score"] == 0.0


# ── Context prefix ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_prefix_empty_when_skipped(embedder: MagicMock):
    """With skip_context=True, context_prefix should be empty string."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    service = IngestService(embedding_service=embedder, db=db)
    await service.ingest(
        SAMPLE_TEXT,
        metadata={},
        skip_context=True,
        skip_quality=True,
        skip_graph=True,
        skip_parents=True,
    )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    for row in child_rows:
        assert row["context_prefix"] == ""


@pytest.mark.asyncio
async def test_context_prefix_set_when_context_generation_enabled(embedder: MagicMock):
    """With skip_context=False, context_prefix comes from ContextGenerator."""
    db = _make_db()
    written_data: list = []
    mock_table = db.open_table.return_value
    mock_table.add.side_effect = lambda data: written_data.extend(data)

    mock_ctx_gen = MagicMock()
    mock_ctx_gen.generate_contexts_batch = AsyncMock(return_value=["Context: test"] * 10)

    service = IngestService(embedding_service=embedder, db=db)
    with patch("src.chunking.context_generator.ContextGenerator", return_value=mock_ctx_gen), patch(
        "src.config.CONTEXT_GENERATION", True
    ):
        await service.ingest(
            SAMPLE_TEXT,
            metadata={},
            skip_context=False,
            skip_quality=True,
            skip_graph=True,
            skip_parents=True,
        )

    child_rows = [r for r in written_data if "vector" in r]
    assert child_rows
    # At least one row should have a non-empty context prefix
    has_prefix = any(row.get("context_prefix") for row in child_rows)
    assert has_prefix
