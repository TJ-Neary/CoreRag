# Migration Log

**Date**: 2026-02-01
**Source**: `/Users/tjneary/Documents/Documents NO TOUCH/60_Tech_Projects/AI Projects/PKM_v1` (AI agent copy)
**Target**: `/Users/tjneary/Documents/60_Tech_Projects/AI Projects/PKM_v1` (original project)

---

## Merged Files (copy improvements applied to original)

### `src/processor.py`
- **Change**: Added two-phase staging. Files now immediately appear in the dashboard with `"processing"` status and a spinner while AI analysis runs, then update to `"pending"` when complete.
- **Before**: Single-phase — items only appeared in dashboard after AI analysis finished.
- **What was kept from original**: The original's import structure (`from src.archiver import archive_original`, `from src.exporter import export_to_vault`) was preserved. The intelligence module (`gemini-1.5-pro-latest`, 50K char context, structured prompt) was NOT overwritten.

### `src/staging.py`
- **Change**: `get_pending_items()` now returns items with status `"processing"` in addition to `"pending"`.
- **Why**: Required for the two-phase staging feature in processor.py — the dashboard needs to see processing items.

### `src/ui/templates/dashboard.html`
- **Changes**:
  - Added CSS spinner animation (`.loader` class)
  - Added `"processing"` state handler in `renderQueue()` — shows spinner + "AI is reading the document..." for items being analyzed
  - Changed `refreshQueue()` to avoid content flicker (no longer wipes innerHTML before fetch)
  - Added auto-refresh polling via `setInterval(refreshQueue, 2000)`
- **What was kept from original**: All existing card HTML structure, approve logic, and update API calls unchanged.

### `src/config.py`
- **Changes**:
  - Added fallback defaults when env vars are missing: `INBOX_PATH` -> `~/Desktop/Inbox`, `VAULT_PATH` -> `~/Documents/ObsidianVault`, `ARCHIVE_PATH` -> `~/Documents`
  - `validate_config()` now auto-creates `INBOX_PATH` and `VAULT_PATH` directories if they don't exist (previously only warned)
  - Removed `sys.exit(1)` on archive creation failure (now just prints warning)
  - Fixed typo: "actally" -> "actually"
- **What was kept from original**: Module structure, `get_path_var` signature, API key handling.

### `src/extractor.py`
- **Change**: Added `.yaml` to supported plain-text extensions list (union of both versions).
- **What was kept from original**: `.log` and `.csv` support, `errors='replace'` behavior, `import pypdf` / `import docx` import style.

## Files NOT Merged (original was better)

### `src/intelligence.py`
- **Original kept**: Uses `gemini-1.5-pro-latest` (copy used older `gemini-pro`), sends 50K chars of context (copy sent 4K), has structured prompt with role instruction, proper regex JSON cleaning via `_clean_json_markdown()`.

### `src/exporter.py`
- **Original kept**: Richer YAML frontmatter with `date_processed`, `tags` section, `_sanitize_filename()` helper, proper encoding parameter.

### `src/executor.py`
- **Original kept**: Functionally identical. Copy had marginally cleaner code but less explanatory comments.

### `src/archiver.py`
- Identical in both directories. No changes needed.

### `src/server.py`
- Identical in both directories. No changes needed.

### `.env`
- Identical (only difference was placeholder text for API key).

### `requirements.txt`
- Original already had `PyYAML==6.0.1` that the copy was missing. No changes needed.

## New Files Added

### `src/watchdog.py`
- **New**: File system watcher using the `watchdog` library. Monitors `INBOX_PATH` for new/moved files, triggers `process_document()` on detection. Ignores hidden files (`.DS_Store`).

### `scripts/run_system.sh`
- **New**: Shell script that starts both the FastAPI server and the watchdog process, then opens the dashboard in the browser. Auto-detects venv location.
- **Paths corrected** from copy's `Documents NO TOUCH` to original project location.

### `scripts/com.user.pkm.plist`
- **New**: macOS LaunchAgent that triggers `run_system.sh` when files are added to `~/Desktop/Inbox`.
- **Paths corrected** from copy's `Documents NO TOUCH` to original project location.

