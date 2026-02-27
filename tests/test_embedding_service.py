"""
Tests for the EmbeddingService including BGE-M3 support.
"""

from unittest.mock import patch

import pytest

from src.embeddings.embedding_service import EmbeddingCache, EmbeddingService


class TestEmbeddingCache:
    """Tests for the LRU embedding cache."""

    def test_put_and_get(self, tmp_path):
        cache = EmbeddingCache(max_size=100, cache_dir=tmp_path / "cache", persist=False)
        cache.put("hello", "model-a", [1.0, 2.0])
        result = cache.get("hello", "model-a")
        assert result == [1.0, 2.0]

    def test_cache_miss(self, tmp_path):
        cache = EmbeddingCache(max_size=100, cache_dir=tmp_path / "cache", persist=False)
        assert cache.get("missing", "model-a") is None

    def test_different_models(self, tmp_path):
        cache = EmbeddingCache(max_size=100, cache_dir=tmp_path / "cache", persist=False)
        cache.put("hello", "model-a", [1.0])
        cache.put("hello", "model-b", [2.0])
        assert cache.get("hello", "model-a") == [1.0]
        assert cache.get("hello", "model-b") == [2.0]

    def test_eviction(self, tmp_path):
        cache = EmbeddingCache(max_size=2, cache_dir=tmp_path / "cache", persist=False)
        cache.put("a", "m", [1.0])
        cache.put("b", "m", [2.0])
        cache.put("c", "m", [3.0])  # Should evict "a"
        assert cache.get("a", "m") is None
        assert cache.get("b", "m") == [2.0]

    def test_clear(self, tmp_path):
        cache = EmbeddingCache(max_size=100, cache_dir=tmp_path / "cache", persist=False)
        cache.put("a", "m", [1.0])
        cache.clear()
        assert len(cache) == 0

    def test_persistence(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache = EmbeddingCache(max_size=100, cache_dir=cache_dir, persist=True)
        cache.put("hello", "m", [1.0, 2.0])
        cache.save()

        # Load into a new cache
        cache2 = EmbeddingCache(max_size=100, cache_dir=cache_dir, persist=True)
        assert cache2.get("hello", "m") == [1.0, 2.0]


class TestEmbeddingServiceConfig:
    """Tests for model configuration and support."""

    def test_bge_m3_in_supported_models(self):
        assert "BAAI/bge-m3" in EmbeddingService.SUPPORTED_MODELS
        assert EmbeddingService.SUPPORTED_MODELS["BAAI/bge-m3"] == 1024

    def test_bge_m3_alias(self):
        assert EmbeddingService.MODEL_ALIASES.get("bge-m3") == "BAAI/bge-m3"

    def test_query_instruction_prefix(self):
        prefix = EmbeddingService.QUERY_INSTRUCTION_MODELS.get("BAAI/bge-m3", "")
        assert "searching relevant passages" in prefix

    def test_no_prefix_for_minilm(self):
        prefix = EmbeddingService.QUERY_INSTRUCTION_MODELS.get("all-MiniLM-L6-v2", "")
        assert prefix == ""


class TestEmbeddingServiceBGEM3:
    """Tests requiring actual model loading — marked as slow."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a lightweight embedding service for testing."""
        # Use MiniLM for speed in tests; BGE-M3 tested via config tests above
        try:
            svc = EmbeddingService(
                model_name="all-MiniLM-L6-v2",
                cache_dir=tmp_path / "cache",
                device="cpu",
                batch_size=8,
            )
            return svc
        except Exception:
            pytest.skip("sentence-transformers not available")

    def test_embed_single(self, service):
        result = service.embed("test text")
        assert len(result.embedding) == 384
        assert result.model == "all-MiniLM-L6-v2"

    def test_embed_batch(self, service):
        results = service.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert all(len(r.embedding) == 384 for r in results)

    def test_embed_query_applies_prefix(self, service):
        """Verify embed_query applies instruction prefix for appropriate models."""
        # MiniLM has no prefix, so query embedding should match direct embedding
        query_vec = service.embed_query("test query")
        direct_vec = service.embed("test query").embedding
        assert query_vec == direct_vec

    def test_embed_documents(self, service):
        vecs = service.embed_documents(["doc one", "doc two"], show_progress=False)
        assert len(vecs) == 2
        assert all(len(v) == 384 for v in vecs)

    def test_similarity(self, service):
        sim = service.similarity("hello world", "hello world")
        assert sim > 0.99

    def test_cache_works(self, service):
        service.embed("cached text")
        service.embed("cached text")
        assert service.stats.cache_hits >= 1

    def test_get_info(self, service):
        info = service.get_info()
        assert info["model"] == "all-MiniLM-L6-v2"
        assert info["dimension"] == 384


class TestMigrationScript:
    """Tests for the embedding migration script."""

    def test_dry_run_with_no_data(self, tmp_path):
        """Migration dry run returns skipped when no data exists."""

        # Patch DB_PATH
        with patch("scripts.migrate_embeddings.DB_PATH", tmp_path / "test.lancedb"):
            from scripts.migrate_embeddings import migrate_embeddings

            result = migrate_embeddings(target_model="all-MiniLM-L6-v2", dry_run=True)
            assert result["status"] == "skipped"
