"""Tests for the chunk quality scorer."""

import pytest

from src.quality.chunk_scorer import ChunkScorer


@pytest.fixture
def scorer():
    return ChunkScorer()


class TestChunkScorer:
    def test_high_quality_prose(self, scorer):
        text = (
            "Machine learning models require careful validation to ensure they "
            "generalize well to unseen data. Cross-validation is a widely used "
            "technique that partitions the training data into folds. Each fold "
            "serves as a validation set while the remaining folds are used for training."
        )
        score = scorer.score(text)
        assert score.overall > 0.6

    def test_low_quality_fragment(self, scorer):
        text = "see also page"
        score = scorer.score(text)
        assert score.overall < 0.4

    def test_empty_text(self, scorer):
        score = scorer.score("")
        assert score.overall == pytest.approx(0.0, abs=0.1)

    def test_very_short_text(self, scorer):
        score = scorer.score("Hello world")
        assert score.overall < 0.5

    def test_moderate_quality(self, scorer):
        text = "The system uses Python 3.12 with type hints on all functions."
        score = scorer.score(text)
        assert 0.3 < score.overall < 0.9

    def test_score_components(self, scorer):
        text = (
            "Natural language processing has made significant advances in recent years. "
            "Transformer architectures have revolutionized the field. "
            "Models like BERT and GPT demonstrate strong performance across many tasks."
        )
        score = scorer.score(text)
        assert 0.0 <= score.density <= 1.0
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.length <= 1.0
        assert 0.0 <= score.coherence <= 1.0

    def test_list_content(self, scorer):
        text = "- Item one\n- Item two\n- Item three\n- Item four"
        score = scorer.score(text)
        # Lists are valid content
        assert score.overall > 0.2

    def test_very_long_text(self, scorer):
        text = "This is a sentence with some words. " * 200
        score = scorer.score(text)
        # Should be penalized for length and low density
        assert score.length < 1.0
