"""Quality assurance module for CoreRag.

Imports are lazy to avoid pulling in optional dependencies (e.g., aiohttp)
when only a subset of quality tools is needed.
"""


def __getattr__(name):
    if name in ("FreshnessIndicator", "FreshnessInfo", "FreshnessLevel"):
        from src.quality import freshness

        return getattr(freshness, name)
    if name in ("DuplicateDetector", "DuplicateMatch", "DuplicateReport"):
        from src.quality import duplicate_detector

        return getattr(duplicate_detector, name)
    if name in ("LinkChecker", "LinkCheckResult", "LinkRotReport", "LinkStatus", "check_links"):
        from src.quality import link_checker

        return getattr(link_checker, name)
    if name in (
        "ConflictDetector",
        "Conflict",
        "ConflictReport",
        "ConflictType",
        "ConflictSeverity",
        "detect_conflicts",
    ):
        from src.quality import conflict_detector

        return getattr(conflict_detector, name)
    raise AttributeError(f"module 'src.quality' has no attribute {name!r}")


__all__ = [
    "FreshnessIndicator",
    "FreshnessInfo",
    "FreshnessLevel",
    "DuplicateDetector",
    "DuplicateMatch",
    "DuplicateReport",
    "LinkChecker",
    "LinkCheckResult",
    "LinkRotReport",
    "LinkStatus",
    "check_links",
    "ConflictDetector",
    "Conflict",
    "ConflictReport",
    "ConflictType",
    "ConflictSeverity",
    "detect_conflicts",
]
