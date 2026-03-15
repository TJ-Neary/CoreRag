"""
Centralized test fixtures for CoreRag tests.

This conftest.py provides shared fixtures used across multiple test files,
reducing duplication and ensuring consistent test setup.

Usage:
    Fixtures are automatically available to all test files in the tests/ directory.
    Simply use the fixture name as a parameter in your test function.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Environment Setup
# =============================================================================
# Set dummy environment variables BEFORE any src imports
# This ensures tests don't accidentally use real paths

os.environ.setdefault("INBOX_PATH", "/tmp/corerag_test/inbox")
os.environ.setdefault("VAULT_PATH", "/tmp/corerag_test/vault")
os.environ.setdefault("ARCHIVE_PATH", "/tmp/corerag_test/archive")
os.environ.setdefault("GOOGLE_API_KEY", "test_api_key_not_real")
os.environ.setdefault("CORERAG_API_KEY", "test_api_key_not_real")


# =============================================================================
# Path Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory(prefix="corerag_test_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_inbox(temp_dir: Path) -> Path:
    """Provide a temporary inbox directory."""
    inbox = temp_dir / "inbox"
    inbox.mkdir()
    return inbox


@pytest.fixture
def temp_vault(temp_dir: Path) -> Path:
    """Provide a temporary vault directory."""
    vault = temp_dir / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def temp_archive(temp_dir: Path) -> Path:
    """Provide a temporary archive directory."""
    archive = temp_dir / "archive"
    archive.mkdir()
    return archive


@pytest.fixture
def temp_state_dir(temp_dir: Path) -> Path:
    """Provide a temporary state directory for staging, checkpoints, etc."""
    state = temp_dir / "state"
    state.mkdir()
    return state


@pytest.fixture
def temp_manifest(temp_state_dir: Path) -> Path:
    """Provide a path for a temporary staging manifest."""
    return temp_state_dir / "staging_manifest.json"


# =============================================================================
# Sample Document Fixtures
# =============================================================================


@pytest.fixture
def sample_text_file(temp_inbox: Path) -> Path:
    """Create a sample text file in the inbox."""
    file_path = temp_inbox / "sample_document.txt"
    file_path.write_text(
        "This is a sample document for testing purposes.\n"
        "It contains multiple lines of text.\n"
        "No sensitive information here."
    )
    return file_path


@pytest.fixture
def sample_sensitive_file(temp_inbox: Path) -> Path:
    """Create a sample file with mock PII for testing detection."""
    file_path = temp_inbox / "sensitive_document.txt"
    file_path.write_text(
        "Employee Record\n"
        "Name: John Doe\n"
        "Email: john.doe@example.com\n"
        "SSN: 123-45-6789\n"
        "Phone: (555) 123-4567\n"
    )
    return file_path


@pytest.fixture
def sample_json_file(temp_inbox: Path) -> Path:
    """Create a sample JSON file in the inbox."""
    file_path = temp_inbox / "data.json"
    file_path.write_text('{"key": "value", "nested": {"a": 1, "b": 2}}')
    return file_path


@pytest.fixture
def sample_markdown_file(temp_inbox: Path) -> Path:
    """Create a sample markdown file in the inbox."""
    file_path = temp_inbox / "document.md"
    file_path.write_text(
        "# Heading\n\n"
        "This is a **bold** paragraph.\n\n"
        "## Subheading\n\n"
        "- Item 1\n"
        "- Item 2\n"
    )
    return file_path


# =============================================================================
# Sample Metadata Fixtures
# =============================================================================


@pytest.fixture
def sample_metadata() -> Dict[str, Any]:
    """Provide sample document metadata as returned by analyze_document."""
    return {
        "category": "Technology",
        "year": "2024",
        "type": "Document",
        "summary": "A sample document about technology.",
        "suggested_name": "sample_tech_doc",
        "pii_observations": "",
    }


@pytest.fixture
def sample_staging_item(sample_text_file: Path, sample_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Provide a complete staging item as stored in the manifest."""
    return {
        "status": "pending",
        "original_path": str(sample_text_file),
        "proposed": {
            "filename": "sample_tech_doc.txt",
            "target_folder": "Technology/2024",
            "category": "Technology",
            "year": "2024",
            "type": "Document",
            "tags": ["sample", "test"],
        },
        "metadata": {
            **sample_metadata,
            "is_sensitive": False,
            "pii_detections": [],
            "pii_source": "auto",
        },
        "redacted_text": "This is a sample document for testing purposes.",
    }


@pytest.fixture
def sample_approved_item(sample_staging_item: Dict[str, Any]) -> Dict[str, Any]:
    """Provide a staging item with approved status."""
    item = sample_staging_item.copy()
    item["status"] = "approved"
    return item


# =============================================================================
# Mock Database Fixtures
# =============================================================================


@pytest.fixture
def mock_lancedb() -> MagicMock:
    """Provide a mock LanceDB connection."""
    mock_db = MagicMock()
    mock_table = MagicMock()

    # Configure table mock for common operations
    mock_table.search.return_value = mock_table
    mock_table.where.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.to_list.return_value = []
    mock_table.to_pandas.return_value = MagicMock(empty=True)

    mock_db.open_table.return_value = mock_table
    mock_db.table_names.return_value = ["child_chunks", "parent_chunks"]

    return mock_db


