# P9 Wave 2: Async Correctness + Performance — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server genuinely concurrent by fixing async-but-synchronous code paths. Eliminate unnecessary I/O (redundant DB connections, full table scans, N+1 queries, model reloading).

**Architecture:** 14 independent fixes. Tasks 2.1 (async) and 2.6 (SQLite connections) are the most impactful. Most others are 1-5 line changes.

**Tech Stack:** Python 3.12+, FastAPI, LanceDB, SQLite, asyncio, threading

**Spec:** `docs/superpowers/specs/2026-03-17-p9-codebase-hardening-design.md` (Section 4)

**Tech Debt Items:** TD-017, TD-021, TD-024, TD-031, TD-032, TD-033, TD-034, TD-035, TD-038, TD-039, TD-040, TD-044, TD-045, TD-046, TD-049

**Prerequisite:** Wave 1 complete (all 9 security fixes committed and verified).

---

## Task List

| # | Task | TD | Files | Effort |
|---|------|-----|-------|--------|
| 2.1 | asyncio.to_thread for blocking I/O | TD-024 | server.py, hybrid_search.py, dashboard_routes.py | ~20 lines |
| 2.2 | Shared LanceDB connection + table cache | TD-031 | v1_routes.py, hybrid_search.py | ~20 lines |
| 2.3 | Tag update via tbl.update() | TD-032 | dashboard_routes.py | 1 line |
| 2.4 | Embedding service singleton | TD-033 | executor.py | 2 lines |
| 2.5 | Column projections + count_rows | TD-034 | v1_routes.py | 3 lines |
| 2.6 | SQLite connection management | TD-017+TD-035 | knowledge_graph.py, catalog_manager.py | ~60 lines |
| 2.7 | file_size before archive | TD-038 | executor.py | 4 lines |
| 2.8 | Thread-safe ResultCache | TD-039 | hybrid_search.py | 6 lines |
| 2.9 | Fix catalog_search tag filter | TD-040 | mcp server.py | 10 lines |
| 2.10 | OrderedDict LRU cache | TD-044 | embedding_service.py | 20 lines |
| 2.11 | threading.Event for commit control | TD-045 | dashboard_routes.py | 15 lines |
| 2.12 | Exception logging in executor | TD-046 | executor.py | 4 lines |
| 2.13 | SettingsManager stat debounce | TD-049 | settings_manager.py | 10 lines |
| 2.14 | Verify dual RAG end-to-end | TD-021 | Manual verification | N/A |
