# P8 SP1: Document Catalog + Archive Organization — Implementation Plan

> **Status: COMPLETE** — Implemented (Session 32, 2026-03-15/16). 10 commits, ~2,100 lines.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SQLite document catalog that tracks every file across all destinations (main RAG, restricted RAG, Obsidian, archive), reorganize the archive at ~/Documents/PKM/, replace the keyword auto-tagger with LLM-powered tags, and retroactively catalog the 99 existing files.

**Architecture:** New `src/catalog/catalog_manager.py` module with SQLite backend at `~/Documents/PKM/_catalog.db`. Integrated into executor at commit time. LLM prompt enhanced with existing folder tree + tag context for consistent naming. Retroactive rebuild script populates catalog from existing LanceDB + staging manifest data.

**Tech Stack:** Python 3.12+, SQLite, LanceDB, FastAPI, Ollama (qwen3:32b)

**Spec:** `docs/superpowers/specs/2026-03-15-p8-sp1-document-catalog-spec.md`

**Context files to read before implementing:**
- `src/executor.py` — where commits happen (integrate catalog.register)
- `src/processor.py` — where PII scan + auto-tagging happen (replace auto-tagger)
- `src/intelligence.py` — LLM analysis prompt (add folder tree + tag context)
- `src/config.py` — ARCHIVE_PATH constant (change to ~/Documents/PKM/)
- `src/archiver.py` — file archiving logic
- `src/staging.py` — staging manifest (used for retroactive rebuild)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/catalog/__init__.py` | Create | Package init |
| `src/catalog/catalog_manager.py` | Create | CatalogManager class, schema, all operations |
| `tests/test_catalog.py` | Create | Tests for CatalogManager |
| `src/config.py` | Modify | ARCHIVE_PATH → ~/Documents/PKM/ |
| `src/executor.py` | Modify | Call catalog.register() + record_export() |
| `src/processor.py` | Modify | Replace auto-tagger with LLM tags + year tag |
| `src/intelligence.py` | Modify | Add folder tree + tag context to LLM prompt |
| `src/cli/main.py` | Modify | Add catalog subcommands |
| `src/api/dashboard_routes.py` | Modify | Add catalog API endpoints |
| `src/mcp_server/server.py` | Modify | Add catalog MCP tools |
| `scripts/rebuild_catalog.py` | Create | Retroactive population script |

---

## Task 1: Create CatalogManager with Schema + Core CRUD

**Files:**
- Create: `src/catalog/__init__.py`
- Create: `src/catalog/catalog_manager.py`
- Create: `tests/test_catalog.py`

- [ ] **Step 1: Create package and CatalogManager with schema**

Create `src/catalog/__init__.py` (empty) and `src/catalog/catalog_manager.py` with:
- `DocumentRecord` dataclass matching the schema
- `ExportRecord` dataclass
- `CatalogManager.__init__` creates SQLite DB + tables if not exist
- `register()`, `get()`, `update()`, `search()`, `delete()` methods
- `record_export()`, `get_exports()` methods
- `get_stats()` method

Default DB path: `~/Documents/PKM/_catalog.db` (create PKM dir if not exists).

- [ ] **Step 2: Write tests**

Test in `tests/test_catalog.py`:
- `test_register_and_get` — register a doc, get it back
- `test_update` — register, update category, verify
- `test_search_by_category` — register 3 docs, search by category
- `test_search_by_tag` — search by tag substring
- `test_search_by_sensitive` — filter sensitive only
- `test_record_export` — register doc, record 2 exports, get_exports returns both
- `test_delete_soft` — delete sets status to 'deleted', still in DB
- `test_get_stats` — returns counts by category/tag/sensitivity
- `test_storage_location_fields` — verify storage_location, storage_device, storage_accessible

Use `tmp_path` fixture for test DB path.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_catalog.py -v --tb=short`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/catalog/ tests/test_catalog.py
git commit -m "feat: CatalogManager with SQLite schema + CRUD operations"
```

---

## Task 2: Update ARCHIVE_PATH + Create PKM Directory

**Files:**
- Modify: `src/config.py`
- Modify: `src/archiver.py` (verify it uses config.ARCHIVE_PATH)

- [ ] **Step 1: Change ARCHIVE_PATH in config.py**

Find `ARCHIVE_PATH` and change from:
```python
ARCHIVE_PATH = Path(os.getenv("ARCHIVE_PATH", ...))
```
To default to `~/Documents/PKM` instead of `~/Documents`. The env var override still works.

- [ ] **Step 2: Ensure PKM directory is created**

In `src/config.py` or `src/archiver.py`, add:
```python
ARCHIVE_PATH.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: Verify archiver uses config.ARCHIVE_PATH**

