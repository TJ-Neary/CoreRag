# Ingestion Quality Gates — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automated pre-commit and post-commit quality validation to the ingestion pipeline — detect PII false positive anomalies, extraction failures, and orphaned database entries.

**Architecture:** New `src/quality/batch_validator.py` module with three functions: `validate_batch()` (pre-commit), `validate_commit()` (post-commit), `validate_database_integrity()` (startup). Integrated into existing pipeline hooks at batch_processor completion, executor commit, and server lifespan.

**Tech Stack:** Python 3.12+, LanceDB, FastAPI

**Spec:** `docs/superpowers/specs/2026-03-15-ingestion-quality-gates-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/quality/batch_validator.py` | Create | All 3 validation functions + dataclasses |
| `src/batch_processor.py` | Modify (~line 178) | Call `validate_batch()` after analysis |
| `src/executor.py` | Modify (~line 297) | Call `validate_commit()` after commit |
| `src/server.py` | Modify (lifespan) | Call `validate_database_integrity()` at startup |
| `src/api/dashboard_routes.py` | Modify | Add `GET /api/batch-quality` endpoint |
| `tests/test_batch_validator.py` | Create | Tests for all 3 validation functions |

---

### Task 1: Create batch_validator.py with data models and validate_batch()

**Files:**
- Create: `src/quality/batch_validator.py`
- Create: `tests/test_batch_validator.py`

- [ ] **Step 1: Create batch_validator.py with dataclasses and validate_batch()**

```python
"""Automated quality gates for the ingestion pipeline.

Pre-commit: validate_batch() — anomaly detection after batch analysis.
Post-commit: validate_commit() — integrity check after each file commit.
Startup: validate_database_integrity() — orphan cleanup on server start.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src import config

logger = logging.getLogger(__name__)


@dataclass
class BatchQualityReport:
    total_items: int = 0
    sensitive_count: int = 0
    sensitive_rate: float = 0.0
    extraction_warnings: list[str] = field(default_factory=list)
    duplicate_count: int = 0
    error_count: int = 0
    error_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class CommitValidationResult:
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
    """
    report = BatchQualityReport()

    try:
        items = list(manifest.values())
        report.total_items = len(items)

        if not items:
            return report

        # PII sensitivity rate
        for item in items:
            meta = item.get("metadata", {})
            if meta.get("is_sensitive"):
                report.sensitive_count += 1

            # Text extraction check — flag files with suspiciously short text
            redacted = item.get("redacted_text", "")
            orig_path = item.get("original_path", "")
            if orig_path:
                try:
                    file_size = Path(orig_path).stat().st_size if Path(orig_path).exists() else 0
                except Exception:
                    file_size = 0
                if file_size > 10240 and len(redacted) < 100:
                    report.extraction_warnings.append(Path(orig_path).name)

            # Duplicate check (reads existing duplicate_info from processor)
            if item.get("metadata", {}).get("duplicate_info"):
                report.duplicate_count += 1

            # Error check
            if item.get("status") == "error":
                report.error_count += 1
                report.error_files.append(Path(orig_path).name if orig_path else "unknown")

        report.sensitive_rate = report.sensitive_count / report.total_items if report.total_items else 0

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
        report_path.write_text(json.dumps({
            "total_items": report.total_items,
            "sensitive_count": report.sensitive_count,
            "sensitive_rate": report.sensitive_rate,
            "extraction_warnings": report.extraction_warnings,
            "duplicate_count": report.duplicate_count,
            "error_count": report.error_count,
            "error_files": report.error_files,
            "warnings": report.warnings,
            "passed": report.passed,
        }, indent=2))

        if report.warnings:
            for w in report.warnings:
                logger.warning(f"Batch quality: {w}")
        else:
            logger.info(f"Batch quality: PASSED ({report.total_items} items)")

    except Exception as e:
        logger.warning(f"Batch validation failed (non-fatal): {e}")

    return report
```

- [ ] **Step 2: Write tests**

