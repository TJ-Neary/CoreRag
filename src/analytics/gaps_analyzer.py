"""Knowledge Gaps Analyzer — identify missing knowledge proactively.

Analyzes failed searches, sparse folders, and topic imbalances
to recommend areas where the knowledge base could be improved.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.config import ARCHIVE_PATH, VAULT_PATH

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGap:
    """A detected gap in the knowledge base."""

    topic: str
    gap_type: str  # "search_failure", "sparse_coverage", "topic_imbalance"
    evidence: str
    confidence: float
    suggested_action: str


class GapsAnalyzer:
    """Analyzes the knowledge base for gaps and improvement opportunities."""

    def __init__(
        self,
        vault_path: Optional[Path] = None,
        archive_path: Optional[Path] = None,
        analytics=None,
        db=None,
    ):
        self.vault_path = vault_path or VAULT_PATH
        self.archive_path = archive_path or ARCHIVE_PATH
        self.analytics = analytics
        self.db = db

    def identify_search_gaps(self, limit: int = 20) -> list[KnowledgeGap]:
        """Find topics where searches consistently fail."""
        if not self.analytics:
            return []

        failed = self.analytics.get_failed_queries(limit=limit)
        if not failed:
            return []

        # Group by topic pattern (first 3 meaningful words)
        topic_counts: dict[str, list] = {}
        for event in failed:
            words = event.query.lower().split()
            # Skip stop words for topic extraction
            meaningful = [w for w in words if len(w) > 2 and w not in _STOP_WORDS]
            topic = " ".join(meaningful[:3]) if meaningful else event.query[:30]
            topic_counts.setdefault(topic, []).append(event)

        gaps = []
        for topic, events in sorted(topic_counts.items(), key=lambda x: -len(x[1])):
            avg_score = sum(e.top_result_score for e in events) / len(events)
            gaps.append(
                KnowledgeGap(
                    topic=topic,
                    gap_type="search_failure",
                    evidence=f"Failed {len(events)} time(s), avg score: {avg_score:.2f}",
                    confidence=min(1.0, len(events) / 5),
                    suggested_action=f"Add documents about '{topic}'",
                )
            )

        return gaps[:limit]

    def identify_sparse_folders(self, min_docs: int = 3) -> list[dict]:
        """Find archive folders with very few documents."""
        knowledge_dir = self.archive_path / "Knowledge"
        if not knowledge_dir.exists():
            knowledge_dir = self.archive_path

        if not knowledge_dir.exists():
            return []

        sparse = []
        for folder in sorted(knowledge_dir.iterdir()):
            if not folder.is_dir():
                continue
            doc_count = sum(1 for f in folder.rglob("*") if f.is_file())
            if doc_count < min_docs:
                sparse.append(
                    {"folder": folder.name, "document_count": doc_count, "path": str(folder)}
                )

        return sparse

    def identify_topic_imbalances(self) -> list[KnowledgeGap]:
        """Find topics with significantly fewer documents than average."""
        if not self.db:
            return []

        try:
            table = self.db.open_table("children")
            # Count documents by tag
            data = table.to_pandas()
            if "tags" not in data.columns or data.empty:
                return []

            tag_counts: dict[str, int] = {}
            for tags_str in data["tags"].dropna():
                for tag in str(tags_str).strip(",").split(","):
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            if not tag_counts:
                return []

            avg_count = sum(tag_counts.values()) / len(tag_counts)
            threshold = avg_count * 0.3

            gaps = []
            for tag, count in sorted(tag_counts.items(), key=lambda x: x[1]):
                if count < threshold:
                    gaps.append(
                        KnowledgeGap(
                            topic=tag,
                            gap_type="topic_imbalance",
                            evidence=f"Only {count} docs vs {avg_count:.0f} average",
                            confidence=0.7,
                            suggested_action=f"Add more content tagged '{tag}'",
                        )
                    )

            return gaps

        except Exception as e:
            logger.debug(f"Topic imbalance analysis failed: {e}")
            return []

    def get_comprehensive_analysis(self) -> dict[str, Any]:
        """Run all gap analyses and return aggregated results."""
        search_gaps = self.identify_search_gaps()
        sparse = self.identify_sparse_folders()
        imbalances = self.identify_topic_imbalances()

        all_gaps = search_gaps + imbalances
        all_gaps.sort(key=lambda g: g.confidence, reverse=True)

        return {
            "search_gaps": [
                {"topic": g.topic, "evidence": g.evidence, "action": g.suggested_action}
                for g in search_gaps[:5]
            ],
            "sparse_areas": sparse[:10],
            "topic_imbalances": [
                {"topic": g.topic, "evidence": g.evidence, "action": g.suggested_action}
                for g in imbalances[:5]
            ],
            "top_recommendations": [
                {
                    "topic": g.topic,
                    "type": g.gap_type,
                    "action": g.suggested_action,
                    "confidence": g.confidence,
                }
                for g in all_gaps[:5]
            ],
            "summary": {
                "search_failures": len(search_gaps),
                "sparse_folders": len(sparse),
                "imbalanced_topics": len(imbalances),
            },
        }


_STOP_WORDS = {
    "the",
    "is",
    "at",
    "which",
    "on",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "with",
    "to",
    "for",
    "of",
    "not",
    "no",
    "can",
    "had",
    "has",
    "have",
    "was",
    "were",
    "been",
    "be",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "how",
    "what",
    "where",
    "when",
    "why",
    "who",
    "whom",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "my",
    "your",
    "our",
    "their",
    "from",
    "by",
    "about",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "under",
    "are",
}
