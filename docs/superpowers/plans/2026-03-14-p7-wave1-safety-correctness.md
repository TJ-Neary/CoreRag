# P7 Wave 1: Safety & Correctness — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 safety and correctness issues that cause silent failures, stale defaults, and misplaced state files.

**Architecture:** Surgical fixes across 9 files. No new modules. No behavior changes beyond fixing bugs. All changes are independently verifiable.

**Tech Stack:** Python 3.12+, FastAPI, FastMCP, LanceDB

**Spec:** `docs/superpowers/specs/2026-03-14-p7-codebase-evolution-design.md` (Wave 1)

**Note:** Any new tech debt discovered during implementation that isn't fixed immediately must be documented in `_DEV/DevPlan.md` and `_DEV/TECH_DEBT.md`.

---

## Chunk 1: MCP Guards, Score Fix, Model Defaults

### Task 1: Replace assert guards in MCP tool handlers (1.1)

Note: Spec item 3.3 ("standardize all 30 handlers") is deferred to Wave 3. This task only replaces the 7 `assert` guards. 10 handlers with no guard (using try/except only) will be addressed in Wave 3.

**Files:**
- Modify: `src/mcp_server/server.py:954,961,970,982,992,999,1006`

- [ ] **Step 1: Identify all 7 assert lines**

Search for `assert _corerag_tools` in the file. The 7 occurrences are at:
- Line 954: `get_document_history`
- Line 961: `get_document_diff`
- Line 970: `restore_document_version`
- Line 982: `analyze_knowledge_gaps`
- Line 992: `get_golden_suggestions`
- Line 999: `approve_golden_suggestion`
- Line 1006: `list_golden_entries`

- [ ] **Step 2: Replace each assert with explicit guard**

Replace each `assert _corerag_tools is not None` with:
```python
    if not _corerag_tools:
        return {"error": "CoreRag tools not initialized"}
```

All 7 replacements follow the same pattern. Each `assert` is a standalone line followed by a `return await` line. Replace each `assert _corerag_tools is not None` line with the two-line guard (if + return error). The following `return await ...` line stays unchanged — it becomes the else path. Verify indentation matches the surrounding code (8 spaces for the `if`, 12 for the `return`). Do each replacement individually to ensure correct whitespace.

- [ ] **Step 3: Verify no remaining asserts**

Run: `grep -n "assert _corerag_tools" src/mcp_server/server.py`
Expected: No output (all replaced)

- [ ] **Step 4: Verify guard pattern consistency**

Run: `grep -c "if not _corerag_tools" src/mcp_server/server.py`
Expected: Count should match the total number of tool handlers that use the guard pattern.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mcp_tools.py -v --tb=short`
Expected: All MCP tool tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/mcp_server/server.py
git commit -m "fix: replace assert guards with explicit checks in MCP tool handlers"
```

---

### Task 2: Normalize API search score semantics (1.2)

**Files:**
- Modify: `src/api/v1_routes.py:342,436`

- [ ] **Step 1: Fix the SearchResultItem score (line 342)**

Change:
```python
score=float(r.get("_distance", 0)),
```
To:
```python
score=max(0.0, 1.0 - float(r.get("_distance", 0))),
```

- [ ] **Step 2: Fix the answer endpoint search score (line 436)**

Change:
```python
"score": float(r.get("_distance", 0)),
```
To:
```python
"score": max(0.0, 1.0 - float(r.get("_distance", 0))),
```

- [ ] **Step 3: Run API tests**

Run: `pytest tests/test_v1_routes.py -v --tb=short`
Expected: All pass. If any test checks exact score values, update to expect the inverted range.

- [ ] **Step 4: Commit**

```bash
git add src/api/v1_routes.py
git commit -m "fix: normalize API search scores to 0-1 similarity (was raw distance)"
```

---

### Task 3: Fix Gemini CLI install URL (1.4)

**Files:**
- Modify: `src/llm/provider.py:378`

- [ ] **Step 1: Fix the error message**

Change line 378:
```python
                    "Gemini CLI not found. Install with: npm install -g @anthropic-ai/gemini-cli"
```
To:
```python
                    "Gemini CLI not found. Install from: https://github.com/google-gemini/gemini-cli"
```

- [ ] **Step 2: Commit**

```bash
git add src/llm/provider.py
git commit -m "fix: correct Gemini CLI install URL (was copy-pasted from Claude CLI)"
```

---

### Task 4: Update OLLAMA_MODEL default + centralize references (1.7)