Read `src/archiver.py` and confirm `archive_to_target()` uses `ARCHIVE_PATH` from config (it should already).

- [ ] **Step 4: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass (no behavior change for existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/archiver.py
git commit -m "feat: change archive path to ~/Documents/PKM/"
```

---

## Task 3: Replace Auto-Tagger with LLM Tags + Year Tag

**Files:**
- Modify: `src/processor.py` (~line 150)
- Modify: `src/intelligence.py` (LLM prompt)

- [ ] **Step 1: Update processor.py to use LLM tags**

Replace the auto-tagger section in `processor.py` (the `# 4b. Auto-Tagging` block). Instead of calling `_get_auto_tagger().tag(text)`, extract tags from the LLM metadata that `analyze_document()` already returns.

The LLM analysis prompt (in `intelligence.py`) needs to be updated to:
1. Include the existing archive folder tree
2. Include existing collection tags in use
3. Ask for 1-3 topic tags + year tag
4. Return tags in the JSON response

In `processor.py`, after the LLM analysis:
```python
# Use LLM-suggested tags instead of keyword auto-tagger
llm_tags = metadata.get("tags", [])
if isinstance(llm_tags, str):
    llm_tags = [t.strip() for t in llm_tags.split(",") if t.strip()]

# Add year as tag if extracted
year = metadata.get("year", "")
if year and year != "Unknown":
    if year not in llm_tags:
        llm_tags.append(year)

# Cap at 5 tags
metadata["tags"] = llm_tags[:5]
```

- [ ] **Step 2: Update intelligence.py LLM prompt**

In the `analyze_document()` function, add to the prompt:
```
Also suggest 1-3 collection tags for this document. Tags should describe what collection or topic this document belongs to (e.g., "fitness", "hr-training", "building-codes"). Use existing tags when appropriate: {existing_tags}

Return tags as a JSON array in the "tags" field.
```

To get existing tags, read from the catalog (if available) or from LanceDB tag column.

- [ ] **Step 3: Add folder tree context to LLM prompt**

Read the existing `~/Documents/PKM/` folder tree and include in the prompt:
```
Existing archive folder structure:
{folder_tree}

When suggesting a target_folder, REUSE existing folders when the document fits.
```

- [ ] **Step 4: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/processor.py src/intelligence.py
git commit -m "feat: LLM-powered tags replace keyword auto-tagger + year as tag"
```

---

## Task 4: Integrate Catalog into Executor

**Files:**
- Modify: `src/executor.py`

- [ ] **Step 1: Add catalog registration after successful commit**

In `execute_approved_item()`, after `update_item(item_id, {"status": "completed"})`, add:

```python
# Register in document catalog
try:
    from src.catalog.catalog_manager import CatalogManager, DocumentRecord

    catalog = CatalogManager()
    doc_record = DocumentRecord(
        id=doc_id,  # The SHA256 hash document_id
        original_filename=original_path.name,
        original_path=str(original_path),
        archive_path=str(archive_dest) if archive_dest else None,
        main_rag_doc_id=doc_id,
        category=final_metadata.get("category", ""),
        year=final_metadata.get("year", ""),
        tags=",".join(final_metadata.get("tags", [])),
        is_sensitive=1 if final_metadata.get("is_sensitive") else 0,
        summary=final_metadata.get("summary", ""),
        file_type=original_path.suffix.lstrip("."),
        file_size=original_path.stat().st_size if original_path.exists() else 0,
    )
    catalog.register(doc_record)

    # Record exports
    if archive_dest:
        catalog.record_export(doc_id, "archive", str(archive_dest), redacted=False)
    catalog.record_export(doc_id, "main_rag", doc_id, redacted=final_metadata.get("is_sensitive", False))
    if vault_dest:
        catalog.record_export(doc_id, "obsidian", str(vault_dest), redacted=True)
except Exception as e:
    logger.warning(f"Catalog registration failed (non-fatal): {e}")
```

- [ ] **Step 2: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass (catalog failures are non-fatal).

- [ ] **Step 3: Commit**

```bash
git add src/executor.py
git commit -m "feat: register documents in catalog after commit"
```

---

## Task 5: CLI Catalog Commands

**Files:**
- Modify: `src/cli/main.py`

- [ ] **Step 1: Add catalog subcommand group**

Add to the CLI:
```python
@app.command()
def catalog_list(sensitive: bool = False, tag: str = "", category: str = ""):
    """List cataloged documents."""

@app.command()
def catalog_stats():
    """Show catalog summary statistics."""

@app.command()
def catalog_search(query: str):
    """Search catalog by keyword in filename/summary."""

@app.command()
def catalog_rebuild():
    """Rebuild catalog from existing LanceDB + manifest data."""
```

- [ ] **Step 2: Implement each command**

Each command creates a `CatalogManager()` and calls the appropriate method. Output formatted with `rich` tables (already used in CLI).

- [ ] **Step 3: Run tests**

Run: `pytest --tb=short -q`

- [ ] **Step 4: Commit**

```bash
git add src/cli/main.py
git commit -m "feat: CLI catalog commands — list, stats, search, rebuild"
```

---

## Task 6: Dashboard API + MCP Tools

**Files:**
- Modify: `src/api/dashboard_routes.py`
- Modify: `src/mcp_server/server.py`

- [ ] **Step 1: Add dashboard catalog endpoints**

```python
@router.get("/api/catalog")
async def get_catalog(sensitive: bool = None, tag: str = "", category: str = ""):
    """Paginated catalog listing."""

@router.get("/api/catalog/stats")
async def get_catalog_stats():
    """Catalog summary for dashboard widget."""

@router.get("/api/catalog/{doc_id}")
async def get_catalog_entry(doc_id: str):
    """Single document with exports."""
```

- [ ] **Step 2: Add MCP catalog tools**

In `server.py`, add:
```python
@mcp.tool()
async def catalog_search(query: str, tags: str = "", sensitive_only: bool = False):
    """Search the document catalog."""

@mcp.tool()
async def catalog_stats():
    """Get document catalog statistics."""
```

- [ ] **Step 3: Run tests**

Run: `pytest --tb=short -q`

- [ ] **Step 4: Commit**

```bash
git add src/api/dashboard_routes.py src/mcp_server/server.py
git commit -m "feat: catalog dashboard API + MCP tools"
```

---

## Task 7: Retroactive Catalog Rebuild Script

**Files:**
- Create: `scripts/rebuild_catalog.py`

- [ ] **Step 1: Create rebuild script**

The script does 4 phases:

**Phase 1:** Scan LanceDB `child_chunks` → extract unique `(source_path, document_id)` pairs + chunk counts
**Phase 2:** Cross-reference with CWD `staging_manifest.json` for metadata (category, year, summary, tags, is_sensitive)
**Phase 3:** Re-classify each doc with improved LLM prompt (folder tree context, LLM tags) — ~30s/file
**Phase 4:** Locate archived originals in `~/Documents/` and record archive_path. Move to `~/Documents/PKM/{target_folder}/` if not already organized.

Include:
- `--dry-run` flag (preview without writing)
- `--skip-llm` flag (skip Phase 3 re-classification)
- `--phase N` flag (run specific phase only)
- Progress logging

- [ ] **Step 2: Test with dry-run**

```bash
python scripts/rebuild_catalog.py --dry-run
```
Expected: Shows what would be cataloged without writing.

- [ ] **Step 3: Commit**

```bash
git add scripts/rebuild_catalog.py
git commit -m "feat: retroactive catalog rebuild from existing LanceDB + manifest"
```

---

## Verification

After all tasks complete:

- [x] **Run full test suite** — 660 passed, 1 pre-existing failure, 26 skipped (Session 32)

- [x] **Test catalog end-to-end** — 102 docs cataloged, 2 sensitive, 111 exports (Session 32)

- [x] **Run retroactive rebuild** — 99 docs from LanceDB, 97 new + 2 existing, --skip-llm (Session 32)

---

## Task 8: LLM Re-classification of Existing 99 Documents

> **Status:** NOT STARTED — Execute after archive folder migration is complete.

**Goal:** Replace the low-quality keyword auto-tagger tags on all 99 existing documents with LLM-powered tags, proper categories, and year tags. The initial catalog rebuild (Task 7) populated entries using old metadata — 56 of 99 documents have `category=Unsorted` and carry shotgun keyword tags like `fitness,workout,plan,training,mind-pump,gym,lifting` that don't meaningfully describe the content.

**Why this matters:**
- The keyword auto-tagger (now removed) assigned 7-10 generic tags per document based on word frequency, making tag-based search useless (56 docs all share the same tags)
- 58 of 99 documents have no category or year because they predate the staging manifest
- The new LLM prompt (Task 3) produces purpose-driven collection tags (1-3 per doc) plus year, with folder tree and existing tag context for consistency
- Without this step, the catalog's metadata quality is poor for half the collection

**Prerequisites:**
1. Archive folder migration must be complete (`~/Documents/Knowledge/` → `~/Documents/PKM/`)
2. `.env` ARCHIVE_PATH must point to `~/Documents/PKM/` (done)
3. Original files must be locatable in the archive (Phase 4 found only 41/99 — the remaining 58 need to be located or their text extracted from LanceDB chunks)

**Files:**
- Modify: `scripts/rebuild_catalog.py` (add Phase 3 text fallback from LanceDB chunks)

- [ ] **Step 1: Locate and migrate archived files**

Move `~/Documents/Knowledge/` to `~/Documents/PKM/` (preserving folder structure):
```bash
# Check what's in Knowledge/
ls ~/Documents/Knowledge/
# Move to PKM (the new canonical location)
mv ~/Documents/Knowledge/* ~/Documents/PKM/
rmdir ~/Documents/Knowledge
```

Also scan `~/Documents/` root level for loose archived files that ended up there due to the old `ARCHIVE_PATH=~/Documents` default. Move any CoreRag-archived files into appropriate `~/Documents/PKM/` subfolders.

- [ ] **Step 2: Add LanceDB text fallback to rebuild script**

For the 58 documents where original files can't be found, reconstruct text from LanceDB `child_chunks` by concatenating chunk content in order. This provides enough text for LLM re-classification without needing the original file.

In `scripts/rebuild_catalog.py`, update `phase3_llm_reclassify()`:
```python
# If original file not found, reconstruct from LanceDB chunks
if not text:
    chunks = [row for row in all_rows if row["document_id"] == doc_id]
    chunks.sort(key=lambda r: r.get("chunk_index", 0))
    text = "\n".join(c["content"] for c in chunks)
    if text:
        logger.info(f"  Reconstructed {len(text)} chars from {len(chunks)} LanceDB chunks")
```

- [ ] **Step 3: Run LLM re-classification**

```bash
python scripts/rebuild_catalog.py --phase 3
```

This will:
- Re-analyze each document with the improved LLM prompt (folder tree + existing tag context)
- Replace old keyword tags with 1-3 purposeful collection tags + year tag
- Update categories from "Unsorted" to proper values (Education, Fitness, Technical, etc.)
- Estimated time: ~30s/file × 99 files = ~50 minutes with Ollama qwen3:32b

- [ ] **Step 4: Verify re-classification quality**

```bash
python -m src.cli.main catalog stats
python -m src.cli.main catalog list --category Unsorted
```

Expected: "Unsorted" count should drop from 56 to near zero. Tags should be diverse and meaningful (not all documents sharing the same 7 tags).

- [ ] **Step 5: Commit updated rebuild script**

```bash
git add scripts/rebuild_catalog.py
git commit -m "feat: LanceDB text fallback for rebuild re-classification"
```

---

## Summary

| Task | What | Files | Status |
|------|------|-------|--------|
| 1 | CatalogManager + tests | 3 new files | ✅ Complete |
| 2 | Archive path → ~/Documents/PKM/ | config.py | ✅ Complete |
| 3 | LLM tags + year tag | processor.py, intelligence.py | ✅ Complete |
| 4 | Integrate into executor | executor.py | ✅ Complete |
| 5 | CLI commands | cli/main.py | ✅ Complete |
| 6 | Dashboard API + MCP | dashboard_routes.py, server.py | ✅ Complete |
| 7 | Retroactive rebuild script | scripts/rebuild_catalog.py | ✅ Complete |
| 8 | LLM re-classification of 99 docs | scripts/rebuild_catalog.py | ⬜ Not started |

**Tasks 1-7 complete (Session 32). Task 8 requires archive folder migration first.**
