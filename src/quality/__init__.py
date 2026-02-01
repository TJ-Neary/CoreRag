"""Quality assurance module for PKM."""

from src.quality.freshness import (
    FreshnessIndicator,
    FreshnessInfo,
    FreshnessLevel,
)
from src.quality.duplicate_detector import (
    DuplicateDetector,
    DuplicateMatch,
    DuplicateReport,
)
from src.quality.link_checker import (
    LinkChecker,
    LinkCheckResult,
    LinkRotReport,
    LinkStatus,
    check_links,
)
from src.quality.conflict_detector import (
    ConflictDetector,
    Conflict,
    ConflictReport,
    ConflictType,
    ConflictSeverity,
    detect_conflicts,
)

__all__ = [
    # Freshness
    "FreshnessIndicator",
    "FreshnessInfo",
    "FreshnessLevel",
    # Duplicates
    "DuplicateDetector",
    "DuplicateMatch",
    "DuplicateReport",
    # Links
    "LinkChecker",
    "LinkCheckResult",
    "LinkRotReport",
    "LinkStatus",
    "check_links",
    # Conflicts
    "ConflictDetector",
    "Conflict",
    "ConflictReport",
    "ConflictType",
    "ConflictSeverity",
    "detect_conflicts",
]
