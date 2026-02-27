"""
Tests for LanceDB schema extensions (Phase 0).

Verifies that new fields have correct types and defaults, and that
existing data patterns remain backward-compatible.
"""

import pyarrow as pa
import pytest

from src.chunking.parent_child import create_parent_child_tables


class TestParentSchema:
    """Verify parent_chunks schema has new fields."""

    def test_schema_has_content_hash(self, tmp_lancedb):
        parent_t, _ = create_parent_child_tables(tmp_lancedb)
        schema = parent_t.schema
        assert "content_hash" in schema.names
        assert schema.field("content_hash").type == pa.string()

    def test_schema_has_summary(self, tmp_lancedb):
        parent_t, _ = create_parent_child_tables(tmp_lancedb)
        schema = parent_t.schema
        assert "summary" in schema.names
        assert schema.field("summary").type == pa.string()


class TestChildSchema:
    """Verify child_chunks schema has new fields."""

    def test_schema_has_content_hash(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "content_hash" in schema.names

    def test_schema_has_context_prefix(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "context_prefix" in schema.names
        assert schema.field("context_prefix").type == pa.string()

    def test_schema_has_quality_score(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "quality_score" in schema.names
        assert schema.field("quality_score").type == pa.float32()

    def test_schema_has_source_authority(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "source_authority" in schema.names

    def test_schema_has_date_extracted(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "date_extracted" in schema.names

    def test_schema_has_date_confidence(self, tmp_lancedb):
        _, child_t = create_parent_child_tables(tmp_lancedb)
        schema = child_t.schema
        assert "date_confidence" in schema.names
        assert schema.field("date_confidence").type == pa.float32()


class TestBackwardCompatibility:
    """Verify data written with new fields doesn't break existing patterns."""

    def test_parent_data_with_defaults(self, tmp_lancedb):
        """New parent fields default to empty string."""
        parent_t, _ = create_parent_child_tables(tmp_lancedb)
        parent_t.add(
            [
                {
                    "id": "p1",
                    "document_id": "d1",
                    "content": "test content",
                    "section_title": "",
                    "start_char": 0,
                    "end_char": 12,
                    "token_count": 3,
                    "metadata": "{}",
                    "content_hash": "",
                    "summary": "",
                }
            ]
        )
        rows = parent_t.search().limit(1).to_list()
        assert len(rows) == 1
        assert rows[0]["content_hash"] == ""
        assert rows[0]["summary"] == ""

    def test_child_data_with_defaults(self, tmp_lancedb):
        """New child fields default to empty/0.0."""
        from src.config import EMBEDDING_DIMENSIONS

        _, child_t = create_parent_child_tables(tmp_lancedb)
        child_t.add(
            [
                {
                    "id": "c1",
                    "parent_id": "p1",
                    "document_id": "d1",
                    "content": "test chunk",
                    "vector": [0.0] * EMBEDDING_DIMENSIONS,
                    "start_char": 0,
                    "end_char": 10,
                    "chunk_index": 0,
                    "content_hash": "",
                    "context_prefix": "",
                    "quality_score": 0.0,
                    "source_authority": "unknown",
                    "date_extracted": "",
                    "date_confidence": 0.0,
                }
            ]
        )
        rows = child_t.search().limit(1).to_list()
        assert len(rows) == 1
        assert rows[0]["content_hash"] == ""
        assert rows[0]["context_prefix"] == ""
        assert rows[0]["quality_score"] == pytest.approx(0.0)
        assert rows[0]["source_authority"] == "unknown"


@pytest.fixture
def tmp_lancedb(tmp_path):
    """Create a temporary LanceDB connection."""
    import lancedb

    return lancedb.connect(str(tmp_path / "test.lancedb"))