```python
"""Tests for src/quality/batch_validator.py"""
import pytest
from src.quality.batch_validator import validate_batch, BatchQualityReport


class TestValidateBatch:
    def test_empty_manifest(self):
        report = validate_batch({})
        assert report.passed is True
        assert report.total_items == 0

    def test_normal_batch_passes(self):
        manifest = {
            "1": {"metadata": {"is_sensitive": False}, "redacted_text": "x" * 500, "original_path": "/tmp/a.pdf", "status": "pending"},
            "2": {"metadata": {"is_sensitive": False}, "redacted_text": "y" * 500, "original_path": "/tmp/b.pdf", "status": "pending"},
        }
        report = validate_batch(manifest)
        assert report.passed is True
        assert report.sensitive_rate == 0.0

    def test_high_pii_rate_warns(self):
        manifest = {
            str(i): {"metadata": {"is_sensitive": True}, "redacted_text": "x" * 500, "original_path": f"/tmp/{i}.pdf", "status": "pending"}
            for i in range(10)
        }
        report = validate_batch(manifest)
        assert report.passed is False
        assert report.sensitive_rate == 1.0
        assert any("PII rate" in w for w in report.warnings)

    def test_errors_flagged(self):
        manifest = {
            "1": {"metadata": {}, "redacted_text": "", "original_path": "/tmp/a.epub", "status": "error"},
        }
        report = validate_batch(manifest)
        assert report.error_count == 1
        assert report.passed is False
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_batch_validator.py -v --tb=short`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/quality/batch_validator.py tests/test_batch_validator.py
git commit -m "feat: batch quality validation — PII rate, extraction, error detection"
```

---

### Task 2: Add validate_commit() and validate_database_integrity()

**Files:**
- Modify: `src/quality/batch_validator.py`
- Modify: `tests/test_batch_validator.py`

- [ ] **Step 1: Add validate_commit()**

Append to `batch_validator.py`:

```python
def validate_commit(source_path: str, db=None, skip_rag: bool = False) -> CommitValidationResult:
    """Post-commit integrity check — runs after each file is committed.

    Verifies parent-child integrity in LanceDB.
    Auto-cleans orphaned parents.
    """
    result = CommitValidationResult(source_path=source_path)

    if skip_rag:
        # File opted out of RAG indexing — nothing to validate
        return result

    try:
        import lancedb
        import warnings as _warnings

        if db is None:
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore")
                db = lancedb.connect(str(config.DB_PATH))

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")

            # Count parents and children for this source
            if "parent_chunks" in db.table_names():
                result.parent_count = db.open_table("parent_chunks").count_rows(
                    f"source_path = '{source_path}'"
                )
            if "child_chunks" in db.table_names():
                result.child_count = db.open_table("child_chunks").count_rows(
                    f"source_path = '{source_path}'"
                )

        # Integrity checks
        if result.child_count == 0:
            result.errors.append(f"No child chunks created for {source_path}")
            result.passed = False

        if result.parent_count > 0 and result.child_count == 0:
            # Orphaned parents — auto-clean
            try:
                db.open_table("parent_chunks").delete(f"source_path = '{source_path}'")
                result.orphans_cleaned = result.parent_count
                result.warnings.append(
                    f"Auto-cleaned {result.parent_count} orphaned parents for {source_path}"
                )
                logger.warning(f"Commit validation: cleaned {result.parent_count} orphaned parents for {source_path}")
            except Exception as e:
                result.errors.append(f"Failed to clean orphans: {e}")

        if result.passed:
            logger.debug(f"Commit validation: {source_path} OK ({result.parent_count}p, {result.child_count}c)")

    except Exception as e:
        logger.warning(f"Commit validation failed (non-fatal): {e}")

    return result


def validate_database_integrity(db=None) -> dict:
    """Startup health check — find and clean orphaned parent entries.

    Complements HealthChecker.quick_check() — that checks table existence,
    this checks parent-child referential integrity.
    """
    try:
        import lancedb
        import warnings as _warnings

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
                f"Startup integrity: cleaned {total_cleaned} orphaned parents from {len(orphaned)} files"
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
```

- [ ] **Step 2: Add tests**

```python
class TestValidateCommit:
    def test_skip_rag(self):
        from src.quality.batch_validator import validate_commit
        result = validate_commit("test.pdf", skip_rag=True)
        assert result.passed is True

    def test_no_children_fails(self):
        from unittest.mock import MagicMock
        from src.quality.batch_validator import validate_commit

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["parent_chunks", "child_chunks"]

        mock_parent = MagicMock()
        mock_parent.count_rows.return_value = 3
        mock_child = MagicMock()
        mock_child.count_rows.return_value = 0

        mock_db.open_table.side_effect = lambda name: {
            "parent_chunks": mock_parent,
            "child_chunks": mock_child,
        }[name]

        result = validate_commit("test.pdf", db=mock_db)
        assert result.passed is False
        assert result.orphans_cleaned == 3


