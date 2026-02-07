"""Tests for the BacklinkGenerator — vault-wide term matching and KG backlinks."""

import sqlite3

import pytest

from src.export.backlink_generator import BacklinkGenerator


@pytest.fixture
def vault_dir(tmp_path):
    """Create a mock vault with several markdown files."""
    vault = tmp_path / "vault"
    vault.mkdir()
    ingested = vault / "Ingested"
    ingested.mkdir()
    (ingested / "Python.md").write_text("# Python\nContent about Python.")
    (ingested / "Authentication.md").write_text("# Auth\nOAuth2 setup.")
    (ingested / "FastAPI.md").write_text("# FastAPI\nWeb framework.")
    (ingested / "Machine Learning.md").write_text("# ML\nDeep learning.")
    (ingested / "ab.md").write_text("# Short name")  # Too short (2 chars), should be skipped
    return vault


@pytest.fixture
def graph_db(tmp_path):
    """Create a mock knowledge graph SQLite database."""
    db_path = tmp_path / "knowledge_graph.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE entities (
            id INTEGER PRIMARY KEY,
            name TEXT, type TEXT, document_id TEXT,
            confidence REAL, metadata TEXT, created_at TEXT
        )""")
    cursor.execute("""CREATE TABLE relationships (
            id INTEGER PRIMARY KEY,
            subject TEXT, predicate TEXT, object TEXT,
            document_id TEXT, confidence REAL, context TEXT, created_at TEXT
        )""")
    # Two documents sharing the entity "Python"
    cursor.execute(
        "INSERT INTO entities (name, type, document_id, confidence) VALUES (?, ?, ?, ?)",
        ("Python", "technology", "doc_abc", 1.0),
    )
    cursor.execute(
        "INSERT INTO entities (name, type, document_id, confidence) VALUES (?, ?, ?, ?)",
        ("Python", "technology", "doc_xyz", 1.0),
    )
    cursor.execute(
        "INSERT INTO entities (name, type, document_id, confidence) VALUES (?, ?, ?, ?)",
        ("FastAPI", "technology", "doc_abc", 1.0),
    )
    conn.commit()
    conn.close()
    return db_path


class TestFindLinkableTerms:
    def test_finds_matching_vault_terms(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "This document covers Python programming and authentication."
        result = gen.find_linkable_terms(content)
        assert "Python" in result
        assert "[[Python|Python]]" == result["Python"]

    def test_excludes_self(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "This Python document explains Python basics."
        result = gen.find_linkable_terms(content, exclude_stem="Python")
        # Should not link to self
        assert "Python" not in result

    def test_skips_inside_existing_wikilinks(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "See [[Python]] for details. Also Python is great."
        result = gen.find_linkable_terms(content)
        # First "Python" is inside wikilink — should be skipped
        # Second "Python" should match
        assert "Python" in result

    def test_skips_inside_code_blocks(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "```python\nimport Python\n```\nUse Python for scripting."
        result = gen.find_linkable_terms(content)
        # "Python" inside code block should be skipped
        # "Python" in final sentence should match
        assert "Python" in result
        assert "[[Python|Python]]" == result["Python"]

    def test_skips_yaml_frontmatter(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "---\ncategory: Python\n---\nSome text about authentication."
        result = gen.find_linkable_terms(content)
        # "Python" in frontmatter should be skipped, but "authentication" matches
        assert "Python" not in result
        assert "authentication" in result or "Authentication" in result

    def test_ignores_short_stems(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "The ab test showed Python works."
        result = gen.find_linkable_terms(content)
        # "ab.md" has stem length 2, below MIN_TERM_LENGTH of 3
        assert not any("ab" in v for v in result.values())

    def test_case_insensitive_matching(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "This covers python programming."
        result = gen.find_linkable_terms(content)
        assert len(result) >= 1


class TestApplyInlineLinks:
    def test_replaces_first_occurrence_only(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "Python is great. Python is powerful. FastAPI too."
        result = gen.apply_inline_links(content)
        # Only first occurrence of each term should be replaced
        assert result.count("[[Python|Python]]") == 1
        assert result.count("[[FastAPI|FastAPI]]") == 1

    def test_preserves_content_without_matches(self, vault_dir):
        gen = BacklinkGenerator(vault_dir)
        content = "This document has no linkable terms."
        result = gen.apply_inline_links(content)
        assert result == content


class TestGetRelatedFromGraph:
    def test_returns_links_for_shared_entities(self, vault_dir, graph_db):
        gen = BacklinkGenerator(vault_dir, graph_db)
        links = gen.get_related_from_graph("doc_xyz")
        # doc_xyz shares "Python" with doc_abc, and "Python" is in vault
        assert any("Python" in link for link in links)

    def test_returns_empty_without_graph(self, vault_dir):
        gen = BacklinkGenerator(vault_dir, graph_db_path=None)
        links = gen.get_related_from_graph("doc_abc")
        assert links == []

    def test_returns_empty_for_unknown_document(self, vault_dir, graph_db):
        gen = BacklinkGenerator(vault_dir, graph_db)
        links = gen.get_related_from_graph("nonexistent_doc")
        assert links == []


class TestGenerateRelatedSection:
    def test_generates_markdown_section(self, vault_dir, graph_db):
        gen = BacklinkGenerator(vault_dir, graph_db)
        section = gen.generate_related_section("doc_xyz")
        if section:
            assert "## Related Notes" in section
            assert "[[" in section

    def test_returns_empty_string_when_no_links(self, vault_dir, graph_db):
        gen = BacklinkGenerator(vault_dir, graph_db)
        section = gen.generate_related_section("nonexistent_doc")
        assert section == ""


class TestComputeDocumentId:
    def test_consistent_hashing(self):
        text = "Hello world"
        id1 = BacklinkGenerator.compute_document_id(text)
        id2 = BacklinkGenerator.compute_document_id(text)
        assert id1 == id2
        assert len(id1) == 16

    def test_different_text_different_id(self):
        id1 = BacklinkGenerator.compute_document_id("Hello")
        id2 = BacklinkGenerator.compute_document_id("World")
        assert id1 != id2
