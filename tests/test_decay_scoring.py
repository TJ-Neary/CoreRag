"""Tests for time-decay scoring."""

from datetime import datetime

import pytest

from src.search.decay_scoring import (
    AdaptiveDecay,
    DecayConfig,
    SeasonalBoost,
    apply_decay_to_results,
    calculate_decay_multiplier,
)


class TestDecayMultiplier:
    """Tests for the decay formula."""

    def test_no_decay_for_current_date(self):
        config = DecayConfig(reference_date=datetime(2025, 6, 1))
        multiplier = calculate_decay_multiplier(datetime(2025, 6, 1), config)
        assert multiplier == pytest.approx(1.0, abs=0.01)

    def test_one_year_decay(self):
        config = DecayConfig(decay_rate=0.1, reference_date=datetime(2025, 6, 1))
        multiplier = calculate_decay_multiplier(datetime(2024, 6, 1), config)
        # 1 / (1 + 0.1 * 1) = 0.909
        assert multiplier == pytest.approx(0.909, abs=0.02)

    def test_five_year_decay(self):
        config = DecayConfig(decay_rate=0.1, reference_date=datetime(2025, 6, 1))
        multiplier = calculate_decay_multiplier(datetime(2020, 6, 1), config)
        # 1 / (1 + 0.1 * 5) = 0.667
        assert multiplier == pytest.approx(0.667, abs=0.02)

    def test_ten_year_decay(self):
        config = DecayConfig(decay_rate=0.1, reference_date=datetime(2025, 6, 1))
        multiplier = calculate_decay_multiplier(datetime(2015, 6, 1), config)
        # 1 / (1 + 0.1 * 10) = 0.5
        assert multiplier == pytest.approx(0.5, abs=0.02)

    def test_min_multiplier_floor(self):
        config = DecayConfig(
            decay_rate=10.0,  # Very aggressive
            min_multiplier=0.1,
            reference_date=datetime(2025, 6, 1),
        )
        multiplier = calculate_decay_multiplier(datetime(2015, 6, 1), config)
        assert multiplier >= 0.1

    def test_max_age_cap(self):
        config = DecayConfig(
            max_age_years=5.0,
            decay_rate=0.1,
            reference_date=datetime(2025, 6, 1),
        )
        # 20 years old but capped at 5
        multiplier = calculate_decay_multiplier(datetime(2005, 6, 1), config)
        expected = 1 / (1 + 0.1 * 5)  # Capped at 5 years
        assert multiplier == pytest.approx(expected, abs=0.02)

    def test_custom_decay_rate(self):
        config = DecayConfig(decay_rate=0.5, reference_date=datetime(2025, 6, 1))
        multiplier = calculate_decay_multiplier(datetime(2024, 6, 1), config)
        # 1 / (1 + 0.5 * 1) = 0.667
        assert multiplier == pytest.approx(0.667, abs=0.02)


class TestApplyDecayToResults:
    """Tests for applying decay to search results."""

    def test_results_get_decay_fields(self):
        config = DecayConfig(reference_date=datetime(2025, 6, 1))
        results = [
            {"score": 0.9, "metadata": {"modified_at": "2024-06-01T00:00:00"}},
        ]
        decayed = apply_decay_to_results(results, config)
        assert "original_score" in decayed[0]
        assert "decay_multiplier" in decayed[0]
        assert decayed[0]["original_score"] == 0.9

    def test_results_resorted_by_decayed_score(self):
        config = DecayConfig(decay_rate=0.5, reference_date=datetime(2025, 6, 1))
        results = [
            {"score": 0.9, "metadata": {"modified_at": "2015-01-01T00:00:00"}},  # Old, high score
            {"score": 0.7, "metadata": {"modified_at": "2025-05-01T00:00:00"}},  # New, lower score
        ]
        decayed = apply_decay_to_results(results, config)
        # Newer doc should float to top despite lower original score
        assert decayed[0]["metadata"]["modified_at"] == "2025-05-01T00:00:00"

    def test_missing_date_no_decay(self):
        # Use current time as reference so missing date = now = no decay
        config = DecayConfig()
        results = [
            {"score": 0.9, "metadata": {}},  # No date
        ]
        decayed = apply_decay_to_results(results, config)
        # No date = use current time = minimal decay (multiplier ~1.0)
        assert decayed[0]["decay_multiplier"] == pytest.approx(1.0, abs=0.01)

    def test_rrf_score_fallback(self):
        config = DecayConfig(reference_date=datetime(2025, 6, 1))
        results = [
            {"rrf_score": 0.8, "metadata": {"modified_at": "2025-06-01T00:00:00"}},
        ]
        decayed = apply_decay_to_results(results, config)
        assert decayed[0]["original_score"] == 0.8

    def test_empty_results(self):
        decayed = apply_decay_to_results([])
        assert decayed == []


class TestAdaptiveDecay:
    """Tests for adaptive decay rate learning."""

    def test_default_decay_rate(self):
        ad = AdaptiveDecay()
        assert ad.get_decay_rate("anything") == 0.1

    def test_prefer_older_reduces_decay(self):
        ad = AdaptiveDecay()
        ad.record_preference("history", selected_age_years=5.0, alternatives_ages=[1.0, 2.0])
        assert ad.get_decay_rate("history") < 0.1

    def test_prefer_newer_increases_decay(self):
        ad = AdaptiveDecay()
        ad.record_preference("news", selected_age_years=0.1, alternatives_ages=[3.0, 5.0])
        assert ad.get_decay_rate("news") > 0.1


class TestSeasonalBoost:
    """Tests for seasonal relevance boosting."""

    def test_tax_boosted_in_march(self):
        sb = SeasonalBoost()
        boost = sb.get_seasonal_boost(["tax-return"], current_date=datetime(2025, 3, 15))
        assert boost > 1.0

    def test_no_boost_for_irrelevant(self):
        sb = SeasonalBoost()
        boost = sb.get_seasonal_boost(["python"], current_date=datetime(2025, 3, 15))
        assert boost == 1.0
