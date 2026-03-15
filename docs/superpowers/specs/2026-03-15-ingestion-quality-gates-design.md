# Ingestion Quality Gates — Design Spec

**Date:** 2026-03-15
**Author:** Claude Opus 4.6 (Session 31)
**Status:** Draft

---

## Context

CoreRag's ingestion pipeline processes files through analysis (PII detection, LLM classification) then commits them (archiving, vault export, RAG indexing). Session 31 discovered two classes of quality issues that went undetected:

1. **PII false positives:** 86% of a 72-file batch was flagged as sensitive due to Presidio NER detecting names/addresses in HR training content and building permit docs. No automated anomaly detection existed.
2. **Orphaned parent chunks:** 71 files had parent chunks but zero children in LanceDB — ghost entries from failed indexing that accumulated over months unnoticed.

Both issues were caught manually. This spec adds automated quality gates at two pipeline stages to prevent recurrence.

---

## Pre-Commit Quality Gate

**Location:** `src/quality/batch_validator.py` → `validate_batch()`
**Trigger:** Automatically after all files in a batch finish analysis (all items reach "pending" status).
**Consumer:** Dashboard banner + `/api/batch-quality` endpoint.

### Checks

| Check | Threshold | Action |
|-------|-----------|--------|
| PII sensitivity rate | >50% of batch flagged `is_sensitive=True` | Warning: "Unusually high PII rate — review detections" |
| Text extraction ratio | Extracted text <100 chars for files >10KB | Flag item: "possible extraction failure" |
| Duplicate rate | >80% of batch matched existing files | Info: "Most files already indexed" |
| Error rate | Any items with status "error" | Error count + filenames |

### Data Model

```python
@dataclass
class BatchQualityReport:
    total_items: int
    sensitive_count: int
    sensitive_rate: float
    extraction_warnings: list[str]  # filenames with short text
    duplicate_count: int
    error_count: int
    error_files: list[str]
    warnings: list[str]  # human-readable warning messages
    passed: bool  # True if no warnings
```

### Integration

- `batch_processor.py` calls `validate_batch(manifest)` after all items finish analysis
- Result stored as JSON in `~/.corerag/batch_quality_report.json`
- Dashboard fetches via `GET /api/batch-quality` and renders as a banner
- Banner color: green (passed), yellow (warnings), red (errors)

---

## Post-Commit Integrity Gate

**Location:** `src/quality/batch_validator.py` → `validate_commit()`
**Trigger:** After each `execute_approved_item()` completes in `executor.py`.
**Also runs:** At server startup (in lifespan) as a periodic health check.

### Checks

| Check | What It Verifies | Action on Failure |
|-------|-----------------|-------------------|
| Parent-child integrity | File has both parents AND children | Auto-delete orphaned parents; log warning |
| Child chunk count | At least 1 child was created | Log error; mark item "commit_failed" |
| Content hash presence | All children have non-empty `content_hash` | Log warning |
| Context prefix presence | Children have context prefixes (if enabled) | Log info (non-blocking) |
| Source path consistency | DB `source_path` matches committed filename | Log warning (prevents CUI_ ghost problem) |

### Auto-Corrections

- **Orphaned parents (0 matching children):** Auto-delete with structured log entry. This is always safe — a parent with no children is unsearchable dead data.
- **Failed indexing:** Mark manifest item status as "error" with reason field. Do not silently succeed.

### Data Model

```python
@dataclass
class CommitValidationResult:
    source_path: str
    passed: bool
    parent_count: int
    child_count: int
    orphans_cleaned: int
    warnings: list[str]
    errors: list[str]
```

### Startup Health Check

At server startup (in `lifespan`), run `validate_database_integrity()`:
1. Find all parent source_paths not in child source_paths → auto-clean
2. Log summary: "Startup integrity: cleaned N orphaned parents from M files"

This replaces the manual cleanup done in Session 31.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/quality/batch_validator.py` | Create | `validate_batch()`, `validate_commit()`, `validate_database_integrity()` |
| `src/batch_processor.py` | Modify | Call `validate_batch()` after analysis |
| `src/executor.py` | Modify | Call `validate_commit()` after commit |
| `src/server.py` | Modify | Call `validate_database_integrity()` in lifespan |
| `src/api/dashboard_routes.py` | Modify | Add `GET /api/batch-quality` endpoint |

---

## Success Criteria

1. A batch with 86% PII rate produces a visible warning banner on the dashboard
2. Orphaned parents from failed indexing are auto-cleaned at commit time and startup
3. Extraction failures (files that produce <100 chars of text from large files) are flagged
4. All checks run automatically — no manual intervention required to detect issues
5. Existing tests pass unchanged (quality gates are additive)
