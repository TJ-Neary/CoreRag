"""
Tests for the conflict detector module.

Run with: pytest tests/test_conflict_detector.py -v
"""

from src.quality.conflict_detector import ConflictDetector, NumericExtractor


class TestNumericExtractor:
    """Tests for numeric fact extraction."""

    def test_extract_version(self):
        facts = NumericExtractor.extract("We use Python version 3.11.4 in production")
        assert len(facts) > 0
        assert any(f["type"] == "version" for f in facts)

    def test_extract_date(self):
        facts = NumericExtractor.extract("The deadline is 2025-03-15 for delivery")
        assert any(f["type"] == "date" for f in facts)

    def test_extract_percentage(self):
        facts = NumericExtractor.extract("The success rate is 95.5% this quarter")
        assert any(f["type"] == "percentage" for f in facts)

    def test_extract_count(self):
        facts = NumericExtractor.extract("There are 1500 users on the platform")
        assert any(f["type"] == "count" for f in facts)

    def test_no_facts_from_empty_text(self):
        facts = NumericExtractor.extract("")
        assert facts == []

    def test_no_facts_from_plain_text(self):
        facts = NumericExtractor.extract("The sky is blue and the grass is green")
        assert facts == []


class TestConflictDetector:
    """Tests for the conflict detection system."""

    def test_init_without_embedder(self):
        detector = ConflictDetector()
        assert detector is not None

    def test_init_with_embedder(self):
        def mock_embedder(text):
            return [0.1] * 384

        detector = ConflictDetector(embedder=mock_embedder)
        assert detector is not None

    def test_scan_empty_documents(self):
        detector = ConflictDetector()
        report = detector.scan_documents([])
        assert report.documents_analyzed == 0

    def test_scan_single_document(self):
        detector = ConflictDetector()
        docs = [{"text": "The system has 500 users.", "source_path": "doc1.md"}]
        report = detector.scan_documents(docs)
        assert report.documents_analyzed == 1

    def test_scan_conflicting_numeric_facts(self):
        detector = ConflictDetector()
        docs = [
            {
                "text": "The project has 500 active users as of March.",
                "source_path": "report_q1.md",
            },
            {
                "text": "The project has 5000 active users this quarter.",
                "source_path": "report_q2.md",
            },
        ]
        report = detector.scan_documents(docs)
        assert report.documents_analyzed == 2
