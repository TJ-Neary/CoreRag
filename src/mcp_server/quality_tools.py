"""Quality tool group — conflict detection, gaps analysis, golden set, ingestion queue."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class QualityTools:
    """Quality and analysis tools for the knowledge base."""

    def __init__(self, db=None, vault_root=None, conflict_detector=None, query_analytics=None):
        self.db = db
        self.vault_root = vault_root or Path.cwd()
        self._conflict_detector = conflict_detector
        self._query_analytics = query_analytics

    async def detect_conflicts(self, path: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Scan documents for contradictions, numeric mismatches, and outdated info."""
        if not self._conflict_detector:
            return {"error": "Conflict detector not initialized"}

        try:
            scan_path = Path(path) if path else self.vault_root
            if not scan_path.exists():
                return {"error": f"Path not found: {scan_path}"}

            report = self._conflict_detector.scan_directory(scan_path, recursive=True)

            return {
                "path": str(scan_path),
                "documents_analyzed": report.documents_analyzed,
                "conflicts_found": report.conflicts_found,
                "by_type": report.by_type,
                "by_severity": report.by_severity,
                "conflicts": [
                    {
                        "type": c.conflict_type.value,
                        "severity": c.severity.value,
                        "description": c.description,
                        "topic": c.topic,
                        "confidence": c.confidence,
                        "evidence_a": {
                            "file": c.evidence_a.file_path,
                            "content": c.evidence_a.content[:300],
                        },
                        "evidence_b": {
                            "file": c.evidence_b.file_path,
                            "content": c.evidence_b.content[:300],
                        },
                        "resolution": c.resolution_suggestion,
                    }
                    for c in report.conflicts[:limit]
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    async def analyze_knowledge_gaps(self) -> Dict[str, Any]:
        """Analyze the knowledge base for gaps and improvement opportunities."""
        from src.analytics.gaps_analyzer import GapsAnalyzer

        analyzer = GapsAnalyzer(analytics=self._query_analytics, db=self.db)
        return analyzer.get_comprehensive_analysis()

    async def get_golden_suggestions(self, limit: int = 10) -> Dict[str, Any]:
        """Get analytics-based suggestions for golden set entries."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        suggestions = mgr.get_suggestions(limit=limit)
        return {
            "suggestions": suggestions,
            "count": len(suggestions),
            "current_entries": mgr.entry_count,
        }

    async def approve_golden_suggestion(self, query: str) -> Dict[str, Any]:
        """Approve a golden set suggestion from analytics."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        success = mgr.approve_suggestion(query)
        if success:
            return {"status": "approved", "query": query, "total_entries": mgr.entry_count}
        return {"status": "failed", "error": f"Query not found in suggestions: {query}"}

    async def list_golden_entries(
        self, limit: int = 50, source: Optional[str] = None
    ) -> Dict[str, Any]:
        """List current golden set entries."""
        from src.quality.golden_set_manager import GoldenSetManager

        mgr = GoldenSetManager(analytics=self._query_analytics)
        entries = mgr.list_entries(source_filter=source, limit=limit)
        return {"entries": entries, "total": mgr.entry_count}

    async def get_ingestion_queue(self) -> Dict[str, Any]:
        """Get current ingestion queue status."""
        try:
            from src.staging import STAGING_MANIFEST_PATH

            if STAGING_MANIFEST_PATH.exists():
                with open(STAGING_MANIFEST_PATH) as f:
                    manifest = json.load(f)
                pending = sum(1 for v in manifest.values() if v.get("status") == "pending")
                processing = sum(1 for v in manifest.values() if v.get("status") == "processing")
                completed = sum(1 for v in manifest.values() if v.get("status") == "completed")
                return {
                    "pending": pending,
                    "processing": processing,
                    "completed": completed,
                    "total": len(manifest),
                }
        except Exception as e:
            logger.error(f"Error reading ingestion queue: {e}")

        return {"pending": 0, "processing": 0, "completed": 0, "total": 0}
