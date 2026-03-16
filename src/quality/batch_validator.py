"""Automated quality gates for the ingestion pipeline.

Pre-commit: validate_batch() — anomaly detection after batch analysis.
Post-commit: validate_commit() — integrity check after each file commit.
Startup: validate_database_integrity() — orphan cleanup on server start.
"""

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src import config

logger = logging.getLogger(__name__)


@dataclass
class BatchQualityReport:
    """Result of pre-commit batch validation."""

    total_items: int = 0
    sensitive_count: int = 0
    sensitive_rate: float = 0.0
    extraction_warnings: list[str] = field(default_factory=list)
    duplicate_count: int = 0
    error_count: int = 0
    error_files: list[str] = field(default_factory=list)
    extraction_details: list[dict] = field(default_factory=list)  # NEW
    error_details: list[dict] = field(default_factory=list)  # NEW
    warnings: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class CommitValidationResult:
    """Result of post-commit integrity check."""

    source_path: str = ""
    passed: bool = True
    parent_count: int = 0
    child_count: int = 0
    orphans_cleaned: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_batch(manifest: dict) -> BatchQualityReport:
    """Pre-commit quality gate — runs after batch analysis completes.

    Checks PII sensitivity rate, extraction quality, duplicates, errors.
    Saves report to STATE_DIR/batch_quality_report.json.
    """
    report = BatchQualityReport()

    try:
        items = list(manifest.values())
        report.total_items = len(items)

        if not items:
            return report

        for item in items:
            meta = item.get("metadata", {})

            # PII sensitivity
            if meta.get("is_sensitive"):
                report.sensitive_count += 1

            # Text extraction check
            redacted = item.get("redacted_text", "")
            orig_path = item.get("original_path", "")
            if orig_path:
                try:
                    file_size = Path(orig_path).stat().st_size if Path(orig_path).exists() else 0
                except Exception:
                    file_size = 0
                if file_size > 10240 and len(redacted) < 100:
                    filename = Path(orig_path).name
                    report.extraction_warnings.append(filename)
                    report.extraction_details.append({
                        "filename": filename,
                        "error_type": "extraction_failed",
                        "message": f"Extracted only {len(redacted)} chars from {file_size}+ byte file",
                    })

            # Duplicate check (reads existing duplicate_info from processor)
            if meta.get("duplicate_info"):
                report.duplicate_count += 1

            # Error check
            if item.get("status") == "error":
                report.error_count += 1
                error_filename = Path(orig_path).name if orig_path else "unknown"
                report.error_files.append(error_filename)
                report.error_details.append({
                    "filename": error_filename,
                    "error_type": "pipeline_error",
                    "message": item.get("error", "Unknown error"),
                })

        report.sensitive_rate = (
            report.sensitive_count / report.total_items if report.total_items else 0
        )

        # Generate warnings
        if report.sensitive_rate > 0.5:
            report.warnings.append(
                f"High PII rate: {report.sensitive_count}/{report.total_items} "
                f"({report.sensitive_rate:.0%}) flagged as sensitive — review detections"
            )
            report.passed = False

        if report.extraction_warnings:
            report.warnings.append(
                f"Possible extraction failures: {len(report.extraction_warnings)} files "
                f"produced <100 chars from >10KB files"
            )
            report.passed = False

        if report.error_count:
            report.warnings.append(
                f"{report.error_count} files failed: {', '.join(report.error_files[:5])}"
            )
            report.passed = False

        if report.total_items > 5 and report.duplicate_count / report.total_items > 0.8:
            report.warnings.append(
                f"Most files already indexed: {report.duplicate_count}/{report.total_items} duplicates"
            )

        # Save report
        report_path = config.STATE_DIR / "batch_quality_report.json"
        report_path.write_text(json.dumps(dataclasses.asdict(report), indent=2))

        if report.warnings:
            for w in report.warnings:
                logger.warning(f"Batch quality: {w}")
        else:
            logger.info(f"Batch quality: PASSED ({report.total_items} items)")

    except Exception as e:
        logger.warning(f"Batch validation failed (non-fatal): {e}")

    return report


def validate_commit(source_path: str, db=None, skip_rag: bool = False) -> CommitValidationResult:
    """Post-commit integrity check — runs after each file is committed.

    Verifies parent-child integrity in LanceDB. Auto-cleans orphaned parents.
    """
    result = CommitValidationResult(source_path=source_path)

    if skip_rag:
        return result

    try:
        import warnings as _warnings

        import lancedb

        if db is None:
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore")
                db = lancedb.connect(str(config.DB_PATH))

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")

            if "parent_chunks" in db.table_names():
                result.parent_count = db.open_table("parent_chunks").count_rows(
                    f"source_path = '{source_path}'"
                )
            if "child_chunks" in db.table_names():
                result.child_count = db.open_table("child_chunks").count_rows(
                    f"source_path = '{source_path}'"
                )

        if result.child_count == 0:
            result.errors.append(f"No child chunks created for {source_path}")
            result.passed = False

        if result.parent_count > 0 and result.child_count == 0:
            try:
                db.open_table("parent_chunks").delete(f"source_path = '{source_path}'")
                result.orphans_cleaned = result.parent_count
                result.warnings.append(
                    f"Auto-cleaned {result.parent_count} orphaned parents for {source_path}"
                )
                logger.warning(
                    f"Commit validation: cleaned {result.parent_count} orphaned parents "
                    f"for {source_path}"
                )
            except Exception as e:
                result.errors.append(f"Failed to clean orphans: {e}")

        if result.passed:
            logger.debug(
                f"Commit validation: {source_path} OK "
                f"({result.parent_count}p, {result.child_count}c)"
            )

    except Exception as e:
        logger.warning(f"Commit validation failed (non-fatal): {e}")

    return result


def validate_database_integrity(db=None) -> dict:
    """Startup health check — find and clean orphaned parent entries.

    Complements HealthChecker.quick_check() which checks table existence.
    This checks parent-child referential integrity.
    """
    try:
        import warnings as _warnings

        import lancedb

        if db is None:
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore")
                db = lancedb.connect(str(config.DB_PATH))

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")

            if "parent_chunks" not in db.table_names() or "child_chunks" not in db.table_names():
                return {"status": "skipped", "reason": "tables not found"}

            parent_sources = set(
                db.open_table("parent_chunks").to_arrow().column("source_path").to_pylist()
            )
            child_sources = set(
                db.open_table("child_chunks").to_arrow().column("source_path").to_pylist()
            )

        orphaned = parent_sources - child_sources
        total_cleaned = 0

        if orphaned:
            parent_table = db.open_table("parent_chunks")
            for source in orphaned:
                count = parent_table.count_rows(f"source_path = '{source}'")
                parent_table.delete(f"source_path = '{source}'")
                total_cleaned += count

            logger.info(
                f"Startup integrity: cleaned {total_cleaned} orphaned parents "
                f"from {len(orphaned)} files"
            )

        return {
            "status": "ok",
            "orphaned_files": len(orphaned),
            "orphaned_parents_cleaned": total_cleaned,
            "parent_sources": len(parent_sources - orphaned),
            "child_sources": len(child_sources),
        }

    except Exception as e:
        logger.warning(f"Database integrity check failed (non-fatal): {e}")
        return {"status": "error", "error": str(e)}
