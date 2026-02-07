"""Classification module for CoreRag."""

from src.classification.auto_tagger import (
    AutoTagger,
    EmbeddingTagger,
    KeywordTagger,
    Tag,
    TaggingResult,
    Taxonomy,
    auto_tag,
)

__all__ = [
    "AutoTagger",
    "Taxonomy",
    "Tag",
    "TaggingResult",
    "KeywordTagger",
    "EmbeddingTagger",
    "auto_tag",
]
