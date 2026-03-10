"""Tests for OllamaLLM thinking tag stripping."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.ollama_llm import OllamaLLM


class TestOllamaLLM:
    @pytest.fixture
    def llm(self):
        with patch("src.utils.ollama_llm.OllamaLLM.__init__", return_value=None):
            obj = OllamaLLM.__new__(OllamaLLM)
            obj.model = "qwen3:32b"
            obj.host = "http://localhost:11434"
            obj.timeout = 60.0
            return obj

    async def test_generate_strips_thinking_tags(self, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '<think>\nanalyzing...\n</think>\n{"entities": []}'
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await llm.generate("Extract entities from: test doc")

        assert "<think>" not in result
        assert '{"entities": []}' in result

    async def test_generate_passthrough_without_tags(self, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "clean response"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await llm.generate("prompt")

        assert result == "clean response"

    async def test_generate_handles_multiple_think_blocks(self, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '<think>first</think>middle<think>second</think>{"result": true}'
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await llm.generate("prompt")

        assert "<think>" not in result
        assert '{"result": true}' in result
