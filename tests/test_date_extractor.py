"""Tests for the date extractor."""

import pytest

from src.quality.date_extractor import DateExtractor


@pytest.fixture
def extractor():
    return DateExtractor()


class TestDateExtractor:
    def test_iso_date(self, extractor):
        date, conf = extractor.extract("Created on 2024-01-15 for review.")
        assert date == "2024-01-15"
        assert conf >= 0.9

    def test_iso_datetime(self, extractor):
        date, conf = extractor.extract("Timestamp: 2024-03-20T14:30:00")
        assert date == "2024-03-20"
        assert conf >= 0.9

    def test_us_long_date(self, extractor):
        date, conf = extractor.extract("Published January 15, 2024.")
        assert date == "2024-01-15"
        assert conf >= 0.8

    def test_us_short_date(self, extractor):
        date, conf = extractor.extract("Updated on Jan 5, 2024.")
        assert date == "2024-01-05"
        assert conf >= 0.7

    def test_year_month(self, extractor):
        date, conf = extractor.extract("Report for 2024-03 period.")
        assert date == "2024-03"
        assert conf >= 0.5

    def test_month_year(self, extractor):
        date, conf = extractor.extract("Released in March 2024.")
        assert date == "2024-03"
        assert conf >= 0.4

    def test_year_only(self, extractor):
        date, conf = extractor.extract("Founded in 2023.")
        assert date == "2023"
        assert conf >= 0.2

    def test_no_date(self, extractor):
        date, conf = extractor.extract("No dates in this text at all.")
        assert date is None
        assert conf == 0.0

    def test_empty_text(self, extractor):
        date, conf = extractor.extract("")
        assert date is None
        assert conf == 0.0

    def test_multiple_dates_highest_confidence(self, extractor):
        text = "Created 2024-01-15 and updated January 2024"
        date, conf = extractor.extract(text)
        # ISO date should win (higher confidence)
        assert date == "2024-01-15"
        assert conf >= 0.9

    def test_extract_all(self, extractor):
        text = "Report from 2024-01-15, updated March 2024, founded 2020."
        results = extractor.extract_all(text)
        assert len(results) >= 2
        dates = [r[0] for r in results]
        assert "2024-01-15" in dates

    def test_us_slash_date(self, extractor):
        date, conf = extractor.extract("Filed on 01/15/2024.")
        assert date == "2024-01-15"

    def test_european_dot_date(self, extractor):
        date, conf = extractor.extract("Erstellt am 15.01.2024.")
        assert date is not None
