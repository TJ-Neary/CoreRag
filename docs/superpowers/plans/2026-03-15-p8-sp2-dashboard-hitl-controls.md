# P8 SP2: Dashboard HITL Controls — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add skip/error file management, quality report banner, and archive manager view to the CoreRag dashboard — giving the user full GUI control over the ingestion pipeline and document catalog.

**Architecture:** Three features built incrementally on the existing dashboard. Skip button and quality banner modify the Ingestion tab. Archive manager adds a new tab with hybrid layout (sidebar tree + filters + file list). Backend extends existing `dashboard_routes.py` and `catalog_manager.py`. All frontend is vanilla JS + Tailwind in the single `dashboard.html` template.

**Tech Stack:** Python 3.12+, FastAPI, SQLite (catalog), Jinja2/Tailwind CSS, vanilla JavaScript

**Spec:** `docs/superpowers/specs/2026-03-15-p8-sp2-dashboard-hitl-controls-spec.md`

**Security note:** Frontend code that renders user-provided data (filenames, summaries, tags) must use `textContent` for plain text or safe DOM construction methods — never raw string interpolation into HTML. The existing dashboard uses template literals with `${}` which is an existing pattern; new code should follow the same approach but sanitize where user content could contain HTML special characters.

**Context files to read before implementing:**
- `src/ui/templates/dashboard.html` — 1,447-line dashboard template (Tailwind, dark theme)
- `src/api/dashboard_routes.py` — route handlers (uses `create_dashboard_router()` factory)
- `src/catalog/catalog_manager.py` — CatalogManager with CRUD + search + stats
- `src/staging.py` — staging manifest (cleanup_manifest, update_item, get_item)
- `src/quality/batch_validator.py` — BatchQualityReport dataclass + validate_batch()
- `src/config.py` — INBOX_PATH, ARCHIVE_PATH constants

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/staging.py` | Modify | Add `"skipped"` to `cleanup_manifest()` keep_statuses |
| `src/quality/batch_validator.py` | Modify | Add `extraction_details`/`error_details` fields to BatchQualityReport |
| `src/processor.py` | Modify | Populate error details when exceptions caught during analysis |
| `src/catalog/catalog_manager.py` | Modify | Add `migrate_to_cold()`, `get_folder_tree()`, `get_devices()` |
| `src/api/dashboard_routes.py` | Modify | Skip/restore actions, move-errors, folder-tree, cold-storage, devices endpoints |
| `src/ui/templates/dashboard.html` | Modify | Tab system, skip button, quality banner, archive manager view |
| `tests/test_catalog.py` | Modify | Tests for new CatalogManager methods |
| `tests/test_dashboard_sp2.py` | Create | Tests for skip/restore/move-errors/archive API endpoints |

---

## Task 1: Manifest Cleanup + Skip Status Support

**Files:**
- Modify: `src/staging.py`

- [ ] **Step 1: Add "skipped" to cleanup_manifest keep_statuses**

In `src/staging.py`, find `cleanup_manifest()` (line ~183). Change the default:

```python
if keep_statuses is None:
    keep_statuses = ["pending", "processing", "approved", "skipped"]
```

This prevents skipped items from being archived on server restart, preserving the ability to restore them from the dashboard.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_staging.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/staging.py
git commit -m "fix: preserve skipped items in manifest cleanup"
```

---

## Task 2: Batch Validator Error Details

**Files:**
- Modify: `src/quality/batch_validator.py`
- Modify: `src/processor.py`

- [ ] **Step 1: Extend BatchQualityReport dataclass**

In `src/quality/batch_validator.py`, add two new fields to `BatchQualityReport` (after `error_files`):

```python
@dataclass
class BatchQualityReport:
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
```

Each detail dict: `{"filename": "x.pdf", "error_type": "extraction_failed", "message": "Password protected"}`

Error types: `extraction_failed`, `format_unsupported`, `password_protected`, `llm_timeout`, `llm_json_error`, `pipeline_error`

- [ ] **Step 2: Update validate_batch() to populate details**

In the extraction warning check section of `validate_batch()`, populate `extraction_details` alongside `extraction_warnings`. For error items, populate `error_details` with the error message from the manifest item.

- [ ] **Step 3: Ensure batch-quality API serialization includes new fields**

