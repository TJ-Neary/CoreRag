"""
Tests for the auto-tagger classification module.

Run with: pytest tests/test_auto_tagger.py -v
"""

from src.classification.auto_tagger import AutoTagger, Taxonomy


class TestTaxonomy:
    """Tests for the default taxonomy."""

    def test_default_taxonomy_has_tags(self):
        t = Taxonomy()
        assert len(t.tags) > 0

    def test_tags_are_strings(self):
        t = Taxonomy()
        # Tags should be accessible
        assert all(isinstance(tag, str) for tag in t.tags)


class TestKeywordTagger:
    """Tests for keyword-based tagging."""

    def test_relevant_content_gets_tags(self):
        tagger = AutoTagger()
        result = tagger.tag(
            "This Python tutorial covers pandas dataframes and numpy arrays "
            "for data analysis and machine learning workflows."
        )
        assert isinstance(result.assigned_tags, list)
        # Should find at least one tag from technical content
        all_tags = result.assigned_tags + result.suggested_tags
        assert len(all_tags) > 0

    def test_empty_content_gets_no_tags(self):
        tagger = AutoTagger()
        result = tagger.tag("")
        assert result.assigned_tags == []

    def test_gibberish_gets_no_tags(self):
        tagger = AutoTagger()
        result = tagger.tag("asdfghjkl qwertyuiop zxcvbnm")
        assert result.assigned_tags == []

    def test_tagging_result_has_processing_time(self):
        tagger = AutoTagger()
        result = tagger.tag("Some document about software engineering")
        assert result.processing_time_ms >= 0

    def test_file_path_used_in_tagging(self):
        tagger = AutoTagger()
        result = tagger.tag(
            "Document content here",
            file_path="project/src/main.py",
        )
        assert isinstance(result.assigned_tags, list)


class TestEmbeddingTagger:
    """Tests for embedding-based tagging mode."""

    def test_embedding_tagger_initializes_with_embedder(self):
        def mock_embedder(text):
            return [0.1] * 384

        tagger = AutoTagger(embedder=mock_embedder)
        # Should have both keyword and embedding taggers
        assert tagger.keyword_tagger is not None
        assert tagger.embedding_tagger is not None

    def test_no_embedder_means_keyword_only(self):
        tagger = AutoTagger()
        assert tagger.embedding_tagger is None

    def test_hybrid_tagging_with_embedder(self):
        def mock_embedder(text):
            return [0.1] * 384

        tagger = AutoTagger(embedder=mock_embedder)
        result = tagger.tag("Machine learning with neural networks and deep learning")
        assert isinstance(result.assigned_tags, list)
        assert "keyword" in result.method or "embedding" in result.method
