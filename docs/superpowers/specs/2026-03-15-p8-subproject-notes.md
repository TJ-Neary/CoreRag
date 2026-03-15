# P8 Sub-Project Notes — Captured During Brainstorm

**Purpose:** Preserve design decisions and requirements discussed during the P8 brainstorm for sub-projects that will be designed later. These notes ensure nothing is lost between sessions.

---

## Sub-project 2: Dashboard HITL Controls — Deferred Items

### Archive Manager View
- Add a new view/tab in the dashboard for browsing archived files
- User can browse the `~/Documents/PKM/` folder structure
- Select files individually or in bulk
- "Move to Cold Storage" button opens a folder picker dialog
- User selects the cold storage destination (external drive, NAS, etc.)
- System moves files and updates the catalog atomically:
  - `storage_location` → e.g., "external_hd"
  - `storage_device` → e.g., "WD_Passport_2TB"
  - `storage_accessible` → 0 (offline until drive reconnected)
  - `archive_path` → updated to new location
- The folder structure is **replicated** in the cold storage location (not just flat files)
  - If `~/Documents/PKM/Education/HR/file.pdf` is migrated, it goes to `{cold_storage}/PKM/Education/HR/file.pdf`
- When an offline file appears in search results, show: "Found in 'WD_Passport_2TB' (currently offline) — connect drive to access original"
- Future: detect when a previously-offline drive is connected and auto-update `storage_accessible`

### Skip/Remove Button
- Per-file button on each dashboard card during HITL review
- Sets manifest status to "skipped" — removes from pending queue
- File stays in inbox (not deleted, not committed)
- User can re-process skipped files later

### Quality Report Banner
- After batch analysis completes, display the quality gate report as a banner at the top of the dashboard
- Color: green (passed), yellow (warnings), red (errors)
- Shows: PII rate, extraction warnings, error count
- Clickable to expand full details

---

## Sub-project 6: Standalone macOS App — Deferred Items

### Goal
- Package CoreRag as a `.app` bundle launchable from Finder/Dock
- No terminal needed — double-click to start
- Menubar icon + dashboard auto-open in default browser

### Approach
- Use `py2app` or `PyInstaller` to bundle the Python environment
- The app launches:
  1. Ollama check (is it running? prompt to start if not)
  2. CoreRag server (FastAPI/uvicorn)
  3. Menubar app (rumps with dock icon)
  4. Opens dashboard in browser
- Install/uninstall via drag-to-Applications
- Auto-start on login option (LaunchAgent, already exists as `install_menubar.sh`)

### Considerations
- Bundle size: Python venv + models (~2-3GB). Consider keeping models external.
- First-run setup: spaCy model download, LanceDB init, embedding model download
- Updates: how to update the app without losing data (data is in ~/.corerag/, separate from app)
- Code signing: needed for Gatekeeper if distributing beyond this machine

### Why Wait
- Core features (dual DB, catalog, redaction editor) need to be stable before packaging
- UI changes during sub-projects 1-5 would require re-packaging each time
- Package after the feature set is frozen

---

## Captured Design Decisions (from brainstorm)

1. **Archive path:** `~/Documents/PKM/` (not "Knowledge")
2. **Catalog location:** `~/Documents/PKM/_catalog.db` (SQLite, lives with archive)
3. **Cold storage:** Folder structure replicated to destination (not flat)
4. **Cold storage tracking:** 3 columns on documents table (storage_location, storage_device, storage_accessible)
5. **Re-ingest existing 99 files:** Yes — rebuild through new pipeline for consistent quality
6. **Standalone app:** Sub-project 6, after features are stable
7. **Archive manager:** Built into dashboard GUI, not CLI-only
8. **CUI_ prefix:** Only on archive filenames when USER's PII detected (not generic NER names)
