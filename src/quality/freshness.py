"""
Freshness Indicators for CoreRag.

Tracks content freshness and provides staleness warnings:
- Time since last modification
- Time since last access
- Content age classification
- Staleness alerts in search results
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import os

logger = logging.getLogger(__name__)


class FreshnessLevel(Enum):
    """Content freshness levels."""
    FRESH = "fresh"       # Modified recently (< 7 days)
    CURRENT = "current"   # Relatively recent (< 30 days)
    AGING = "aging"       # Getting old (< 90 days)
    STALE = "stale"       # Old (< 1 year)
    ARCHIVE = "archive"   # Very old (> 1 year)


@dataclass
class FreshnessInfo:
    """Freshness information for a document."""
    file_path: str
    modified_at: datetime
    accessed_at: Optional[datetime]
    created_at: Optional[datetime]
    age_days: int
    freshness_level: FreshnessLevel
    is_stale: bool
    staleness_reason: Optional[str] = None


class FreshnessIndicator:
    """
    Track and indicate content freshness.

    Features:
    - Classify documents by age
    - Add freshness indicators to search results
    - Alert on stale content
    - Track access patterns
    """

    # Default thresholds (days)
    FRESH_THRESHOLD = 7
    CURRENT_THRESHOLD = 30
    AGING_THRESHOLD = 90
    STALE_THRESHOLD = 365

    def __init__(
        self,
        fresh_days: int = 7,
        current_days: int = 30,
        aging_days: int = 90,
        stale_days: int = 365,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize freshness indicator.

        Args:
            fresh_days: Days to consider "fresh"
            current_days: Days to consider "current"
            aging_days: Days to consider "aging"
            stale_days: Days to consider "stale"
            state_dir: Directory for access tracking
        """
        self.fresh_days = fresh_days
        self.current_days = current_days
        self.aging_days = aging_days
        self.stale_days = stale_days

        self.state_dir = state_dir or Path.home() / ".corerag" / "freshness"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Access tracking
        self._access_log: Dict[str, datetime] = {}
        self._load_access_log()

    def get_freshness(self, file_path: Path) -> FreshnessInfo:
        """
        Get freshness information for a file.

        Args:
            file_path: Path to the file

        Returns:
            FreshnessInfo with freshness details
        """
        file_path = Path(file_path)

        if not file_path.exists():
            return FreshnessInfo(
                file_path=str(file_path),
                modified_at=datetime.min,
                accessed_at=None,
                created_at=None,
                age_days=999999,
                freshness_level=FreshnessLevel.ARCHIVE,
                is_stale=True,
                staleness_reason="File not found",
            )

        stat = file_path.stat()

        modified_at = datetime.fromtimestamp(stat.st_mtime)
        accessed_at = self._access_log.get(str(file_path))
        created_at = datetime.fromtimestamp(stat.st_ctime)

        age_days = (datetime.now() - modified_at).days

        # Determine freshness level
        if age_days <= self.fresh_days:
            level = FreshnessLevel.FRESH
        elif age_days <= self.current_days:
            level = FreshnessLevel.CURRENT
        elif age_days <= self.aging_days:
            level = FreshnessLevel.AGING
        elif age_days <= self.stale_days:
            level = FreshnessLevel.STALE
        else:
            level = FreshnessLevel.ARCHIVE

        # Determine if stale
        is_stale = level in {FreshnessLevel.STALE, FreshnessLevel.ARCHIVE}
        staleness_reason = None

        if is_stale:
            if age_days > self.stale_days:
                staleness_reason = f"Content is {age_days} days old (over {self.stale_days} days)"

        return FreshnessInfo(
            file_path=str(file_path),
            modified_at=modified_at,
            accessed_at=accessed_at,
            created_at=created_at,
            age_days=age_days,
            freshness_level=level,
            is_stale=is_stale,
            staleness_reason=staleness_reason,
        )

    def log_access(self, file_path: Path) -> None:
        """Log that a file was accessed (e.g., returned in search)."""
        self._access_log[str(file_path)] = datetime.now()
        self._save_access_log()

    def enrich_search_results(
        self,
        results: List[Dict],
        file_path_key: str = "source_path",
    ) -> List[Dict]:
        """
        Add freshness indicators to search results.

        Args:
            results: Search results
            file_path_key: Key for file path in results

        Returns:
            Results with added freshness info
        """
        enriched = []

        for result in results:
            file_path = result.get(file_path_key)
            if file_path:
                freshness = self.get_freshness(Path(file_path))

                result["freshness"] = {
                    "level": freshness.freshness_level.value,
                    "age_days": freshness.age_days,
                    "is_stale": freshness.is_stale,
                    "modified_at": freshness.modified_at.isoformat(),
                    "indicator": self._get_indicator(freshness),
                }

                # Log access
                self.log_access(Path(file_path))

            enriched.append(result)

        return enriched

    def get_stale_content(
        self,
        directory: Path,
        recursive: bool = True,
    ) -> List[FreshnessInfo]:
        """
        Find stale content in a directory.

        Args:
            directory: Directory to scan
            recursive: Scan recursively

        Returns:
            List of stale files
        """
        stale = []

        pattern = "**/*" if recursive else "*"
        for file_path in Path(directory).glob(pattern):
            if file_path.is_file():
                freshness = self.get_freshness(file_path)
                if freshness.is_stale:
                    stale.append(freshness)

        # Sort by age (oldest first)
        stale.sort(key=lambda x: x.age_days, reverse=True)

        return stale

    def get_freshness_summary(self, directory: Path) -> Dict[str, Any]:
        """
        Get freshness summary for a directory.

        Returns:
            Summary with counts by freshness level
        """
        counts = {level.value: 0 for level in FreshnessLevel}
        total_age = 0
        file_count = 0

        for file_path in Path(directory).rglob("*"):
            if file_path.is_file():
                freshness = self.get_freshness(file_path)
                counts[freshness.freshness_level.value] += 1
                total_age += freshness.age_days
                file_count += 1

        return {
            "total_files": file_count,
            "by_level": counts,
            "avg_age_days": total_age / file_count if file_count > 0 else 0,
            "stale_count": counts.get("stale", 0) + counts.get("archive", 0),
            "fresh_percentage": (
                counts.get("fresh", 0) / file_count * 100
                if file_count > 0 else 0
            ),
        }

    def _get_indicator(self, freshness: FreshnessInfo) -> str:
        """Get visual indicator for freshness level."""
        indicators = {
            FreshnessLevel.FRESH: "🟢",      # Green
            FreshnessLevel.CURRENT: "🔵",    # Blue
            FreshnessLevel.AGING: "🟡",      # Yellow
            FreshnessLevel.STALE: "🟠",      # Orange
            FreshnessLevel.ARCHIVE: "🔴",    # Red
        }
        return indicators.get(freshness.freshness_level, "⚪")

    def _load_access_log(self) -> None:
        """Load access log from disk."""
        log_file = self.state_dir / "access_log.json"
        if log_file.exists():
            try:
                with open(log_file) as f:
                    data = json.load(f)
                    self._access_log = {
                        k: datetime.fromisoformat(v)
                        for k, v in data.items()
                    }
            except Exception as e:
                logger.warning(f"Failed to load access log: {e}")

    def _save_access_log(self) -> None:
        """Save access log to disk."""
        log_file = self.state_dir / "access_log.json"

        try:
            with open(log_file, "w") as f:
                json.dump({
                    k: v.isoformat()
                    for k, v in self._access_log.items()
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save access log: {e}")
