"""
Date Extractor

Extracts dates from text with confidence scoring.
Supports ISO, US (MM/DD/YYYY), European (DD.MM.YYYY), and relative formats.
"""

import re
from datetime import datetime
from typing import Optional


class DateExtractor:
    """Extracts dates from text with confidence scores."""

    # Patterns ordered by specificity (most specific first)
    PATTERNS = [
        # ISO: 2024-01-15, 2024-01-15T10:30:00
        (r"\b(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2})", "%Y-%m-%d", 0.95),
        (r"\b(\d{4}-\d{2}-\d{2})\b", "%Y-%m-%d", 0.9),
        # US: January 15, 2024 or Jan 15, 2024
        (
            r"\b((?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{1,2},?\s+\d{4})\b",
            "%B %d, %Y",
            0.85,
        ),
        (
            r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})\b",
            "%b %d, %Y",
            0.8,
        ),
        # US: 01/15/2024 (ambiguous with European)
        (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", "%m/%d/%Y", 0.6),
        # European: 15.01.2024
        (r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b", "%d.%m.%Y", 0.6),
        # Year-month: 2024-01, January 2024
        (r"\b(\d{4}-\d{2})\b", "%Y-%m", 0.5),
        (
            r"\b((?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{4})\b",
            "%B %Y",
            0.5,
        ),
        # Year only: 2024 (low confidence, very common)
        (r"\b(20\d{2})\b", "%Y", 0.3),
    ]

    def extract(self, text: str) -> tuple[Optional[str], float]:
        """Extract the most confident date from text.

        Args:
            text: Input text to scan.

        Returns:
            Tuple of (normalized_date_string, confidence).
            Returns (None, 0.0) if no date found.
        """
        best_date: Optional[str] = None
        best_confidence: float = 0.0

        for pattern, fmt, confidence in self.PATTERNS:
            match = re.search(pattern, text)
            if match and confidence > best_confidence:
                raw = match.group(1)
                try:
                    # Normalize comma handling
                    raw_clean = raw.replace(",", "").strip()
                    if fmt in ("%B %d, %Y", "%b %d, %Y"):
                        raw_clean = raw.replace(",", "").strip()
                    parsed = datetime.strptime(raw_clean, fmt.replace(",", ""))
                    # Normalize to ISO format
                    if fmt == "%Y":
                        best_date = f"{parsed.year}"
                    elif fmt in ("%Y-%m", "%B %Y"):
                        best_date = parsed.strftime("%Y-%m")
                    else:
                        best_date = parsed.strftime("%Y-%m-%d")
                    best_confidence = confidence
                except ValueError:
                    continue

        return best_date, best_confidence

    def extract_all(self, text: str) -> list[tuple[str, float]]:
        """Extract all dates from text with confidence scores.

        Returns:
            List of (date_string, confidence) tuples, sorted by confidence desc.
        """
        results = []
        seen = set()

        for pattern, fmt, confidence in self.PATTERNS:
            for match in re.finditer(pattern, text):
                raw = match.group(1)
                try:
                    raw_clean = raw.replace(",", "").strip()
                    parsed = datetime.strptime(raw_clean, fmt.replace(",", ""))
                    if fmt == "%Y":
                        normalized = f"{parsed.year}"
                    elif fmt in ("%Y-%m", "%B %Y"):
                        normalized = parsed.strftime("%Y-%m")
                    else:
                        normalized = parsed.strftime("%Y-%m-%d")

                    if normalized not in seen:
                        seen.add(normalized)
                        results.append((normalized, confidence))
                except ValueError:
                    continue

        results.sort(key=lambda x: x[1], reverse=True)
        return results
