"""Quality assurance module for PKM.

Imports are lazy to avoid pulling in optional dependencies (e.g., aiohttp)
when only a subset of quality tools is needed.
"""


def __getattr__(name):
    if name in ("FreshnessIndicator", "FreshnessInfo", "FreshnessLevel"):
        from src.quality.freshness import FreshnessIndicator, FreshnessInfo, FreshnessLevel
        return locals()[name]
    if name in ("DuplicateDetector", "DuplicateMatch", "DuplicateReport"):
        from src.quality.duplicate_detector import DuplicateDetector, DuplicateMatch, DuplicateReport
        return locals()[name]
    if name in ("LinkChecker", "LinkCheckResult", "LinkRotReport", "LinkStatus", "check_links"):
        from src.quality.link_checker import LinkChecker, LinkCheckResult, LinkRotReport, LinkStatus, check_links
        return locals()[name]
    if name in ("ConflictDetector", "Conflict", "ConflictReport", "ConflictType", "ConflictSeverity", "detect_conflicts"):
        from src.quality.conflict_detector import ConflictDetector, Conflict, ConflictReport, ConflictType, ConflictSeverity, detect_conflicts
        return locals()[name]
    raise AttributeError(f"module 'src.quality' has no attribute {name!r}")


__all__ = [
    "FreshnessIndicator", "FreshnessInfo", "FreshnessLevel",
    "DuplicateDetector", "DuplicateMatch", "DuplicateReport",
    "LinkChecker", "LinkCheckResult", "LinkRotReport", "LinkStatus", "check_links",
    "ConflictDetector", "Conflict", "ConflictReport", "ConflictType", "ConflictSeverity", "detect_conflicts",
]