class TestValidateDatabaseIntegrity:
    def test_no_tables(self):
        from unittest.mock import MagicMock
        from src.quality.batch_validator import validate_database_integrity

        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        result = validate_database_integrity(db=mock_db)
        assert result["status"] == "skipped"
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_batch_validator.py -v --tb=short`

- [ ] **Step 4: Commit**

```bash
git add src/quality/batch_validator.py tests/test_batch_validator.py
git commit -m "feat: post-commit validation + startup integrity check"
```

---

### Task 3: Wire into pipeline

**Files:**
- Modify: `src/batch_processor.py` (~line 178)
- Modify: `src/executor.py` (~line 297)
- Modify: `src/server.py` (lifespan)

- [ ] **Step 1: Wire validate_batch() into batch_processor.py**

At line 178, after `self._progress["status"] = "complete"`, add:

```python
try:
    from src.quality.batch_validator import validate_batch
    from src.staging import load_manifest
    manifest = load_manifest()
    validate_batch(manifest)
except Exception as e:
    logging.warning(f"Batch validation skipped: {e}")
```

- [ ] **Step 2: Wire validate_commit() into executor.py**

At line 297, before `return True`, add:

```python
try:
    from src.quality.batch_validator import validate_commit
    validate_commit(
        source_path=current_path.name,
        skip_rag=item.get("skip_rag", False),
    )
except Exception:
    pass  # Non-fatal — already logged inside validate_commit
```

- [ ] **Step 3: Wire validate_database_integrity() into server.py lifespan**

In the lifespan function, after the manifest cleanup block and before shared services init:

```python
try:
    from src.quality.batch_validator import validate_database_integrity
    integrity = validate_database_integrity()
    if integrity.get("orphaned_parents_cleaned", 0) > 0:
        logger.info(
            f"DB integrity: cleaned {integrity['orphaned_parents_cleaned']} orphaned parents"
        )
except Exception as e:
    logger.debug(f"Integrity check skipped: {e}")
```

- [ ] **Step 4: Add dashboard endpoint**

In `src/api/dashboard_routes.py`, add a route to serve the quality report:

```python
@router.get("/api/batch-quality")
async def get_batch_quality() -> dict:
    report_path = config.STATE_DIR / "batch_quality_report.json"
    if report_path.exists():
        try:
            return json.loads(report_path.read_text())
        except Exception:
            pass
    return {"passed": True, "warnings": [], "total_items": 0}
```

Add `import json` to dashboard_routes imports if not present.

- [ ] **Step 5: Run full test suite**

Run: `pytest --tb=short -q`
Expected: 623+ pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/batch_processor.py src/executor.py src/server.py src/api/dashboard_routes.py
git commit -m "feat: wire quality gates into pipeline — batch, commit, startup"
```

---

## Verification

- [ ] **Functional test: PII anomaly detection**

Process a batch where >50% of files are flagged sensitive. Verify the batch quality report at `~/.corerag/batch_quality_report.json` shows warnings.

- [ ] **Functional test: Orphan cleanup at startup**

Restart server. Check logs for "DB integrity" message. Verify no orphaned parents remain.

---

## Summary

| Task | What | Files | Lines |
|------|------|-------|-------|
| 1 | validate_batch() + tests | batch_validator.py, test | ~120 |
| 2 | validate_commit() + validate_database_integrity() | batch_validator.py, test | ~100 |
| 3 | Wire into pipeline + dashboard endpoint | 4 files | ~30 |

**Total: 3 tasks, ~250 lines, estimated 20-30 minutes.**