The `GET /api/batch-quality` endpoint reads from `batch_quality_report.json`. `validate_batch()` uses `dataclasses.asdict()` when writing this file, so the new fields will be included automatically.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_batch_validator.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/quality/batch_validator.py src/processor.py
git commit -m "feat: per-file error details in batch quality report"
```

---

## Task 3: Skip/Restore/Move-Errors API Endpoints

**Files:**
- Modify: `src/api/dashboard_routes.py`
- Create: `tests/test_dashboard_sp2.py`

- [ ] **Step 1: Add skip action to the update endpoint**

In `src/api/dashboard_routes.py`, find the existing `POST /api/update/{item_id}` route handler inside `create_dashboard_router()`. Extend it to handle an `action` field in the request body.

When `action == "skip"`: move the file from `INBOX_PATH` to `INBOX_PATH/_Skipped/`, update manifest status to "skipped".

When `action == "restore"`: move file from `_Skipped/` back to `INBOX_PATH` (with timestamp suffix if collision), reset status to "pending".

Add `import shutil` at the top of the file if not already present.

- [ ] **Step 2: Add move-errors endpoint**

Add `POST /api/queue/move-errors` that bulk-moves all error-status files to `INBOX_PATH/_Error/`.

- [ ] **Step 3: Write tests**

Create `tests/test_dashboard_sp2.py` with tests for:
- `test_skip_file` — POST skip action, verify status=skipped, file moved
- `test_restore_file` — POST restore action, verify status=pending, file moved back
- `test_restore_collision` — restore when same filename exists in inbox
- `test_move_errors` — POST move-errors, verify error files moved to _Error/

Use `tmp_path` for inbox simulation, mock `config.INBOX_PATH`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dashboard_sp2.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/dashboard_routes.py tests/test_dashboard_sp2.py
git commit -m "feat: skip/restore/move-errors API endpoints"
```

---

## Task 4: CatalogManager — New Methods for Archive Manager

**Files:**
- Modify: `src/catalog/catalog_manager.py`
- Modify: `tests/test_catalog.py`

- [ ] **Step 1: Add get_folder_tree() method**

Returns dict with `categories` (list of name/count), `no_archive_path` count, `offline` count, `total`. Queries catalog SQLite grouping by category, counting null/empty archive_path, and counting storage_accessible=0.

- [ ] **Step 2: Add get_devices() method**

Returns list of dicts with `device`, `location_type`, `file_count`. Queries distinct `storage_device` values from catalog.

- [ ] **Step 3: Add migrate_to_cold() method**

Accepts `doc_ids`, `device_name`, `destination_root`. For each doc: validates file exists, replicates folder structure relative to ARCHIVE_PATH at the destination, moves file with `shutil.move`, updates catalog (storage_location, storage_device, storage_accessible, archive_path). Partial failure semantics: successfully-moved files stay at destination, failed files remain at original path. Returns `{"succeeded": [...], "failed": [...]}`.

- [ ] **Step 4: Write tests**

Add to `tests/test_catalog.py`:
- `test_get_folder_tree` — register docs in 3 categories, verify tree counts
- `test_get_folder_tree_empty` — empty catalog returns zeros
- `test_get_devices` — register docs with storage_device set, verify list
- `test_get_devices_empty` — no devices returns empty list
- `test_migrate_to_cold_success` — create temp files, migrate, verify moved + catalog updated
- `test_migrate_to_cold_partial_failure` — one file missing, verify succeeded/failed split
- `test_migrate_to_cold_replicates_structure` — verify folder structure replicated at destination

All tests use `tmp_path`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_catalog.py --no-cov -v --tb=short`
Expected: All pass (existing 23 + new 7 = 30).

- [ ] **Step 6: Commit**

```bash
git add src/catalog/catalog_manager.py tests/test_catalog.py
git commit -m "feat: CatalogManager — folder tree, devices, cold storage migration"
```

---

## Task 5: Archive Manager API Endpoints

**Files:**
- Modify: `src/api/dashboard_routes.py`

- [ ] **Step 1: Add folder-tree endpoint**

`GET /api/catalog/folder-tree` — calls `CatalogManager().get_folder_tree()`.

**IMPORTANT:** This route must be registered BEFORE `/api/catalog/{doc_id}` — otherwise FastAPI matches "folder-tree" as a doc_id. Check route ordering and adjust if needed.

- [ ] **Step 2: Add devices endpoint**

`GET /api/catalog/devices` — calls `CatalogManager().get_devices()`.

- [ ] **Step 3: Add cold-storage endpoint**

`POST /api/catalog/cold-storage` — accepts `{doc_ids, device_name, destination_root}`, calls `CatalogManager().migrate_to_cold()`.

- [ ] **Step 4: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -10`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/dashboard_routes.py
git commit -m "feat: archive manager API — folder-tree, devices, cold-storage"
```

---

## Task 6: Dashboard Frontend — Tab System + Skip Button

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Add tab system to header**

Add a tab bar after `<header>` with "Ingestion" (default active) and "Archive" tabs. Wrap existing content in `<div id="ingestion-view">`, add `<div id="archive-view" class="hidden">` placeholder.

Tab switching JS: toggles `hidden` class on views, updates tab active styling. Calls `loadArchiveView()` when Archive tab activated.

- [ ] **Step 2: Add skip button to card template**

Add "x" button in top-right of each card header. On click, calls `skipFile(itemId)` which POSTs to `/api/update/{id}` with `{action: "skip"}`, then collapses the card with CSS transition.

- [ ] **Step 3: Add skipped counter and restore toggle**

Below review container: "N files skipped" counter with "Show skipped" toggle. Skipped files shown in a collapsible list with "Restore" button per item.

- [ ] **Step 4: Test manually**

Start server, drop files, run analysis. Verify skip works, counter updates, file moves.

- [ ] **Step 5: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: dashboard tab system + skip button with file management"
```

