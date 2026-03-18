# P8 Sub-project 2: Dashboard HITL Controls — Full Spec

**Date:** 2026-03-15
**Author:** Claude Opus 4.6 (Session 32)
**Status:** Complete — implemented (Session 32, P8 SP2)
**North Star:** A second brain with perfect memory and recall — GUI-first, privacy-controlled.

---

## 1. Skip Button

**What:** An "×" button in the top-right corner of each dashboard file card during HITL review.

**Behavior:**
- Click → file physically moves from `INBOX_PATH` to `INBOX_PATH/_Skipped/`
- Manifest status set to `"skipped"` with timestamp
- Card collapses from the review queue with animation
- A "N files skipped" counter at the bottom of the review area with "Show skipped" toggle
- Skipped files visible in toggle view with "Restore" option (moves back to Inbox, resets to pending)

**`_Skipped/` folder:**
- Created at `INBOX_PATH/_Skipped/` (e.g., `~/Desktop/Inbox/_Skipped/`)
- Excluded from watchdog monitoring and batch processing
- Preserves original filename
- User browses manually in Finder for backlog review
- To re-process: move file back to Inbox manually, or use Restore in dashboard

**`_Error/` folder:**
- Created at `INBOX_PATH/_Error/` (e.g., `~/Desktop/Inbox/_Error/`)
- Files with extraction failures or critical pipeline errors are moved here via "Move errors" button in quality banner
- Excluded from watchdog monitoring and batch processing
- Separated from `_Skipped/` so user can distinguish "chose not to process" from "broke during processing"

**Backend:**
- `POST /api/update/{item_id}` with `{"action": "skip"}` — extends existing update endpoint. Moves file to `_Skipped/`, sets manifest status to `"skipped"`.
- `POST /api/update/{item_id}` with `{"action": "restore"}` — moves file from `_Skipped/` back to Inbox, resets status to `"pending"`. If a file with the same name already exists in Inbox, append a timestamp suffix to avoid collision.
- `POST /api/queue/move-errors` — bulk-moves all error-status files to `_Error/`
- **Watchdog:** Already uses `recursive=False` on the inbox observer, so `_Skipped/` and `_Error/` subdirectories are already excluded. No code change needed — add a comment documenting this assumption.
- **Batch processor:** `scan_inbox()` uses `is_file()` filter which already excludes directories. No code change needed — add a comment.
- **Manifest cleanup:** `staging.py` `cleanup_manifest()` must add `"skipped"` to the default `keep_statuses` set. Without this, skipped items would be archived on server restart, breaking the Restore feature.

---

## 2. Quality Report Banner

**What:** A color-coded banner between the header/tabs and the file cards, appearing after batch analysis completes.

**Color tiers:**
- **Green** — all clear. "Batch analysis complete: N files ready for review."
- **Yellow** — informational. High PII rate detected. "N of M files flagged as sensitive." No action needed — awareness only.
- **Orange** — extraction issues. Actionable. "N files had extraction problems."
- **Red** — critical failures. Actionable. "N files caused pipeline errors."

**Behavior:**
- Appears automatically after "Start Analysis" completes
- Collapsed: one-line summary with color indicator + chevron
- Click: expands inline showing detail rows
- Click again: collapses
- Dismissible with "×" — stays gone until next batch analysis

**Expanded detail rows:**
- Each affected file listed by name
- What went wrong (extraction failed, LLM timeout, format unsupported, etc.)
- Actionable guidance per tier:

**Orange (extraction issues):**
> "These files couldn't be fully processed. They may be corrupted, password-protected, or in an unsupported format. Skip these files and re-add corrected versions to the inbox."
> [Move to _Error/] button

**Red (critical failures):**
> "Pipeline errors occurred. Check: (1) Is Ollama running? `ollama serve` (2) Is qwen3:32b loaded? `ollama list` (3) Check server logs for details. After fixing, re-run analysis."
> [Move to _Error/] button

