"""Tests for MCP CoreRagTools class."""

import os
import sys
import tempfile
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

# Setup dummy env vars BEFORE importing src modules
os.environ.setdefault("INBOX_PATH", "/dummy/inbox")
os.environ.setdefault("VAULT_PATH", "/dummy/vault")
os.environ.setdefault("ARCHIVE_PATH", "/dummy/archive")
os.environ.setdefault("GOOGLE_API_KEY", "dummy_key")

from src.mcp_server.tools import CoreRagTools


@pytest.fixture
def mock_retriever():
    retriever = AsyncMock()
    retriever.search = AsyncMock(return_value=[
        {
            "content": "Test chunk content about Python programming.",
            "document_id": "doc_abc123",
            "score": 0.85,
            "rrf_score": 0.85,
            "metadata": {
                "source_path": "test_doc.md",
                "section_title": "Getting Started",
            },
        },
    ])
    return retriever


@pytest.fixture
def mock_embedder():
    async def embed(text):
        return [0.1] * 768
    return embed


@pytest.fixture
def mock_db():
    db = MagicMock()
    table = MagicMock()
    table.search.return_value = table
    table.where.return_value = table
    table.limit.return_value = table
    table.select.return_value = table
    table.to_list.return_value = [
        {
            "id": "chunk_1",
            "content": "Test content",
            "document_id": "doc_abc123",
            "vector": [0.1] * 768,
            "source_path": "test_doc.md",
            "section_title": "Intro",
            "metadata": "{}",
            "start_char": 0,
        },
    ]
    db.open_table.return_value = table
    return db


@pytest.fixture
def tools(mock_retriever, mock_embedder, mock_db):
    with tempfile.TemporaryDirectory() as td:
        yield CoreRagTools(
            retriever=mock_retriever,
            embedder=mock_embedder,
            db=mock_db,
            vault_root=Path(td),
        )


class TestSearchKnowledge:
    """Tests for the main search tool."""

    @pytest.mark.asyncio
    async def test_basic_search(self, tools, mock_retriever):
        result = await tools.search_knowledge(query="Python programming", k=5)
        assert "results" in result
        mock_retriever.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self, tools):
        result = await tools.search_knowledge(query="Python", k=5)
        results = result["results"]
        assert len(results) >= 1
        r = results[0]
        assert "content" in r
        assert "source_path" in r
        assert "score" in r
        assert "citation" in r

    @pytest.mark.asyncio
    async def test_search_with_semantic_cache(self, tools):
        cache = MagicMock()
        cache.get.return_value = [{"content": "cached", "score": 0.9}]
        tools._semantic_cache = cache

        result = await tools.search_knowledge(query="cached query")
        assert result.get("_cached") is True
        assert result["results"][0]["content"] == "cached"

    @pytest.mark.asyncio
    async def test_search_with_debug(self, tools):
        result = await tools.search_knowledge(query="test query", debug=True)
        assert "_debug" in result
        assert "retrieval_time_ms" in result["_debug"]
        assert "total_candidates" in result["_debug"]


class TestGetDocument:
    """Tests for document retrieval."""

    @pytest.mark.asyncio
    async def test_get_document_found(self, tools):
        result = await tools.get_document("doc_abc123")
        assert "content" in result
        assert result["document_id"] == "doc_abc123"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, tools, mock_db):
        empty_table = MagicMock()
        empty_table.search.return_value = empty_table
        empty_table.where.return_value = empty_table
        empty_table.to_list.return_value = []
        mock_db.open_table.return_value = empty_table

        result = await tools.get_document("nonexistent")
        assert "error" in result


class TestListRecentFiles:
    """Tests for recent file listing."""

    @pytest.mark.asyncio
    async def test_list_recent_files_empty(self, tools):
        result = await tools.list_recent_files(days=7)
        # Empty temp dir, should return empty
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_recent_files_with_files(self, tools):
        # Create a test file in vault_root
        test_file = tools.vault_root / "test_note.md"
        test_file.write_text("# Test Note")

        result = await tools.list_recent_files(days=7)
        assert len(result) >= 1
        assert result[0]["name"] == "test_note.md"

    @pytest.mark.asyncio
    async def test_list_recent_files_type_filter(self, tools):
        (tools.vault_root / "note.md").write_text("test")
        (tools.vault_root / "data.json").write_text("{}")

        result = await tools.list_recent_files(days=7, file_types=["md"])
        names = [r["name"] for r in result]
        assert "note.md" in names
        assert "data.json" not in names


class TestGetFolderStructure:
    """Tests for folder navigation."""

    @pytest.mark.asyncio
    async def test_get_folder_structure(self, tools):
        (tools.vault_root / "subdir").mkdir()
        (tools.vault_root / "subdir" / "note.md").write_text("test")

        result = await tools.get_folder_structure()
        assert result["type"] == "directory"
        assert len(result["children"]) >= 1

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tools):
        result = await tools.get_folder_structure(path="nonexistent")
        assert "error" in result


class TestSearchByEntity:
    """Tests for knowledge graph search."""

    @pytest.mark.asyncio
    async def test_no_graph_falls_back_to_semantic(self, tools):
        result = await tools.search_by_entity(entity_name="Python")
        assert result["graph_available"] is False
        assert result["fallback"] == "semantic_search"

    @pytest.mark.asyncio
    async def test_with_graph(self, tools):
        mock_graph = MagicMock()
        mock_graph.get_neighbors.return_value = [
            {"entity": "Django", "relationship": "uses", "direction": "outgoing",
             "document_id": "doc1", "confidence": 0.9},
        ]
        mock_graph.get_stats.return_value = {
            "total_entities": 100, "total_relationships": 50,
        }
        tools._knowledge_graph = mock_graph

        result = await tools.search_by_entity(entity_name="Python")
        assert result["entity_found"] is True
        assert "uses" in result["relationships"]


class TestDetectConflicts:
    """Tests for conflict detection tool."""

    @pytest.mark.asyncio
    async def test_no_detector_returns_error(self, tools):
        result = await tools.detect_conflicts()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_with_detector(self, tools):
        mock_detector = MagicMock()
        mock_report = MagicMock()
        mock_report.documents_analyzed = 10
        mock_report.conflicts_found = 2
        mock_report.by_type = {"numeric": 2}
        mock_report.by_severity = {"medium": 2}
        mock_report.conflicts = []
        mock_detector.scan_directory.return_value = mock_report
        tools._conflict_detector = mock_detector

        result = await tools.detect_conflicts()
        assert result["documents_analyzed"] == 10
        assert result["conflicts_found"] == 2
