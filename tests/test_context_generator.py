"""Tests for the Contextual Retrieval context generator."""

from unittest.mock import AsyncMock

import pytest

from src.chunking.context_generator import ContextGenerator


@pytest.fixture
def mock_provider():
    """Create a mock LLM provider."""
    provider = AsyncMock()
    provider.generate = AsyncMock(
        return_value="This chunk discusses machine learning validation techniques."
    )
    return provider


@pytest.fixture
def generator(mock_provider):
    gen = ContextGenerator(llm_provider=mock_provider)
    ContextGenerator.clear_cache()
    return gen


class TestContextGenerator:
    async def test_generate_context(self, generator, mock_provider):
        doc = "This is a document about machine learning."
        chunk = "Cross-validation splits data into folds."
        result = await generator.generate_context(doc, chunk)
        assert isinstance(result, str)
        assert len(result) > 0
        mock_provider.generate.assert_called_once()

    async def test_generate_context_caching(self, generator, mock_provider):
        doc = "Document text."
        chunk = "Chunk text."
        r1 = await generator.generate_context(doc, chunk)
        r2 = await generator.generate_context(doc, chunk)
        assert r1 == r2
        # Only one LLM call — second was cached
        assert mock_provider.generate.call_count == 1

    async def test_generate_context_fallback_on_error(self, generator, mock_provider):
        mock_provider.generate.side_effect = Exception("LLM down")
        result = await generator.generate_context("doc", "chunk")
        assert result == ""

    async def test_batch_generation(self, generator, mock_provider):
        doc = "A long document about Python."
        chunks = ["chunk 1", "chunk 2", "chunk 3"]
        results = await generator.generate_contexts_batch(doc, chunks, concurrency=2)
        assert len(results) == 3
        assert all(isinstance(r, str) for r in results)

    async def test_batch_with_errors(self, generator, mock_provider):
        """Batch handles individual failures gracefully."""
        call_count = 0

        async def _flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Transient failure")
            return "context"

        mock_provider.generate.side_effect = _flaky
        results = await generator.generate_contexts_batch("doc", ["a", "b", "c"])
        assert len(results) == 3
        # First and third succeed, second fails
        assert results[0] == "context"
        assert results[1] == ""  # Fallback
        assert results[2] == "context"

    async def test_max_doc_chars(self, mock_provider):
        gen = ContextGenerator(llm_provider=mock_provider, max_doc_chars=100)
        long_doc = "x" * 10000
        await gen.generate_context(long_doc, "chunk")
        call_args = mock_provider.generate.call_args
        prompt = call_args[0][0]
        # Document should be truncated in the prompt
        assert len(prompt) < 10000

    def test_cache_key_deterministic(self, generator):
        k1 = generator._cache_key("doc", "chunk")
        k2 = generator._cache_key("doc", "chunk")
        assert k1 == k2

    def test_cache_key_different_for_different_input(self, generator):
        k1 = generator._cache_key("doc1", "chunk")
        k2 = generator._cache_key("doc2", "chunk")
        assert k1 != k2

    def test_clear_cache(self, generator):
        from src.chunking.context_generator import _context_cache

        _context_cache["test_key"] = "test_value"
        ContextGenerator.clear_cache()
        assert len(_context_cache) == 0