---

## Task 7: Dashboard Frontend — Quality Report Banner

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Add quality banner HTML + CSS**

Collapsible banner between tabs and review cards. Color-coded: green (bg-green-900/40), yellow (bg-yellow-900/40), orange (bg-orange-900/40), red (bg-red-900/40).

- [ ] **Step 2: Add banner JavaScript**

`loadQualityBanner()` fetches `/api/batch-quality`, determines tier, renders summary + detail rows. Expand/collapse on click. Dismiss with "x". "Move to _Error/" button for orange/red tiers.

Call after batch analysis completes (in the existing analysis-complete callback).

Detail rows use safe DOM construction (createElement/textContent) for user-provided data (filenames, error messages).

- [ ] **Step 3: Test manually**

Process files including an unsupported format. Verify banner color, detail rows, move-errors button.

- [ ] **Step 4: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: quality report banner with color tiers + actionable guidance"
```

---

## Task 8: Dashboard Frontend — Archive Manager View

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Build archive view HTML structure**

Inside `archive-view` div: sidebar (25% width, folder tree), main area (75%, filter bar + bulk actions + file list). Uses Tailwind flex layout matching existing dashboard style.

- [ ] **Step 2: Add archive view JavaScript**

- `loadArchiveView()` — parallel fetch folder-tree + catalog, store data
- `renderFolderTree(tree)` — build sidebar links from categories with counts
- `renderArchiveFiles()` — render filtered file rows as table-style list
- `filterArchiveFiles()` — apply search/tag/sensitive filters, re-render
- Row click expands inline (fetch `/api/catalog/{doc_id}` for details)
- Checkbox selection shows bulk action bar
- `showColdStorageDialog()` — fetch `/api/catalog/devices` for dropdown, "New location..." reveals name+path fields, confirm POSTs to `/api/catalog/cold-storage`

All dynamic content rendered using safe DOM methods (createElement, textContent) for user-provided strings.

- [ ] **Step 3: Add storage status icons**

File rows show storage icon: local (default, no icon or subtle pin), external (disk icon), offline (warning icon with tooltip showing device name).

- [ ] **Step 4: Test manually**

1. Switch to Archive tab — verify folder tree loads with correct counts
2. Click a category — verify file list filters
3. Search by filename — verify results update
4. Select files — verify bulk action bar appears
5. Click file row — verify details expand inline

- [ ] **Step 5: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: archive manager view — sidebar tree, filters, file list, cold storage"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --no-cov --tb=short -q`
Expected: 660+ pass, no regressions.

- [ ] **Manual verification checklist**

Start server (`python -m src.server`), open dashboard at `localhost:8000`:

1. [ ] Tab bar shows "Ingestion" and "Archive"
2. [ ] Skip button on each file card collapses card, moves file to `_Skipped/`
3. [ ] Skipped counter shows at bottom with "Show skipped" toggle
4. [ ] Quality banner appears after batch analysis with correct color tier
5. [ ] Banner expands to show detail rows with actionable guidance
6. [ ] "Move to _Error/" button moves error files
7. [ ] Archive tab loads folder tree with correct category counts
8. [ ] Clicking category filters the file list
9. [ ] Search and tag filters work
10. [ ] File row expand shows document details
11. [ ] Cold storage dialog shows device dropdown

---

## Summary

| Task | What | Files | Effort |
|------|------|-------|--------|
| 1 | Manifest cleanup — preserve skipped items | staging.py | ~2 lines |
| 2 | Batch validator error details | batch_validator.py, processor.py | ~30 lines |
| 3 | Skip/restore/move-errors API | dashboard_routes.py, tests | ~80 lines |
| 4 | CatalogManager new methods | catalog_manager.py, tests | ~100 lines |
| 5 | Archive manager API endpoints | dashboard_routes.py | ~40 lines |
| 6 | Frontend: tabs + skip button | dashboard.html | ~100 lines |
| 7 | Frontend: quality banner | dashboard.html | ~120 lines |
| 8 | Frontend: archive manager view | dashboard.html | ~250 lines |

**Total: 8 tasks, ~720 lines, backend-first then frontend.**
