"""
Time-Weighted Scoring (Decay Function)

Recent information is usually more valuable than stale information.
A note from 2021 might have high vector similarity but be obsolete.

This module applies temporal decay to search results, allowing
recent documents to "float" to the top.

Formula: Final_Score = Vector_Score * (1 / (1 + decay_rate * age_in_years))
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DecayConfig:
    """Configuration for time-weighted scoring."""

    decay_rate: float = 0.1  # Higher = faster decay
    max_age_years: float = 10.0  # Documents older than this get minimum score
    min_multiplier: float = 0.1  # Minimum score multiplier
    reference_date: Optional[datetime] = None  # None = use current time
    use_modification_date: bool = True  # vs creation date


def calculate_decay_multiplier(doc_date: datetime, config: DecayConfig) -> float:
    """
    Calculate decay multiplier for a document date.

    Args:
        doc_date: Document date (creation or modification)
        config: Decay configuration

    Returns:
        Multiplier between min_multiplier and 1.0
    """
    reference = config.reference_date or datetime.now()

    # Calculate age in years
    age_days = (reference - doc_date).days
    age_years = age_days / 365.25

    # Cap at max age
    age_years = min(age_years, config.max_age_years)

    # Apply decay formula
    # Exponential decay: multiplier = 1 / (1 + decay_rate * age)
    multiplier = 1 / (1 + config.decay_rate * age_years)

    # Ensure minimum
    return max(multiplier, config.min_multiplier)


def apply_decay_to_results(
    results: List[dict], config: Optional[DecayConfig] = None, date_field: str = "modified_at"
) -> List[dict]:
    """
    Apply time-based decay to search results.

    Args:
        results: List of search results with scores
        config: Decay configuration
        date_field: Metadata field containing document date

    Returns:
        Results with adjusted scores, re-sorted
    """
    config = config or DecayConfig()

    for result in results:
        # Get document date from metadata
        metadata = result.get("metadata", {})
        if isinstance(metadata, str):
            import json

            metadata = json.loads(metadata)

        date_str = metadata.get(date_field)

        if date_str:
            try:
                if isinstance(date_str, str):
                    doc_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    doc_date = date_str
            except (ValueError, TypeError, AttributeError):
                doc_date = datetime.now()  # Fallback to now (no decay) if date unparseable
        else:
            doc_date = datetime.now()

        # Calculate multiplier
        multiplier = calculate_decay_multiplier(doc_date, config)

        # Store original score and apply decay
        original_score = result.get("score", result.get("rrf_score", 0))
        result["original_score"] = original_score
        result["decay_multiplier"] = multiplier
        result["score"] = original_score * multiplier

    # Re-sort by decayed score
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return results


class AdaptiveDecay:
    """
    Adaptive decay that learns from user behavior.

    If users consistently prefer older documents in a category,
    reduce decay for that category.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.category_decay_rates = {}  # category -> adjusted decay rate
        self.default_decay_rate = 0.1
        self.db_path = db_path

    def get_decay_rate(self, category: str) -> float:
        """Get decay rate for a category."""
        return self.category_decay_rates.get(category, self.default_decay_rate)

    def record_preference(
        self, category: str, selected_age_years: float, alternatives_ages: List[float]
    ):
        """
        Record user preference to adjust decay rates.

        If user selected an older document over newer ones,
        reduce decay for this category.
        """
        if not alternatives_ages:
            return

        avg_alt_age = sum(alternatives_ages) / len(alternatives_ages)

        # User preferred older content
        if selected_age_years > avg_alt_age * 1.5:
            current_rate = self.get_decay_rate(category)
            # Reduce decay (older content valued more)
            new_rate = max(0.01, current_rate * 0.9)
            self.category_decay_rates[category] = new_rate
            logger.debug(f"Reduced decay for {category}: {current_rate:.3f} -> {new_rate:.3f}")

        # User preferred newer content
        elif selected_age_years < avg_alt_age * 0.5:
            current_rate = self.get_decay_rate(category)
            # Increase decay (newer content valued more)
            new_rate = min(0.5, current_rate * 1.1)
            self.category_decay_rates[category] = new_rate
            logger.debug(f"Increased decay for {category}: {current_rate:.3f} -> {new_rate:.3f}")


class SeasonalBoost:
    """
    Boost documents based on seasonal relevance.

    Example: Tax documents boosted in March-April.
    """

    def __init__(self):
        self.seasonal_patterns = {
            "tax": [(3, 4)],  # March-April
            "review": [(12, 1)],  # December-January (annual reviews)
            "budget": [(1, 2), (10, 11)],  # Q1 and Q4 planning
        }

    def get_seasonal_boost(
        self, keywords: List[str], current_date: Optional[datetime] = None
    ) -> float:
        """
        Calculate seasonal boost multiplier.

        Args:
            keywords: Document keywords/tags
            current_date: Date to evaluate (default: now)

        Returns:
            Boost multiplier (1.0 = no boost)
        """
        current_date = current_date or datetime.now()
        current_month = current_date.month

        max_boost = 1.0

        for keyword in keywords:
            for pattern_key, months in self.seasonal_patterns.items():
                if pattern_key in keyword.lower():
                    for month_range in months:
                        if isinstance(month_range, tuple):
                            start, end = month_range
                            if start <= current_month <= end or (
                                start > end and (current_month >= start or current_month <= end)
                            ):
                                max_boost = max(max_boost, 1.3)
                        elif current_month == month_range:
                            max_boost = max(max_boost, 1.3)

        return max_boost


def combined_temporal_scoring(
    results: List[dict], decay_config: Optional[DecayConfig] = None, apply_seasonal: bool = True
) -> List[dict]:
    """
    Apply combined temporal scoring: decay + seasonal boost.

    Args:
        results: Search results
        decay_config: Decay configuration
        apply_seasonal: Whether to apply seasonal boosts

    Returns:
        Results with adjusted scores
    """
    # Apply decay
    results = apply_decay_to_results(results, decay_config)

    # Apply seasonal boost
    if apply_seasonal:
        seasonal = SeasonalBoost()

        for result in results:
            metadata = result.get("metadata", {})
            if isinstance(metadata, str):
                import json

                metadata = json.loads(metadata)

            keywords = metadata.get("keywords", [])
            tags = metadata.get("tags", [])

            boost = seasonal.get_seasonal_boost(keywords + tags)
            result["seasonal_boost"] = boost
            result["score"] *= boost

        # Re-sort after seasonal boost
        results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return results
