"""
Tests for the /api/chat endpoint (LLM chat with optional RAG context).

Run with: pytest tests/test_chat.py -v
"""

import os
import sys
from unittest.mock import patch, AsyncMock, MagicMock

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


class TestChatEndpoint:
    """Tests for POST /api/chat."""

    def test_chat_empty_message(self, client):
        """Empty message returns error."""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_chat_no_rag_success(self, client):
        """Successful chat with RAG disabled and mocked Ollama."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Hello! I'm your CoreRag assistant."}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resp = client.post("/api/chat", json={
                "message": "Hello",
                "use_rag": False,
                "history": [],
            })

        data = resp.json()
        assert "response" in data
        assert data["response"] == "Hello! I'm your CoreRag assistant."
        assert data["rag_used"] is False
        assert data["sources"] == []

    def test_chat_with_history(self, client):
        """Chat includes conversation history."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "You asked about Python."}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resp = client.post("/api/chat", json={
                "message": "What did I ask about?",
                "use_rag": False,
                "history": [
                    {"role": "user", "content": "Tell me about Python"},
                    {"role": "assistant", "content": "Python is a programming language."},
                ],
            })

        data = resp.json()
        assert "response" in data

    def test_chat_ollama_failure(self, client):
        """Ollama connection failure returns error with sources."""
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            resp = client.post("/api/chat", json={
                "message": "test query",
                "use_rag": False,
            })

        data = resp.json()
        assert "error" in data
        assert "sources" in data

    def test_chat_rag_retrieval_failure_still_calls_llm(self, client):
        """If RAG fails, chat should still call Ollama without context."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "I don't have context but I can help."}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("lancedb.connect", side_effect=Exception("DB not found")), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resp = client.post("/api/chat", json={
                "message": "What is Python?",
                "use_rag": True,
            })

        data = resp.json()
        assert "response" in data
        assert data["rag_used"] is False