@pytest.fixture
def mock_lancedb_with_data(mock_lancedb: MagicMock) -> MagicMock:
    """Provide a mock LanceDB with sample search results."""
    mock_table = mock_lancedb.open_table.return_value
    mock_table.to_list.return_value = [
        {
            "id": "chunk_1",
            "content": "Sample chunk content about Python programming.",
            "document_id": "doc_abc123",
            "vector": [0.1] * 1024,
            "source_path": "test_doc.md",
            "section_title": "Introduction",
            "tags": ",python,test,",
            "chunk_index": 0,
        },
        {
            "id": "chunk_2",
            "content": "Another chunk with different content.",
            "document_id": "doc_abc123",
            "vector": [0.2] * 1024,
            "source_path": "test_doc.md",
            "section_title": "Details",
            "tags": ",python,test,",
            "chunk_index": 1,
        },
    ]
    return mock_lancedb


# =============================================================================
# Mock Service Fixtures
# =============================================================================


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Provide a mock embedding service."""
    embedder = MagicMock()
    embedder.embed_documents.return_value = [[0.1] * 1024]
    embedder.embed_query.return_value = [0.1] * 1024
    return embedder


@pytest.fixture
def mock_async_embedder() -> AsyncMock:
    """Provide an async mock embedding function."""

    async def embed(text: str) -> list:
        return [0.1] * 1024

    return embed


@pytest.fixture
def mock_retriever() -> AsyncMock:
    """Provide a mock HybridSearcher/retriever."""
    retriever = AsyncMock()
    retriever.search = AsyncMock(
        return_value=[
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
        ]
    )
    return retriever


@pytest.fixture
def mock_pii_scanner() -> MagicMock:
    """Provide a mock PII scanner with no detections."""
    scanner = MagicMock()
    mock_result = MagicMock()
    mock_result.matches = []
    mock_result.privacy_tier = MagicMock()
    mock_result.privacy_tier.value = "PUBLIC"
    scanner.scan.return_value = mock_result
    return scanner


@pytest.fixture
def mock_pii_scanner_with_detections() -> MagicMock:
    """Provide a mock PII scanner that detects SSN and email."""
    scanner = MagicMock()

    ssn_match = MagicMock()
    ssn_match.confidence = 0.95
    ssn_match.start_pos = 50
    ssn_match.end_pos = 61
    ssn_match.data_type = MagicMock()
    ssn_match.data_type.value = "SSN"
    ssn_match.context = "SSN: [REDACTED]"

    email_match = MagicMock()
    email_match.confidence = 0.98
    email_match.start_pos = 25
    email_match.end_pos = 45
    email_match.data_type = MagicMock()
    email_match.data_type.value = "EMAIL"
    email_match.context = "Email: [REDACTED]"

    mock_result = MagicMock()
    mock_result.matches = [ssn_match, email_match]
    mock_result.privacy_tier = MagicMock()
    mock_result.privacy_tier.value = "SENSITIVE"
    scanner.scan.return_value = mock_result

    return scanner


@pytest.fixture
def mock_intelligence() -> MagicMock:
    """Provide a mock intelligence/LLM service."""
    with patch("src.intelligence.analyze_document", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = (
            {
                "category": "Technology",
                "year": "2024",
                "type": "Document",
                "summary": "A test document.",
                "suggested_name": "test_doc",
                "pii_observations": "",
            },
            "Full document text content.",
        )
        yield mock_analyze


@pytest.fixture
def mock_dedup() -> MagicMock:
    """Provide a mock duplicate detector with no duplicates found."""
    dedup = MagicMock()
    dedup.check_file.return_value = []
    dedup.add_file.return_value = None
    dedup._save_state.return_value = None
    return dedup


@pytest.fixture
def mock_auto_tagger() -> MagicMock:
    """Provide a mock auto-tagger."""
    tagger = MagicMock()
    tag_result = MagicMock()
    tag_result.assigned_tags = ["tech", "document"]
    tag_result.suggested_tags = ["report"]
    tagger.tag.return_value = tag_result
    return tagger


# =============================================================================
# FastAPI Test Client Fixtures
# =============================================================================


@pytest.fixture
def fastapi_client():
    """Provide a FastAPI test client for the dashboard server."""
    from fastapi.testclient import TestClient

    from src.server import app

    return TestClient(app)


# =============================================================================
# Chunking Fixtures
# =============================================================================


@pytest.fixture
def mock_chunker() -> MagicMock:
    """Provide a mock parent-child chunker."""
    chunker = MagicMock()

    mock_parent = MagicMock()
    mock_parent.id = "parent-1"
    mock_parent.document_id = "doc-1"
    mock_parent.content = "Parent chunk content with more context."
    mock_parent.section_title = "Introduction"
    mock_parent.token_count = 100

    mock_child = MagicMock()
    mock_child.id = "child-1"
    mock_child.parent_id = "parent-1"
    mock_child.document_id = "doc-1"
    mock_child.content = "Child chunk content."
    mock_child.chunk_index = 0

    chunker.chunk_document.return_value = ([mock_parent], [mock_child])
    return chunker


# =============================================================================
# Queue Manager Fixtures
# =============================================================================


@pytest.fixture
def mock_queue_manager() -> MagicMock:
    """Provide a mock queue manager for batch processing."""
    qm = MagicMock()
    qm.add_job.return_value = "job-123"
    qm.start.return_value = None
    qm.stop.return_value = None
    qm.get_stats.return_value = {"pending": 0, "completed": 0, "failed": 0}
    return qm


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def reset_singletons():
    """Reset module-level singletons after tests that modify them."""
    yield
    # Clean up processor singletons
    try:
        import src.processor

        src.processor._auto_tagger = None
    except (ImportError, AttributeError):
        pass