**Files:**
- Modify: `src/config.py:68`
- Modify: `src/mcp_server/server.py:113`
- Modify: `src/api/v1_routes.py:306,413`
- Modify: `src/api/dashboard_routes.py:819`

- [ ] **Step 1: Update the source of truth default**

In `src/config.py:68`, change:
```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
```
To:
```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b")
```

- [ ] **Step 2: Fix src/mcp_server/server.py:113**

Change:
```python
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
```
To:
```python
    from src.config import OLLAMA_MODEL as ollama_model
```

Note: `ollama_model` is used later in the function as an argument to `create_hyde_expander()`. Place this import at the top of the function body (near the existing `from src.llm.provider import get_default_provider` import) rather than inline at line 113.

- [ ] **Step 3: Fix src/api/v1_routes.py:306 and 413**

Both lines follow this pattern inside a function body:
```python
model=os.getenv("OLLAMA_MODEL", "qwen2.5:32b"),
```
Replace both with:
```python
model=OLLAMA_MODEL,
```
Append `OLLAMA_MODEL` to the existing config import line (line 40): `from src.config import DB_PATH, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, OLLAMA_MODEL, STATE_DIR, VAULT_PATHS`.

- [ ] **Step 4: Fix src/api/dashboard_routes.py:819**

Change:
```python
            ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
```
To:
```python
            ollama_model = OLLAMA_MODEL
```
Add `from src.config import OLLAMA_MODEL` to the router factory function's imports or to the file-level imports.

- [ ] **Step 5: Verify no remaining raw getenv calls**

Run: `grep -rn 'os.getenv("OLLAMA_MODEL"' src/`
Expected: Only `src/config.py:68` remains (the source of truth).

- [ ] **Step 6: Run tests**

Run: `pytest tests/ -v --tb=short -x`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/mcp_server/server.py src/api/v1_routes.py src/api/dashboard_routes.py
git commit -m "fix: centralize OLLAMA_MODEL references and update default to qwen3:32b"
```

---

## Chunk 2: Path Fixes, Auth Warning, Dep Cleanup

### Task 5: Anchor staging manifest to STATE_DIR (1.5)

**Files:**
- Modify: `src/staging.py:10`

- [ ] **Step 1: Add config import**

Add after the existing imports (before line 10):
```python
from src import config
```

- [ ] **Step 2: Update the path constant**

Change line 10:
```python
STAGING_MANIFEST_PATH = Path("staging_manifest.json")
```
To:
```python
STAGING_MANIFEST_PATH = config.STATE_DIR / "staging_manifest.json"
```

- [ ] **Step 3: Check for existing CWD-based files to migrate**

Run: `ls -la staging_manifest.json 2>/dev/null`
If the file exists in the project root, copy it: `cp staging_manifest.json ~/.corerag/staging_manifest.json`

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -x`
Expected: All pass. Tests that mock staging may need the new path — check for failures.

- [ ] **Step 5: Commit**

```bash
git add src/staging.py
git commit -m "fix: anchor staging manifest to STATE_DIR instead of CWD"
```

---

### Task 6: Anchor corrections log to STATE_DIR (1.6)

**Files:**
- Modify: `src/correction_log.py:9`

- [ ] **Step 1: Add config import**

Add after the existing imports (before line 9):
```python
from src import config
```

- [ ] **Step 2: Update the path constant**

Change line 9:
```python
CORRECTIONS_PATH = Path("corrections_log.json")
```
To:
```python
CORRECTIONS_PATH = config.STATE_DIR / "corrections_log.json"
```

- [ ] **Step 3: Commit**

```bash
git add src/correction_log.py
git commit -m "fix: anchor corrections log to STATE_DIR instead of CWD"
```

---

### Task 7: Warn when API auth is disabled (1.8)

**Files:**
- Modify: `src/server.py` (near the lifespan or app creation)

- [ ] **Step 1: Add auth warning in the app factory or lifespan**

Find the app creation or lifespan section. After the existing API key configuration, add:
```python
if not os.getenv("CORERAG_API_KEY"):
    logger.warning(
        "API authentication disabled — all /api/v1/ endpoints are open. "
        "Set CORERAG_API_KEY in .env to enable authentication."
    )
```

Insert inside the `lifespan` async context manager function (after line 64, just before `yield`). This ensures the warning appears at server startup, not at import time.

- [ ] **Step 2: Run server smoke test**

Run: `pytest tests/test_v1_routes.py -v --tb=short -x`
Expected: All pass (test env has `CORERAG_API_KEY=test_api_key_not_real` per conftest.py so warning should NOT appear in tests).

- [ ] **Step 3: Commit**

```bash
git add src/server.py
git commit -m "fix: warn at startup when API authentication is disabled"
```

