"""Tests for the multi-resolution summarizer."""

from unittest.mock import AsyncMock

import pytest

from src.chunking.summarizer import MultiResolutionSummarizer


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="This section covers ML validation techniques.")
    return provider


@pytest.fixture
def summarizer(mock_provider):
    return MultiResolutionSummarizer(llm_provider=mock_provider)


class TestMultiResolutionSummarizer:
    async def test_summarize_parent(self, summarizer, mock_provider):
        result = await summarizer.summarize_parent("Some long text about ML.")
        assert isinstance(result, str)
        assert len(result) > 0
        mock_provider.generate.assert_called_once()

    async def test_summarize_with_children(self, summarizer):
        result = await summarizer.summarize_parent("Parent text.", ["child 1", "child 2"])
        assert isinstance(result, str)

    async def test_fallback_on_error(self, summarizer, mock_provider):
        mock_provider.generate.side_effect = Exception("LLM failed")
        result = await summarizer.summarize_parent("text")
        assert result == ""

    async def test_text_truncation(self, mock_provider):
        summarizer = MultiResolutionSummarizer(llm_provider=mock_provider, max_text_chars=50)
        long_text = "x" * 10000
        await summarizer.summarize_parent(long_text)
        call_args = mock_provider.generate.call_args[0][0]
        assert len(call_args) < 10000
