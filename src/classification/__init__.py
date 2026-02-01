"""Classification module for PKM."""

from src.classification.auto_tagger import (
    AutoTagger,
    Taxonomy,
    Tag,
    TaggingResult,
    KeywordTagger,
    EmbeddingTagger,
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
