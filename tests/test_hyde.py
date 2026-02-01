"""Tests for HyDE (Hypothetical Document Embedding) query expansion."""

import tempfile
import pytest
from pathlib import Path

from src.search.hyde import HyDEExpander, HyDEConfig, HyDEResult


def mock_llm(prompt: str) -> str:
    """Mock LLM that returns a predictable hypothetical document."""
    return "To configure authentication, set up OAuth2 with client credentials flow and JWT tokens for session management."


def mock_embedder(text: str) -> list:
    """Mock embedder returning a fixed-length vector."""
    return [0.1] * 768


class TestHyDEExpander:
    """Tests for HyDE query expansion."""

    def test_expand_returns_hypothetical_doc(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("How do I configure authentication?")
        assert isinstance(result, HyDEResult)
        assert result.original_query == "How do I configure authentication?"
        assert "OAuth2" in result.hypothetical_document
        assert result.cache_hit is False

    def test_skip_short_queries(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False, min_query_length=10),
        )
        result = expander.expand("test")
        # Short query should be returned as-is
        assert result.hypothetical_document == "test"

    def test_skip_patterns(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("what is Python?")
        # "what is" matches skip pattern
        assert result.hypothetical_document == "what is Python?"

    def test_skip_define_pattern(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("define machine learning concepts")
        assert result.hypothetical_document == "define machine learning concepts"

    def test_embedding_generated_when_embedder_provided(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            embedder=mock_embedder,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("How do I configure authentication?")
        assert result.embedding is not None
        assert len(result.embedding) == 768

    def test_no_embedding_without_embedder(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("How do I configure authentication?")
        assert result.embedding is None

    def test_cache_hit_on_second_call(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=True),
        )
        result1 = expander.expand("How do I configure authentication?")
        result2 = expander.expand("How do I configure authentication?")
        assert result1.cache_hit is False
        assert result2.cache_hit is True
        assert result1.hypothetical_document == result2.hypothetical_document

    def test_cache_persistence_to_disk(self):
        with tempfile.TemporaryDirectory() as td:
            config = HyDEConfig(enable_cache=True, cache_dir=Path(td))
            expander = HyDEExpander(llm_generator=mock_llm, config=config)
            expander.expand("How do I configure authentication?")

            # Check cache file was written
            cache_file = Path(td) / "hyde_cache.json"
            assert cache_file.exists()

    def test_llm_failure_returns_original_query(self):
        def failing_llm(prompt: str) -> str:
            raise RuntimeError("LLM unavailable")

        expander = HyDEExpander(
            llm_generator=failing_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("How do I configure authentication?")
        # Should fall back to original query
        assert result.hypothetical_document == "How do I configure authentication?"

    def test_short_llm_response_returns_original(self):
        def short_llm(prompt: str) -> str:
            return "yes"

        expander = HyDEExpander(
            llm_generator=short_llm,
            config=HyDEConfig(enable_cache=False),
        )
        result = expander.expand("How do I configure authentication?")
        assert result.hypothetical_document == "How do I configure authentication?"

    def test_expand_batch(self):
        expander = HyDEExpander(
            llm_generator=mock_llm,
            config=HyDEConfig(enable_cache=False),
        )
        results = expander.expand_batch(["query one is long enough", "query two is also long"])
        assert len(results) == 2
        assert all(isinstance(r, HyDEResult) for r in results)