**Error file handling:**
- Files with error status are auto-excluded from the commit queue (already happens — `status: "error"` items aren't shown as pending)
- "Move to _Error/" button in banner bulk-moves all error files to `_Error/` folder
- Files left in Inbox can be retried by re-running analysis

**Data source:** `GET /api/batch-quality` (already exists). The `BatchQualityReport` in `batch_validator.py` must be extended:

Current `extraction_warnings` stores only filenames (strings). Add a new field:
```python
@dataclass
class BatchQualityReport:
    # ... existing fields ...
    extraction_details: list[dict]  # NEW: [{"filename": "x.pdf", "error_type": "extraction_failed", "message": "Password protected"}]
    error_details: list[dict]       # NEW: [{"filename": "y.pdf", "error_type": "llm_timeout", "message": "Ollama did not respond within 120s"}]
```

Error types: `extraction_failed`, `format_unsupported`, `password_protected`, `llm_timeout`, `llm_json_error`, `pipeline_error`.

These details are populated in `processor.py` during the analysis phase — when an exception is caught, the error type and message are recorded alongside the filename.

**Banner dismiss state:** Ephemeral — a page refresh re-shows the banner for the current batch. This is intentional (no localStorage persistence needed). The banner disappears only when a new batch analysis starts or the user dismisses it.

---

## 3. Archive Manager View

**Access:** Tab system in the dashboard header. Two tabs:
- **Ingestion** — current HITL review view (default)
- **Archive** — document catalog browser

Tabs appear below the CoreRag title as a horizontal tab bar. Memory and RAG Index buttons remain in the header area (top-right) — they are global tools that apply to both tabs.

**Folder tree is dynamic** — the `GET /api/catalog/folder-tree` endpoint queries the catalog database on every call. When files are moved, categories change, or cold storage migrations happen, the next API call reflects the updated state. The dashboard re-fetches the tree after any action that modifies the catalog (tab switch, cold storage migration, file skip/restore).

**Folder-tree API response shape:**
```json
{
  "categories": [
    {"name": "Work", "count": 78},
    {"name": "Personal", "count": 12},
    {"name": "Education", "count": 4}
  ],
  "no_archive_path": 56,
  "offline": 0,
  "total": 102
}
```

### Layout: Hybrid (Sidebar Tree + Top Filters + File List)

**Sidebar (left, ~25% width):**
- Folder tree built from catalog categories and archive folder structure
- "All Documents (N)" at top
- Category folders with counts: Work (78), Personal (12), Education (4), etc.
- "No Archive Path (N)" for unlocated files
- "Offline (N)" for cold storage files
- Click a folder → filters the file list

**Filter bar (top of file list):**
- Search box (filters by filename, summary text)
- Tag filter chips — click to add, × to remove
- Sensitive-only toggle
- File count indicator: "Showing N of M documents"

**File list (right, ~75% width):**
- Table-style rows: checkbox | filename | category | tags (pills) | year | storage icon
- Storage icons: 📍 local | 💾 external | ⚠️ offline
- Click row → expands inline to show:
  - Full summary
  - Archive path
  - Export destinations (with paths)
  - File size, chunk count
  - Ingested date
- Bulk action bar (appears when checkboxes selected):
  - "Move to Cold Storage" button
  - "Delete from Catalog" button (soft-delete)

### Cold Storage Flow

**Trigger:** Select files → click "Move to Cold Storage"

**Device selection:**
- Dropdown populated from catalog's distinct `storage_device` values (previously-used devices)
- "New location..." option → reveals two fields:
  - Device name (e.g., "WD_Passport_2TB")
  - Base path (e.g., "/Volumes/WD_Passport_2TB")
- First-time: user enters both; subsequent: pick from dropdown

**Execution:**
- Files physically moved from `archive_path` to `{cold_storage_base}/PKM/{relative_folder}/{filename}`
- Folder structure replicated (not flat files)
- Catalog updated atomically:
  - `storage_location` → "external_hd"
  - `storage_device` → device name
  - `storage_accessible` → 0
  - `archive_path` → new cold storage path

**Offline file display:**
- Offline files show with ⚠️ icon
- Tooltip: "Stored on [device name] (currently offline) — connect drive to access original"
- Future enhancement (SP6): auto-detect when previously-offline drive is connected and update `storage_accessible`. Tracked as TD-020 with full implementation details (FSEvents/polling on `/Volumes/`, menubar app integration, `update_device_accessibility()` method).

### Backend (New Endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/catalog/folder-tree` | GET | Returns category/folder hierarchy with counts for sidebar (see response shape below) |
| `POST /api/catalog/cold-storage` | POST | Move selected files to cold storage device |
| `GET /api/catalog/devices` | GET | List known storage devices (from catalog distinct values) |

### Backend (New CatalogManager Method)

`migrate_to_cold(doc_ids, device_name, destination_root)`:
- Validates all files exist at current `archive_path`
- Creates replicated folder structure at destination
- Moves files one by one (shutil.move)
- Updates catalog entry immediately after each successful move (within a single SQLite transaction per file)
- **Partial failure semantics:** Files already moved stay at the destination and their catalog entries are updated. Failed files remain at their original path. The method returns a result dict with `{"succeeded": [...], "failed": [{"id": ..., "error": ...}]}`. The caller (dashboard) displays the partial result to the user. There is no rollback of successfully-moved files — this is intentional because `shutil.move` is not transactional and re-copying from an external drive is slow and error-prone.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/ui/templates/dashboard.html` | Modify | Tab system, skip button, quality banner, archive manager view |
| `src/api/dashboard_routes.py` | Modify | Skip/restore actions on update endpoint, move-errors, folder-tree, cold-storage, devices |
| `src/catalog/catalog_manager.py` | Modify | `migrate_to_cold()`, `get_folder_tree()`, `get_devices()` |
| `src/staging.py` | Modify | Add `"skipped"` to `cleanup_manifest()` keep_statuses; skip/restore status handling |
| `src/processor.py` | Modify | Populate `extraction_details`/`error_details` when exceptions caught |
| `src/quality/batch_validator.py` | Modify | Add `extraction_details`/`error_details` fields to BatchQualityReport |
| `src/watchdog.py` | No change | Already excludes subdirs via `recursive=False` — add documenting comment only |
| `src/batch_processor.py` | No change | Already excludes subdirs via `is_file()` — add documenting comment only |
| `tests/test_catalog.py` | Modify | Tests for migrate_to_cold, get_folder_tree, get_devices |

---

## Success Criteria

1. Skip button removes card from review, moves file to `_Skipped/`, can be restored
2. Error files can be bulk-moved to `_Error/` via quality banner
3. Quality banner shows correct colors (green/yellow/orange/red) with actionable guidance
4. Archive tab shows all 102+ cataloged documents with working sidebar, filters, search
5. Cold storage migration moves files, replicates folder structure, updates catalog
6. Offline files clearly indicated in archive view
7. `_Skipped/` and `_Error/` excluded from watchdog and batch processing
8. Existing tests pass unchanged (SP2 is additive)

---

## Tech Debt: Native Folder Picker (SP6)

When CoreRag becomes a standalone macOS app (SP6), add a "Browse..." button to the cold storage device selection that opens a native `NSOpenPanel` folder picker via PyObjC. The current dropdown + text input design is additive-compatible — the native picker supplements rather than replaces it. Track as TD-019 when this spec is committed.
