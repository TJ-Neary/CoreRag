# P8 Sub-project 1: Document Catalog + Archive Organization — Full Spec

**Date:** 2026-03-15
**Author:** Claude Opus 4.6 (Session 31)
**Status:** Complete — implemented (Session 32, P8 SP1)
**North Star:** A second brain with perfect memory and recall — usable by TJ, multiple AI agents, and multiple projects. Privacy and secrets controlled, only released when needed and approved.

---

## 1. Catalog Schema

SQLite database at `~/Documents/PKM/_catalog.db`.

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    original_path TEXT,
    archive_path TEXT,
    main_rag_doc_id TEXT,
    restricted_rag_doc_id TEXT,
    obsidian_path TEXT,
    category TEXT,
    year TEXT,
    tags TEXT,                          -- Comma-delimited collection tags
    is_sensitive INTEGER DEFAULT 0,
    summary TEXT,
    file_type TEXT,
    file_size INTEGER,
    chunk_count INTEGER DEFAULT 0,
    parent_count INTEGER DEFAULT 0,
    batch_id TEXT,
    ingested_at TEXT,
    updated_at TEXT,
    status TEXT DEFAULT 'active',       -- active, archived, deleted
    storage_location TEXT DEFAULT 'local',  -- local, external_hd, cloud
    storage_device TEXT,                    -- e.g., 'MacBook', 'WD_Passport_2TB'
    storage_accessible INTEGER DEFAULT 1   -- 1=reachable, 0=offline
);

CREATE TABLE document_exports (
    document_id TEXT,
    destination TEXT,    -- 'main_rag', 'restricted_rag', 'obsidian', 'archive'
    path TEXT,
    exported_at TEXT,
    redacted INTEGER,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);
```

---

## 2. Archive Structure

```
~/Documents/PKM/                     ← Base archive path (iCloud: force "Keep Downloaded")
├── Education/
│   ├── HR/
│   ├── Certifications/
│   └── Courses/
├── Fitness/
│   ├── Nutrition/
│   ├── Training_Programs/
│   └── Recovery/
├── Technical/
├── Legal/
├── Medical/
└── _catalog.db                      ← Lives with the archive (moves together)
```

- CUI_ prefix on archive filenames only when USER's PII detected
- Cold storage replicates folder structure to destination
- iCloud-synced folders must be pinned local (SQLite needs local filesystem)

---

## 3. Catalog API

`src/catalog/catalog_manager.py` — `CatalogManager` class:

- `register(doc)` — add new document after commit
- `update(doc_id, **fields)` — update metadata
- `get(doc_id)` — get by ID
- `search(**filters)` — relational query (category, year, tags, sensitivity)
- `delete(doc_id)` — soft delete
- `record_export(doc_id, destination, path, redacted)` — track exports
- `get_exports(doc_id)` — list exports for a document
- `migrate_to_cold(doc_ids, destination_root)` — move to cold storage, replicate folder structure
- `rebuild_from_lancedb()` — retroactive population from existing data
- `get_stats()` — summary counts

Integrated into `executor.py` at commit time.

---

## 4. LLM-Powered Folder & Tag Suggestions

Replace keyword auto-tagger with LLM-powered tagging:
- Feed existing archive folder tree + existing tags to LLM prompt
- LLM reuses existing folders/tags when appropriate
- 3-5 tags per file: 1-3 topic tags + year + sensitivity if applicable
- Tags answer "what collection does this belong to?" not "what words appear?"
- Auto-tagger (`src/classification/auto_tagger.py`) bypassed for tag assignment

---

## 5. Retroactive Re-ingestion

Run once after Sub-project 1 is built via `python -m src.cli.main catalog rebuild`:

**Phase 1:** Build catalog from existing LanceDB (99 files) + staging manifest metadata
**Phase 2:** Re-classify with improved LLM pipeline (new tags, folder context) — ~30s/file
**Phase 3:** Reorganize archive — move files to `~/Documents/PKM/{target_folder}/`
**Phase 4:** Re-embed (optional, separate — existing backfill script handles this)

---

## 6. CLI + MCP + Dashboard Integration

**CLI:**
```
catalog list [--sensitive] [--tag TAG] [--category CAT]
catalog search "query"
catalog stats
catalog rebuild
catalog export [--format csv|json]
```

**MCP tools (for Kendra + agents):**

| Tool | Role Required | Description |
|------|--------------|-------------|
| `corerag_search` | VIEWER+ | Semantic search (existing) |
| `corerag_catalog_search` | VIEWER+ | Search with catalog metadata + cross-DB |
| `corerag_catalog_stats` | VIEWER+ | Document counts |
| `corerag_ingest` | EDITOR+ | Ingest content |
| `corerag_server_status` | ADMIN | Check server status |
| `corerag_server_start` | ADMIN | Start server if not running |
| `corerag_health_check` | ADMIN | DB integrity + health |

**Dashboard API:**
```
GET /api/catalog              — paginated file list with filters
GET /api/catalog/{doc_id}     — single document with all exports
GET /api/catalog/stats        — summary widget
```

**Design principle:** Every CLI command has a dashboard equivalent. The GUI is the primary human interface; CLI exists for automation and agent use.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/catalog/__init__.py` | Create | Package init |
| `src/catalog/catalog_manager.py` | Create | CatalogManager class + all operations |
| `src/executor.py` | Modify | Call catalog.register() + record_export() after commit |
| `src/processor.py` | Modify | Replace auto-tagger with LLM tags, add year tag |
| `src/intelligence.py` | Modify | Add folder tree + existing tags to LLM prompt |
| `src/config.py` | Modify | ARCHIVE_PATH → ~/Documents/PKM/ |
| `src/cli/main.py` | Modify | Add catalog subcommands |
| `src/mcp_server/server.py` | Modify | Add catalog MCP tools |
| `src/api/dashboard_routes.py` | Modify | Add catalog API endpoints |
| `scripts/rebuild_catalog.py` | Create | Retroactive population script |
| `tests/test_catalog.py` | Create | Tests for CatalogManager |

---

## Success Criteria

1. Every committed file has a catalog entry with complete metadata
2. `catalog search "nutrition"` returns relevant files with source paths and tags
3. `catalog list --sensitive` shows only CUI files
4. Retroactive rebuild populates entries for all 99 existing files
5. Archive folder at ~/Documents/PKM/ is organized with consistent LLM-suggested structure
6. Tags are purposeful (3-5 per file) not shotgun (10+)
7. Year appears as a collection tag on every file where year is extracted
8. Existing tests pass unchanged (catalog is additive)
