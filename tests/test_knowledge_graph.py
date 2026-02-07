"""
Tests for the knowledge graph module (entity extraction + SQLite triple store).

Run with: pytest tests/test_knowledge_graph.py -v
"""

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
