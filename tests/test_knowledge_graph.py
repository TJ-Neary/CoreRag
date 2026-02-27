"""
Tests for the knowledge graph module (entity extraction + SQLite triple store).

Run with: pytest tests/test_knowledge_graph.py -v
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.graph.knowledge_graph import Entity, EntityExtractor, KnowledgeGraph, Relationship


class TestEntityExtractor:
    """Tests for regex-based entity extraction."""

    def test_extract_capitalized_entities(self):
        extractor = EntityExtractor()
        entities, rels = extractor._extract_with_patterns(
            "John Smith works at Google on the Python project.", "doc1"
        )
        names = [e.name for e in entities]
        assert len(entities) > 0
        assert any("John" in n or "Smith" in n or "Google" in n for n in names)

    def test_extract_relationships(self):
        extractor = EntityExtractor()
        entities, rels = extractor._extract_with_patterns(
            "Python uses NumPy. TensorFlow depends on Python.", "doc1"
        )
        assert isinstance(rels, list)

    def test_empty_text_returns_nothing(self):
        extractor = EntityExtractor()
        entities, rels = extractor._extract_with_patterns("", "doc1")
        assert entities == []
        assert rels == []

    def test_document_id_attached(self):
        extractor = EntityExtractor()
        entities, rels = extractor._extract_with_patterns(
            "Microsoft released Windows update.", "doc42"
        )
        for e in entities:
            assert e.document_id == "doc42"


class TestKnowledgeGraph:
    """Tests for the SQLite-backed knowledge graph."""

    @pytest.fixture
    def graph(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_graph.db"
            yield KnowledgeGraph(db_path)

    def test_add_entity(self, graph):
        entity = Entity(name="Python", type="technology", document_id="d1")
        graph.add_entity(entity)
        stats = graph.get_stats()
        assert stats["total_entities"] >= 1

    def test_add_relationship(self, graph):
        e1 = Entity(name="Python", type="technology", document_id="d1")
        e2 = Entity(name="NumPy", type="library", document_id="d1")
        graph.add_entity(e1)
        graph.add_entity(e2)

        rel = Relationship(
            subject="Python",
            predicate="uses",
            object="NumPy",
            document_id="d1",
            confidence=0.8,
        )
        graph.add_relationship(rel)
        stats = graph.get_stats()
        assert stats["total_relationships"] >= 1

    def test_get_neighbors(self, graph):
        e1 = Entity(name="Python", type="technology", document_id="d1")
        e2 = Entity(name="Django", type="framework", document_id="d1")
        graph.add_entity(e1)
        graph.add_entity(e2)

        rel = Relationship(
            subject="Python",
            predicate="has_framework",
            object="Django",
            document_id="d1",
            confidence=0.9,
        )
        graph.add_relationship(rel)

        neighbors = graph.get_neighbors("Python")
        assert len(neighbors) >= 1
        assert any(n["entity"] == "Django" for n in neighbors)

    def test_add_from_extraction(self, graph):
        entities = [
            Entity(name="React", type="framework", document_id="d2"),
            Entity(name="JavaScript", type="language", document_id="d2"),
        ]
        rels = [
            Relationship(
                subject="React",
                predicate="written_in",
                object="JavaScript",
                document_id="d2",
                confidence=0.95,
            ),
        ]
        graph.add_from_extraction(entities, rels)
        stats = graph.get_stats()
        assert stats["total_entities"] >= 2
        assert stats["total_relationships"] >= 1

    def test_get_stats_on_empty_graph(self, graph):
        stats = graph.get_stats()
        assert stats["total_entities"] == 0
        assert stats["total_relationships"] == 0


class TestBitemporalFeatures:
    """Tests for bitemporal entity/relationship tracking."""

    @pytest.fixture
    def graph(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_graph.db"
            yield KnowledgeGraph(db_path)

    def test_entity_mention_count_increments(self, graph):
        """Adding same entity twice increments mention_count."""
        e = Entity(name="Python", type="technology", document_id="d1")
        graph.add_entity(e)
        graph.add_entity(e)

        timeline = graph.get_entity_timeline("Python")
        assert len(timeline) == 1
        assert timeline[0]["mention_count"] == 2

    def test_entity_first_seen_preserved(self, graph):
        """First_seen stays at original value after re-add."""
        e = Entity(name="React", type="framework", document_id="d1")
        graph.add_entity(e)

        timeline = graph.get_entity_timeline("React")
        first_seen_1 = timeline[0]["first_seen"]

        graph.add_entity(e)
        timeline = graph.get_entity_timeline("React")
        assert timeline[0]["first_seen"] == first_seen_1

    def test_entity_timeline(self, graph):
        """Timeline shows entity across multiple documents."""
        graph.add_entity(Entity(name="Django", type="framework", document_id="d1"))
        graph.add_entity(Entity(name="Django", type="framework", document_id="d2"))

        timeline = graph.get_entity_timeline("Django")
        assert len(timeline) == 2
        doc_ids = [t["document_id"] for t in timeline]
        assert "d1" in doc_ids
        assert "d2" in doc_ids

    def test_search_entities_by_confidence(self, graph):
        """Search filters by minimum confidence."""
        graph.add_entity(
            Entity(name="StrongEntity", type="concept", document_id="d1", confidence=0.9)
        )
        graph.add_entity(
            Entity(name="WeakEntity", type="concept", document_id="d1", confidence=0.2)
        )

        results = graph.search_entities("Entity", min_confidence=0.5)
        names = [r["name"] for r in results]
        assert "StrongEntity" in names
        assert "WeakEntity" not in names

    def test_supersede_relationship(self, graph):
        """Superseding marks old relationship."""
        r1 = Relationship(subject="A", predicate="works_at", object="CompanyX", document_id="d1")
        graph.add_relationship(r1)

        r2 = Relationship(subject="A", predicate="works_at", object="CompanyY", document_id="d2")
        graph.add_relationship(r2)

        # Get IDs
        conn = sqlite3.connect(graph.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM relationships ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert len(ids) >= 2
        graph.supersede_relationship(ids[0], ids[1])

        # Verify superseded_by is set
        conn = sqlite3.connect(graph.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT superseded_by FROM relationships WHERE id = ?", (ids[0],))
        result = cursor.fetchone()
        conn.close()
        assert result[0] == ids[1]

    def test_confidence_decay(self, graph):
        """Confidence decay reduces stale entity scores."""
        from datetime import datetime, timedelta, timezone

        # Insert entity with old last_seen
        conn = sqlite3.connect(graph.db_path)
        cursor = conn.cursor()
        old_date = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
        cursor.execute(
            """
            INSERT INTO entities (name, type, document_id, confidence,
                                  first_seen, last_seen, mention_count, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            ("OldEntity", "concept", "d1", 1.0, old_date, old_date, 1, 1.0),
        )
        conn.commit()
        conn.close()

        updated = graph.apply_confidence_decay(half_life_days=365)
        assert updated >= 1

        timeline = graph.get_entity_timeline("OldEntity")
        assert timeline[0]["confidence_score"] < 0.5  # 2 years old, half_life=1yr → ~0.25

    def test_relationship_when_true(self, graph):
        """when_true is stored on relationships."""
        r = Relationship(subject="X", predicate="employed_at", object="Y", document_id="d1")
        graph.add_relationship(r, when_true="2024-01")

        conn = sqlite3.connect(graph.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT when_true FROM relationships WHERE subject = 'X'")
        result = cursor.fetchone()
        conn.close()
        assert result[0] == "2024-01"