### `scripts/install_automation.sh`
- **New**: Installs the LaunchAgent plist to `~/Library/LaunchAgents/` and loads it.
- **Paths corrected** from copy's `Documents NO TOUCH` to original project location.

### `CLAUDE.md`
- **New**: Claude Code guidance file covering architecture, commands, conventions, and configuration.

## Files NOT Migrated (copy-only, not needed)

- `automation.log`, `launchd.log`, `launchd_error.log`, `watchdog.log` — runtime logs
- `.claude/` — Claude Code session cache
- `CLAUDE.md` in copy directory — superseded by new version written to original

---

## Handover Notes for Next Session

### Testing Status

**None of the merged changes have been tested.** The following need verification:

1. **Two-phase staging end-to-end**: Drop a file in Inbox, confirm it appears in dashboard with spinner immediately, then transitions to an editable pending card after AI finishes. This touches `processor.py`, `staging.py`, and `dashboard.html` together.
2. **Config fallback defaults**: Remove an env var from `.env` (e.g. comment out `INBOX_PATH`) and confirm the system falls back to `~/Desktop/Inbox` instead of crashing.
3. **Auto-directory creation**: Delete the Inbox folder, start the system, confirm `validate_config()` recreates it.
4. **Extractor .yaml support**: Drop a `.yaml` file in Inbox and confirm text is extracted.
5. **Watchdog**: Run `python -m src.watchdog` and confirm it picks up new files in the Inbox folder.
6. **run_system.sh**: Run `./scripts/run_system.sh` and confirm both server and watchdog start, dashboard opens.

### Known Issues / Potential Problems

- **`processor.py` imports that may be stale**: The file still imports `from src.archiver import archive_original` and `from src.exporter import export_to_vault` at the top, but the two-phase staging flow no longer calls these directly (the executor does that after approval). These imports are unused in the current flow and could be cleaned up.
- **`staging_manifest.json` concurrency**: Both `processor.py` (writing) and `server.py` (reading via API) access the manifest file. There is no file locking. Under heavy load (multiple files dropped simultaneously), this could cause race conditions. The original codebase had this same issue.
- **Dashboard polling**: The 2-second `setInterval` polling in `dashboard.html` could be replaced with SSE or WebSocket for a cleaner approach if the dashboard is expanded.
- **LaunchAgent not installed**: The `com.user.pkm.plist` and `install_automation.sh` were copied but NOT installed. The user needs to run `./scripts/install_automation.sh` to activate the launchd automation.

### Architecture Context

The project has two parallel ingestion paths that are somewhat redundant:

1. **Root-level files** (`src/processor.py`, `src/watchdog.py`, `src/server.py`, `src/staging.py`, `src/executor.py`, `src/archiver.py`, `src/exporter.py`, `src/extractor.py`, `src/intelligence.py`, `src/config.py`) — These form the HITL (human-in-the-loop) dashboard workflow with Gemini-based classification and a web-based review/approve UI. This is the system that was just migrated/merged.

2. **Subpackage modules** (`src/ingestion/pipeline.py`, `src/search/`, `src/embeddings/`, `src/mcp_server/`, `src/chunking/`, etc.) — These form the MCP/RAG pipeline for Claude Desktop integration with LanceDB, nomic embeddings, hybrid search, etc.

These two systems were developed somewhat independently. They share `src/config.py` and some utility code, but have different entry points and different processing flows. A future task might be to unify them so the HITL dashboard feeds into the same LanceDB/embedding pipeline that the MCP server queries.

### Project State

- The `.env` file has `GOOGLE_API_KEY=your_api_key_here` — this is a placeholder. Intelligence features will run in simulation/fallback mode until a real key is set.
- The `staging_manifest.json` in the project root contains data from previous test runs. It can be deleted to start fresh.
- The `venv/` exists but may need `pip install -r requirements.txt` rerun if dependencies have drifted.
- There is no git repo initialized — the `.gitignore` exists but `git init` has not been run.
