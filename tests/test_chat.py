"""
Tests for the /api/chat endpoint (LLM chat with optional RAG context).

Run with: pytest tests/test_chat.py -v
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Setup dummy env vars BEFORE importing src modules
os.environ.setdefault("INBOX_PATH", "/dummy/inbox")
os.environ.setdefault("VAULT_PATH", "/dummy/vault")
os.environ.setdefault("ARCHIVE_PATH", "/dummy/archive")
os.environ.setdefault("GOOGLE_API_KEY", "dummy_key")

sys.path.append(os.getcwd())


@pytest.fixture
def client():
    from src.server import app

    return TestClient(app)


def _mock_provider(response_text: str = "Hello! I'm your CoreRag assistant."):
    """Create a mock LLMProvider that returns the given text."""
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=response_text)
    provider.config = MagicMock()
    provider.config.model = "test-model"
    return provider


class TestChatEndpoint:
    """Tests for POST /api/chat."""

    def test_chat_empty_message(self, client):
        """Empty message returns error."""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_chat_no_rag_success(self, client):
        """Successful chat with RAG disabled and mocked LLM provider."""
        mock_prov = _mock_provider("Hello! I'm your CoreRag assistant.")

        with patch(
            "src.llm.provider.get_default_provider",
            return_value=mock_prov,
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Hello",
                    "use_rag": False,
                    "history": [],
                },
            )

        data = resp.json()
        assert "response" in data
        assert data["response"] == "Hello! I'm your CoreRag assistant."
        assert data["rag_used"] is False
        assert data["sources"] == []

    def test_chat_with_history(self, client):
        """Chat includes conversation history."""
        mock_prov = _mock_provider("You asked about Python.")

        with patch(
            "src.llm.provider.get_default_provider",
            return_value=mock_prov,
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "What did I ask about?",
                    "use_rag": False,
                    "history": [
                        {"role": "user", "content": "Tell me about Python"},
                        {"role": "assistant", "content": "Python is a programming language."},
                    ],
                },
            )

        data = resp.json()
        assert "response" in data

    def test_chat_ollama_failure(self, client):
        """LLM provider failure returns error with sources."""
        mock_prov = MagicMock()
        mock_prov.generate = AsyncMock(side_effect=Exception("Connection refused"))
        mock_prov.config = MagicMock()

        with patch(
            "src.llm.provider.get_default_provider",
            return_value=mock_prov,
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "test query",
                    "use_rag": False,
                },
            )

        data = resp.json()
        assert "error" in data
        assert "sources" in data

    def test_chat_rag_retrieval_failure_still_calls_llm(self, client):
        """If RAG fails, chat should still call LLM without context."""
        mock_prov = _mock_provider("I don't have context but I can help.")

        with (
            patch("lancedb.connect", side_effect=Exception("DB not found")),
            patch(
                "src.llm.provider.get_default_provider",
                return_value=mock_prov,
            ),
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "What is Python?",
                    "use_rag": True,
                },
            )

        data = resp.json()
        assert "response" in data
        assert data["rag_used"] is False