---

### Task 8: Remove unused heavy dependencies (1.9)

**Files:**
- Modify: `pyproject.toml:26,29`

- [ ] **Step 1: Verify neither package is imported**

Run: `grep -rn "import unstructured\|from unstructured\|import pdfplumber\|from pdfplumber" src/`
Expected: No output (confirming neither is used).

- [ ] **Step 2: Remove the dependencies**

Delete these two lines from `pyproject.toml` `[project.dependencies]`:
```
    "unstructured[all-docs]>=0.10.0",
    "pdfplumber>=0.9.0",
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ --tb=short -x`
Expected: All pass (no code depends on these packages).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: remove unused unstructured and pdfplumber dependencies"
```

---

## Chunk 3: Update Tech Debt + DevPlan

### Task 9: Update TECH_DEBT.md with new findings

**Files:**
- Modify: `_DEV/TECH_DEBT.md`

- [ ] **Step 1: Check current max ID**

Read `_DEV/TECH_DEBT.md` and find the highest TD-NNN ID. As of this session: TD-006 (now resolved). New items start at TD-007.

- [ ] **Step 2: Add new tech debt items**

Add these entries for findings NOT fixed in Wave 1 (Wave 2-4 items):

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| TD-007 | REST API search bypasses HybridSearcher — split-quality results | High | Open |
| TD-008 | Three divergent ingest paths — API-ingested docs are second-class | High | Open |
| TD-009 | EmbeddingService re-initialized per API request | Medium | Open |
| TD-010 | Chat endpoint bypasses LLMProvider abstraction | Medium | Open |
| TD-011 | Module-level singletons in processor.py cause import-time model load | Medium | Open |
| TD-012 | pyproject.toml dependency versions far below installed versions | Medium | Open |
| TD-013 | Staging manifest grows unbounded | Medium | Open |

Note: These IDs (TD-007 through TD-013) supersede the preliminary numbering in the spec document. The spec used TD-007 for assert guards and TD-011 for CWD paths, but those are resolved by this plan's Tasks 1, 5, and 6 — so the IDs are reassigned to unresolved items only.

For each, add a full entry following the TD-NNN format in the file (severity, category, found date, files, description, impact, suggested fix, trigger). Reference the P7 spec for details: `docs/superpowers/specs/2026-03-14-p7-codebase-evolution-design.md`.

Update the Summary table counts accordingly.

- [ ] **Step 3: Update DevPlan.md with P7 roadmap**

Add a new section to `_DEV/DevPlan.md` documenting the P7 Codebase Evolution:

```markdown
## P7: Codebase Evolution (Session 31+)

Full codebase audit produced a 4-wave improvement spec:
- **Wave 1: Safety & Correctness** — COMPLETE (Session 31)
- **Wave 2: Performance & Search Quality** — Pending (7 items, ~160 lines)
- **Wave 3: Pipeline Unification & Test Coverage** — Pending (8 items, ~575 lines)
- **Wave 4: Database Evolution & Enhancements** — Pending (12 items, cherry-pick)

Full spec: `docs/superpowers/specs/2026-03-14-p7-codebase-evolution-design.md`
Tech debt items: TD-007 through TD-013
```

- [ ] **Step 4: Commit**

```bash
git add _DEV/TECH_DEBT.md _DEV/DevPlan.md
git commit -m "docs: add P7 codebase evolution tech debt items and roadmap"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --tb=short`
Expected: 609 tests pass, no regressions.

- [ ] **Verify no remaining issues**

Run: `grep -rn 'assert _corerag_tools' src/` → should be empty
Run: `grep -rn 'os.getenv("OLLAMA_MODEL"' src/` → should only show config.py
Run: `grep -rn 'qwen2.5:32b' src/` → should only show .env.example and possibly comments

---

## Summary

| Task | Spec Item | Files Changed | Lines |
|------|-----------|---------------|-------|
| 1 | 1.1 + 3.3 | server.py | ~14 |
| 2 | 1.2 | v1_routes.py | 2 |
| 3 | 1.4 | provider.py | 1 |
| 4 | 1.7 | config.py, server.py, v1_routes.py, dashboard_routes.py | ~8 |
| 5 | 1.5 | staging.py | 2 |
| 6 | 1.6 | correction_log.py | 2 |
| 7 | 1.8 | server.py | 4 |
| 8 | 1.9 | pyproject.toml | -2 |
| 9 | — | TECH_DEBT.md, DevPlan.md | ~80 |

**Total: 9 tasks, 8 commits, ~9 source files, under 1 hour.**
