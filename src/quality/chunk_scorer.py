"""
Chunk Quality Scorer

Heuristic scoring of chunk quality (0.0-1.0) based on information density,
completeness, length adequacy, and coherence. Chunks below the quality
threshold are still indexed but flagged for retrieval de-prioritization.
"""

import re
from dataclasses import dataclass


@dataclass
class ChunkScore:
    """Detailed breakdown of a chunk quality score."""

    overall: float
    density: float
    completeness: float
    length: float
    coherence: float


class ChunkScorer:
    """Heuristic chunk quality scorer."""

    # Words that carry little information
    STOP_WORDS = frozenset(
        "a an the is are was were be been being have has had do does did "
        "will would shall should may might can could of in to for on at by "
        "with from as into through during before after above below between "
        "and or but not no nor so yet both either neither each every all any "
        "few more most other some such this that these those it its he she "
        "they them their his her my your our its who what which when where "
        "how than too very also just about up out if then".split()
    )

    def score(self, chunk_text: str, parent_text: str = "") -> ChunkScore:
        """Score a chunk's quality on multiple dimensions.

        Args:
            chunk_text: The chunk text to score.
            parent_text: Optional parent chunk text for context.

        Returns:
            ChunkScore with overall and per-dimension scores.
        """
        density = self._information_density(chunk_text)
        completeness = self._completeness(chunk_text)
        length = self._length_adequacy(chunk_text)
        coherence = self._coherence(chunk_text)

        # Weighted average
        overall = density * 0.30 + completeness * 0.20 + length * 0.25 + coherence * 0.25

        return ChunkScore(
            overall=round(overall, 3),
            density=round(density, 3),
            completeness=round(completeness, 3),
            length=round(length, 3),
            coherence=round(coherence, 3),
        )

    def _information_density(self, text: str) -> float:
        """Ratio of unique meaningful words to total words."""
        words = re.findall(r"\b\w+\b", text.lower())
        if not words:
            return 0.0

        meaningful = [w for w in words if w not in self.STOP_WORDS and len(w) > 2]
        unique_meaningful = set(meaningful)

        if not meaningful:
            return 0.0

        # Ratio of unique meaningful words to total words
        ratio = len(unique_meaningful) / len(words)
        # Clamp to [0, 1] — typical good text is 0.3-0.6
        return min(ratio / 0.5, 1.0)

    def _completeness(self, text: str) -> float:
        """Does the chunk look like complete text?"""
        score = 0.0
        stripped = text.strip()

        if not stripped:
            return 0.0

        # Starts with capital or list marker
        if stripped[0].isupper() or stripped[0] in "-*•1234567890#":
            score += 0.4

        # Ends with sentence-ending punctuation
        if stripped[-1] in ".!?:;)\"'":
            score += 0.4

        # Has at least one complete sentence
        sentences = re.split(r"[.!?]+", stripped)
        complete_sentences = [s for s in sentences if len(s.strip()) > 10]
        if complete_sentences:
            score += 0.2

        return min(score, 1.0)

    def _length_adequacy(self, text: str) -> float:
        """Score based on word count — penalize very short or very long."""
        words = text.split()
        count = len(words)

        if count < 5:
            return 0.1
        if count < 20:
            return 0.3 + (count - 5) * 0.03  # Linear ramp 0.3 → 0.75
        if count <= 500:
            return 1.0
        # Gradual penalty for very long chunks
        return max(0.3, 1.0 - (count - 500) * 0.001)

    def _coherence(self, text: str) -> float:
        """Sentence structure regularity."""
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

        if not sentences:
            return 0.2

        # Average sentence length (words)
        lengths = [len(s.split()) for s in sentences]
        avg_len = sum(lengths) / len(lengths)

        score = 0.0

        # Ideal sentence length: 8-25 words
        if 8 <= avg_len <= 25:
            score += 0.5
        elif 5 <= avg_len <= 40:
            score += 0.3
        else:
            score += 0.1

        # Multiple sentences suggest coherent prose
        if len(sentences) >= 2:
            score += 0.3

        # Low variance in sentence length suggests consistent writing
        if len(lengths) >= 2:
            variance = sum((slen - avg_len) ** 2 for slen in lengths) / len(lengths)
            std_dev = variance**0.5
            if std_dev < avg_len * 0.5:
                score += 0.2
            elif std_dev < avg_len:
                score += 0.1

        return min(score, 1.0)
