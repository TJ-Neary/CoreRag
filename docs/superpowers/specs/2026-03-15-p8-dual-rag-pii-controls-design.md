# P8: Dual RAG Database + PII Controls — Design Brief

**Date:** 2026-03-15
**Author:** Claude Opus 4.6 (Session 31)
**Status:** Design Brief (needs full brainstorm → spec → plan cycle)

---

## Context

Session 31 revealed that CoreRag's ingestion pipeline needs more nuanced PII handling. The current binary model (sensitive → redact everything, not sensitive → keep everything) doesn't serve real-world needs:

- Tax documents, legal forms, resumes contain YOUR PII that needs to be searchable but protected
- Training materials, books, building codes contain OTHER PEOPLE's names/emails that are useful data
- Cloud LLM integrations (Kendra's Gemini/Claude APIs) should never receive your actual PII
- The HITL dashboard needs per-file and per-detection control over what gets redacted

## Feature Set

### A. Dual RAG Database Architecture

```
Incoming document
    │
    ├── Main RAG DB (~/.corerag/lancedb/)
    │   └── Redacted copy — YOUR PII replaced with [REDACTED]
    │   └── Searchable by ALL agents (Kendra, Centaur, Claude Desktop)
    │   └── Safe for cloud LLM context windows
    │
    └── Restricted RAG DB (~/.corerag/lancedb-restricted/)
        └── Unredacted copy — CUI_ filename prefix
        └── Local-only access (Ollama, local scripts)
        └── ADMIN role only, never exposed to cloud
        └── Contains full PII for tax/legal/medical search
```

**Archive:** Original files go to `~/Documents/Knowledge/{folder}/` with CUI_ prefix if PII detected. Archive is always unredacted.

### B. Dashboard HITL Controls (Per-File)

1. **"Skip" button** — remove file from queue without committing
2. **Export destination checkboxes** per card:
   - ☑ Main RAG (redacted)
   - ☑ Restricted RAG (unredacted, CUI_)
   - ☑ Obsidian vault (redacted)
   - ☑ Archive (always unredacted original, CUI_ if sensitive)
3. **Redaction editor** — toggle individual PII detections on/off per finding
   - Each detection shows: type, confidence, context snippet, [Keep] / [Redact] toggle
   - User controls exactly what gets redacted vs preserved in the main RAG copy

### C. Ingestion Quality Improvements

1. **LLM-powered tags** — qwen3:32b suggests collection tags based on content understanding (replaces aggressive keyword matcher)
2. **Year as collection tag** — automatically add extracted year (e.g., "2024") as a tag
3. **CUI_ prefix logic change:**
   - Remove: CUI_ on suggested filenames for main RAG (content is redacted)
   - Keep: CUI_ on archive filenames when YOUR PII is detected
   - Keep: CUI_ on restricted RAG filenames (always)
4. **Quality report banner** — display batch validation results (PII rate, errors, extraction warnings) as a dashboard banner after analysis

### D. Documentation

1. **Folder structure UI** — document how the "AI Suggested Folders" feature works and how to use it

## Scope

This is P8 — the next major development phase after P7 (Codebase Evolution). It touches:
- Database layer (new restricted LanceDB instance)
- Executor (dual-track commit with selective redaction)
- Dashboard UI (skip button, export checkboxes, redaction editor, quality banner)
- Search routing (fan-out to both DBs for ADMIN, main-only for VIEWER)
- Processor (LLM-powered tagging, year-as-tag)
- MCP server (expose restricted search tool for ADMIN)

## Test Data

The current inbox (111 files) contains both:
- Public documents (training materials, building codes, books) → Main RAG only
- Sensitive documents (HRCI accommodation form) → Both RAG DBs

This batch serves as the test space for the new system.

## Execution Plan

1. `/superpowers:brainstorm` — full design with TJ's input on edge cases
2. Write spec with detailed data models, API changes, UI mockups
3. `/superpowers:writing-plans` — implementation plan
4. Execute in phases:
   - Phase 1: Skip button + quality banner + LLM tags + year tag (quick wins)
   - Phase 2: Document catalog + archive folder consistency
   - Phase 3: Dual database + export routing + CUI_ logic
   - Phase 4: Redaction editor UI
   - Phase 5: Search fan-out + RBAC integration

### E. Document Catalog & Archive Organization

**Problem:** No catalog maps files across the 4 destinations (main RAG, restricted RAG, Obsidian, archive). No way to answer "where did this file end up?" or "what's in folder X?" Post-commit, the only record is the staging manifest (which gets pruned).

**Document Catalog** — persistent SQLite or JSON mapping:

| Field | Description |
|-------|-------------|
| `original_filename` | Name of the source file |
| `original_path` | Where it was ingested from |
| `archive_path` | Where the original lives in ~/Documents/ |
| `main_rag_doc_id` | Document ID in main LanceDB (null if skipped) |
| `restricted_rag_doc_id` | Document ID in restricted LanceDB (null if not sensitive) |
| `obsidian_path` | Path in Obsidian vault (null if not exported) |
| `category` | LLM-assigned category |
| `year` | Extracted year |
| `tags` | Collection tags |
| `is_sensitive` | Whether PII was detected |
| `ingested_at` | Timestamp |
| `batch_id` | Which batch this came from |

**Archive Folder Consistency:**
- Current: LLM suggests folders per-batch with no memory of previous structure
- Fix: Feed existing archive folder tree to the LLM prompt so it reuses existing folders
- The "AI Suggested Folders" UI should show the existing tree + proposed additions
- Add CLI tool: `python -m src.cli.main catalog list` — show all cataloged files by folder

**Archive path fix:** Currently `ARCHIVE_PATH = ~/Documents` (dumps files into Documents root). Should be `ARCHIVE_PATH = ~/Documents/Knowledge/` with organized subfolders.

### F. Folder Structure Documentation

The "AI Suggested Folders" feature in the dashboard UI:
1. Click "Suggest Folders" → LLM analyzes the batch and proposes a folder hierarchy
2. You can edit folder names and assignments in the UI
3. Click "Save Structure" → sets the `target_folder` for each file in the batch
4. When you "Commit All", files are archived to `ARCHIVE_PATH/{target_folder}/`
5. This only affects the current batch — it does NOT reorganize previously committed files

**When to use it:** Before committing each batch. The structure should be reviewed and saved once per batch.

## Related Work

- **TD-002 (RBAC):** Agent-level access control — resolved Session 31. Foundation for restricted DB access.
- **TD-014 (Sparse vectors):** Blocked on LanceDB. Applies to both main and restricted DBs when unblocked.
- **P7 Wave 4 (Quality gates):** Pre/post-commit validation. Applies to dual-track commits.
- **Enrichment backfill (TD-001):** Phase 1 complete. Phases 2-4 apply to both DBs.
