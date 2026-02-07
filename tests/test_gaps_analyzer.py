"""Tests for the GapsAnalyzer — knowledge gap detection."""

from dataclasses import dataclass

from src.analytics.gaps_analyzer import GapsAnalyzer


@dataclass
class FakeFailedQuery:
    query: str
    top_result_score: float


class TestIdentifySearchGaps:
    def test_no_analytics_returns_empty(self):
        analyzer = GapsAnalyzer(analytics=None)
        assert analyzer.identify_search_gaps() == []

    def test_no_failed_queries(self):
        analytics = type("A", (), {"get_failed_queries": lambda self, limit=20: []})()
        analyzer = GapsAnalyzer(analytics=analytics)
        assert analyzer.identify_search_gaps() == []

    def test_groups_by_topic_pattern(self):
        failures = [
            FakeFailedQuery("kubernetes deployment guide", 0.1),
            FakeFailedQuery("kubernetes deployment tutorial", 0.15),
            FakeFailedQuery("react component testing", 0.2),
        ]
        analytics = type("A", (), {"get_failed_queries": lambda self, limit=20: failures})()
        analyzer = GapsAnalyzer(analytics=analytics)
        gaps = analyzer.identify_search_gaps()
        assert len(gaps) >= 2
        topics = [g.topic for g in gaps]
        assert any("kubernetes" in t for t in topics)

    def test_filters_stop_words(self):
        failures = [
            FakeFailedQuery("how to the configure the server", 0.1),
        ]
        analytics = type("A", (), {"get_failed_queries": lambda self, limit=20: failures})()
        analyzer = GapsAnalyzer(analytics=analytics)
        gaps = analyzer.identify_search_gaps()
        assert len(gaps) == 1
        # "how", "to", "the" should be stripped
        assert "how" not in gaps[0].topic
        assert "the" not in gaps[0].topic

    def test_confidence_capped_at_one(self):
        failures = [FakeFailedQuery("same topic query", 0.1) for _ in range(10)]
        analytics = type("A", (), {"get_failed_queries": lambda self, limit=20: failures})()
        analyzer = GapsAnalyzer(analytics=analytics)
        gaps = analyzer.identify_search_gaps()
        assert gaps[0].confidence <= 1.0


class TestIdentifySparseFolders:
    def test_no_archive_returns_empty(self, tmp_path):
        analyzer = GapsAnalyzer(archive_path=tmp_path / "nonexistent")
        assert analyzer.identify_sparse_folders() == []

    def test_finds_sparse_folders(self, tmp_path):
        knowledge = tmp_path / "Knowledge"
        # Sparse folder: 1 doc
        sparse = knowledge / "Sparse"
        sparse.mkdir(parents=True)
        (sparse / "doc1.md").write_text("content")
        # Full folder: 5 docs
        full = knowledge / "Full"
        full.mkdir()
        for i in range(5):
            (full / f"doc{i}.md").write_text("content")

        analyzer = GapsAnalyzer(archive_path=tmp_path)
        results = analyzer.identify_sparse_folders(min_docs=3)
        assert len(results) == 1
        assert results[0]["folder"] == "Sparse"
        assert results[0]["document_count"] == 1

    def test_ignores_files_at_root(self, tmp_path):
        knowledge = tmp_path / "Knowledge"
        knowledge.mkdir()
        (knowledge / "readme.txt").write_text("not a folder")
        analyzer = GapsAnalyzer(archive_path=tmp_path)
        assert analyzer.identify_sparse_folders() == []


class TestComprehensiveAnalysis:
    def test_returns_all_sections(self, tmp_path):
        analyzer = GapsAnalyzer(
            vault_path=tmp_path, archive_path=tmp_path / "nonexistent", analytics=None, db=None
        )
        result = analyzer.get_comprehensive_analysis()
        assert "search_gaps" in result
        assert "sparse_areas" in result
        assert "topic_imbalances" in result
        assert "top_recommendations" in result
        assert "summary" in result
