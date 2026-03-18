# P9 Wave 1: Security + Data Protection — Implementation Plan

> **Status: COMPLETE** — All 9 security tasks executed (Session 33, 2026-03-17/18). 924 tests passing.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Eliminate all critical and high security vulnerabilities identified in the P9 5-agent audit. Protect PII data paths, prevent injection attacks, fix XSS, harden permission defaults.

**Architecture:** 9 independent security fixes across the CoreRag codebase. Each task touches different files with no shared dependencies, so all can run in parallel. The fixes address: PII redaction fail-safe, CLI prompt injection, path traversal, XSS, unauthenticated endpoint, SQL injection pattern, permission escalation, CSRF, and error message leakage.

**Tech Stack:** Python 3.12+, FastAPI, LanceDB, SQLite, Jinja2 HTML templates, asyncio subprocess

**Spec:** `docs/superpowers/specs/2026-03-17-p9-codebase-hardening-design.md` (Section 3)

**Tech Debt Items:** TD-025, TD-026, TD-027, TD-028, TD-029, TD-030, TD-041, TD-042, TD-043

---

## Context for Cold-Start Agents

CoreRag is a local-first, privacy-preserving knowledge engine running on Apple Silicon. It ingests documents, detects PII via Presidio/spaCy, and stores content in two LanceDB vector databases:
- **Main** (`~/.corerag/lancedb/`) -- redacted content (PII replaced with `[REDACTED-TYPE]`)
- **Restricted** (`~/.corerag/lancedb-restricted/`) -- unredacted content (raw PII for authorized local queries)

The system has a web dashboard at `localhost:8000`, a REST API (`/api/v1/*`), and an MCP server (stdio transport for Claude Desktop). Authentication uses per-agent API keys managed by `SettingsManager` (`~/.corerag/settings.yaml`).

**Why this matters:** The restricted database contains SSNs, bank account numbers, medical records, and other sensitive PII. Security vulnerabilities in this system can expose real personal data.

**How to run tests:** `pytest` from the project root (venv must be activated: `source venv/bin/activate`). Config: `pyproject.toml` with `--cov=src --cov-report=term-missing` and `asyncio_mode = "auto"`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/executor.py` | Modify | PII redaction fail-safe (Task 1) |
| `src/llm/provider.py` | Modify | CLI providers stdin refactor (Task 2) |
| `src/api/dashboard_routes.py` | Modify | Cold storage path validation (Task 3) |
| `src/ui/templates/dashboard.html` | Modify | XSS escaping (Task 4) |
| `src/api/v1_routes.py` | Modify | Auth on /vaults, error sanitization (Tasks 5, 9) |
| `src/graph/knowledge_graph.py` | Modify | SQL identifier safety (Task 6) |
| `src/settings/settings_manager.py` | Modify | Permission defaults (Task 7) |
| `src/server.py` | Modify | CSRF middleware, open-mode permissions (Tasks 7, 8) |
| `src/api/settings_routes.py` | Modify | Error sanitization (Task 9) |
| `tests/test_executor.py` | Modify | PII fail-safe test (Task 1) |
| `tests/test_llm_provider.py` | Modify | Stdin test (Task 2) |
| `tests/test_dashboard_routes.py` | Modify | Path validation test (Task 3) |
| `tests/test_v1_routes.py` | Modify | Auth test (Task 5) |
| `tests/test_settings.py` | Modify | Permission defaults test (Task 7) |

---

### Task 1: PII Redaction Fail-Safe (TD-025) -- CRITICAL

**Why:** `_redact_pii()` in `src/executor.py` catches all exceptions and returns the original unredacted text. If Presidio or spaCy fails (OOM, model load error), sensitive documents are silently exported to the Obsidian vault and main RAG database with raw PII (SSNs, bank accounts, names). The calling code already handles `ProcessingError` by setting the staging item to `error` status.

**Current code (src/executor.py lines 88-92):**
```python
    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"PII redaction failed for {file_name}: {e}", exc_info=True)
        return text  # Fall back to original text rather than blocking
```

**Files:**
- Modify: `src/executor.py:88-92`
- Test: `tests/test_executor.py`

- [x] **Step 1: Write the failing test**

In `tests/test_executor.py`, add a test that verifies `_redact_pii` raises `ProcessingError` when the Presidio analyzer fails:

```python
def test_redact_pii_raises_on_presidio_failure():
    """TD-025: PII redaction must NOT silently return unredacted text on failure."""
    from unittest.mock import patch, MagicMock
    from src.executor import _redact_pii
    from src.exceptions import ProcessingError

    # Mock PrivacyScanner to raise (simulating spaCy OOM or model load failure)
    # _redact_pii uses PrivacyScanner from src.utils.privacy_audit, not AnalyzerEngine directly
    with patch("src.executor.PrivacyScanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.side_effect = RuntimeError("spaCy model failed to load")
        mock_scanner_cls.return_value = mock_scanner

        with pytest.raises(ProcessingError, match="PII redaction failed"):
            _redact_pii("Text with SSN 123-45-6789", "test_doc.pdf")
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_executor.py::test_redact_pii_raises_on_presidio_failure -v`
Expected: FAIL -- currently returns the original text instead of raising

- [x] **Step 3: Implement the fix**

In `src/executor.py`, change lines 88-92. The `except ProcessingError: raise` stays. Change the generic handler:

```python
    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"PII redaction failed for {file_name}: {e}", exc_info=True)
        raise ProcessingError(f"PII redaction failed for {file_name}: {e}") from e
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_executor.py::test_redact_pii_raises_on_presidio_failure -v`
Expected: PASS

- [x] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/test_executor.py -v`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add src/executor.py tests/test_executor.py
git commit -m "fix: PII redaction raises on failure instead of silent fallback (TD-025)"
```

---

### Task 2: Gemini + Codex CLI Stdin Refactor (TD-026) -- CRITICAL

**Why:** `GeminiCliProvider.generate()` and `CodexCliProvider.generate()` pass untrusted document content as a `-p` CLI argument. A crafted document could inject CLI flags. `ClaudeCliProvider` already uses the safe stdin pattern -- this task makes the other two providers match.

**Current code (src/llm/provider.py lines 403-416) -- Gemini uses -p:**
```python
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        args = [
            self._cli_path,
            "-p",
            combined_prompt,
            "--output-format",
            "json",
            "-m",
            self._cli_model,
        ]
```

**Reference pattern (src/llm/provider.py lines 314-324) -- Claude uses stdin:**
```python
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input_data), timeout=timeout
        )
```

**Current _run_process (lines 460-475) -- uses stdin=DEVNULL:**
```python
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
```

**Files:**
- Modify: `src/llm/provider.py:395-495`
- Test: `tests/test_llm_provider.py`

- [x] **Step 1: Write the failing test for Gemini CLI stdin**

In `tests/test_llm_provider.py`, add:

```python
@pytest.mark.asyncio
async def test_gemini_cli_uses_stdin_not_dash_p():
    """TD-026: GeminiCliProvider must pass prompt via stdin, not -p argument."""
    from unittest.mock import patch, AsyncMock, MagicMock

    provider = GeminiCliProvider(config=LLMConfig())

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(
        b'{"candidates": [{"content": {"parts": [{"text": "response"}]}}]}',
        b"",
    ))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_process) as mock_exec:
        await provider.generate("system prompt", "user prompt with --dangerous-flag")

        # Verify -p is NOT in the args
        call_args = mock_exec.call_args
        args_list = call_args[0]  # positional args
        assert "-p" not in args_list, "Prompt must be passed via stdin, not -p argument"

        # Verify stdin=PIPE was used (not DEVNULL)
        kwargs = call_args[1]
        assert kwargs.get("stdin") == asyncio.subprocess.PIPE
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_provider.py::test_gemini_cli_uses_stdin_not_dash_p -v`
Expected: FAIL -- currently uses `-p`

- [x] **Step 3: Refactor GeminiCliProvider.generate()**

In `src/llm/provider.py`, change the `generate()` method (lines 403-416). Remove `-p` and `combined_prompt` from args. Pass via stdin through `_run_process`:

```python
        # Build args WITHOUT -p (prompt goes via stdin for injection safety)
        args = [
            self._cli_path,
            "--output-format",
            "json",
            "-m",
            self._cli_model,
        ]

        try:
            stdout, stderr, returncode = await self._run_process(
                args, input_data=combined_prompt.encode(), timeout=self.config.timeout
            )
```

- [x] **Step 4: Refactor _run_process to accept input_data**

Change `_run_process()` (around line 460) to accept `input_data` parameter and use `stdin=PIPE`:

```python
    async def _run_process(
        self,
        args: list[str],
        input_data: bytes = b"",
        timeout: float = 120.0,
    ) -> tuple[bytes, bytes, int]:
        """Run subprocess with stdin support and Python 3.13 compatibility."""
        import subprocess as sp
        env = self._build_env()
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data), timeout=timeout
            )
            return stdout or b"", stderr or b"", process.returncode or 0
        except NotImplementedError:
            def _run() -> tuple[bytes, bytes, int]:
                try:
                    result = sp.run(
                        args,
                        input=input_data,
                        capture_output=True,
                        env=env,
                        timeout=timeout,
                    )
                    return result.stdout or b"", result.stderr or b"", result.returncode
                except sp.TimeoutExpired as exc:
                    raise TimeoutError(str(exc)) from exc
            return await asyncio.to_thread(_run)
```

- [x] **Step 5: Apply same change to CodexCliProvider if it uses -p**

Check `CodexCliProvider.generate()` -- if it also passes the prompt via `-p`, apply the same stdin refactor.

- [x] **Step 6: Run tests**

Run: `pytest tests/test_llm_provider.py -v`
Expected: All pass

- [x] **Step 7: Commit**

```bash
git add src/llm/provider.py tests/test_llm_provider.py
git commit -m "fix: CLI providers use stdin instead of -p for prompt injection safety (TD-026)"
```

---

### Task 3: Cold Storage Path Validation (TD-027) -- CRITICAL

**Why:** The `/api/catalog/cold-storage` endpoint accepts `destination_root` from the POST body with no validation and passes it directly to `shutil.move()`. Any localhost process can move PII-containing archive files to arbitrary filesystem paths. `makedirs(parents=True)` creates arbitrary directory trees.

**Current code (src/api/dashboard_routes.py lines 340-354):**
```python
    @router.post("/api/catalog/cold-storage")
    async def migrate_to_cold_storage(request: Request) -> dict:
        data = await request.json()
        doc_ids = data.get("doc_ids", [])
        device_name = data.get("device_name", "")
        destination = data.get("destination_root", "")
        if not doc_ids or not device_name or not destination:
            return {"error": "Missing required fields: doc_ids, device_name, destination_root"}
        try:
            catalog = CatalogManager()
            return catalog.migrate_to_cold(doc_ids, device_name, destination)
```

**Current migrate_to_cold (src/catalog/catalog_manager.py lines 630-657):**
```python
        dest_base = Path(destination_root) / "PKM"
        # ... no path validation ...
        dest_path = dest_base / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dest_path))
```

**Files:**
- Modify: `src/api/dashboard_routes.py:340-354`
- Test: `tests/test_dashboard_routes.py`

- [x] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_cold_storage_rejects_path_traversal(client):
    """TD-027: Cold storage must reject paths outside allowed roots."""
    payloads = [
        {"doc_ids": ["test"], "device_name": "evil", "destination_root": "/etc"},
        {"doc_ids": ["test"], "device_name": "evil", "destination_root": "../../../tmp"},
        {"doc_ids": ["test"], "device_name": "evil", "destination_root": "/"},
        {"doc_ids": ["test"], "device_name": "evil", "destination_root": "/usr/local"},
    ]
    for payload in payloads:
        response = client.post("/api/catalog/cold-storage", json=payload)
        data = response.json()
        assert "error" in data, (
            f"Path traversal not blocked for: {payload['destination_root']}"
        )
        assert "must be" in data["error"].lower() or "not allowed" in data["error"].lower()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_routes.py::test_cold_storage_rejects_path_traversal -v`
Expected: FAIL -- currently passes the path through unvalidated

- [x] **Step 3: Add path validation**

In `src/api/dashboard_routes.py`, add validation after line 349 (after the `not destination` check), before the `catalog.migrate_to_cold()` call:

```python
        # Validate destination path (TD-027: prevent path traversal)
        from pathlib import Path as _Path
        dest_resolved = _Path(destination).resolve()
        allowed_roots = [_Path("/Volumes"), _Path.home() / "Documents"]
        if not any(str(dest_resolved).startswith(str(root)) for root in allowed_roots):
            return {"error": "Destination must be under /Volumes/ or ~/Documents"}
        if ".." in _Path(destination).parts:
            return {"error": "Path traversal (..) not allowed"}
        if not dest_resolved.exists() or not dest_resolved.is_dir():
            return {"error": "Destination must be an existing directory"}
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard_routes.py::test_cold_storage_rejects_path_traversal -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/api/dashboard_routes.py tests/test_dashboard_routes.py
git commit -m "fix: validate cold storage destination path against traversal (TD-027)"
```

---

### Task 4: Dashboard XSS Fix (TD-028) -- HIGH

**Why:** Multiple dashboard panels inject server-returned data (document filenames, content previews, memory facts, correction fields, tag values) into `innerHTML` without HTML escaping. A document with `<script>` in its filename or content would run JavaScript in the browser. The dashboard has full API access including the restricted PII database, so XSS could exfiltrate sensitive data.

**Current code examples:**

RAG browser (line 1840): `<p class="text-white text-sm font-medium truncate">${f.source_path}</p>`

Memory panel (line 1892): `<p class="text-white text-sm">${f.content}</p>`

Tag pills (line 1447): `pill.innerHTML = \`${tag}<button onclick="removeTag('${id}','${tag}')" ...>&times;</button>\`;`

**Files:**
- Modify: `src/ui/templates/dashboard.html:1447,1837-1848,1889-1920`

- [x] **Step 1: Add escapeHtml() function**

Near the top of the `<script>` section in `dashboard.html`, add:

```javascript
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
```

- [x] **Step 2: Escape RAG browser data (lines 1837-1848)**

Change line 1840:
`${f.source_path}` to `${escapeHtml(f.source_path)}`

Change line 1842:
`${f.preview}` to `${escapeHtml(f.preview)}`

- [x] **Step 3: Escape memory panel data (lines 1889-1903)**

Change line 1892: `${f.content}` to `${escapeHtml(f.content)}`

Change line 1894: `${f.category}` to `${escapeHtml(f.category)}`

Change line 1895: `${f.source}` to `${escapeHtml(f.source)}`

- [x] **Step 4: Escape corrections panel data (lines 1911-1918)**

Change line 1912: `${field}` to `${escapeHtml(field)}`

Change line 1913 (two places): `${diff.ai || '?'}` to `${escapeHtml(diff.ai || '?')}` and `${diff.human || '?'}` to `${escapeHtml(diff.human || '?')}`

Change line 1917: `${c.file || 'Unknown file'}` to `${escapeHtml(c.file || 'Unknown file')}`

- [x] **Step 5: Fix tag pill injection (line 1447)**

Replace the innerHTML assignment:
```javascript
pill.innerHTML = `${tag}<button onclick="removeTag('${id}','${tag}')" class="text-blue-400 hover:text-white ml-1">&times;</button>`;
```

With DOM construction:
```javascript
const tagSpan = document.createElement('span');
tagSpan.textContent = tag;
const btn = document.createElement('button');
btn.innerHTML = '&times;';
btn.className = 'text-blue-400 hover:text-white ml-1';
btn.onclick = () => removeTag(id, tag);
pill.appendChild(tagSpan);
pill.appendChild(btn);
```

- [x] **Step 6: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "fix: escape all innerHTML user-data injections in dashboard (TD-028)"
```

---

### Task 5: Auth on /api/v1/vaults (TD-029) -- HIGH

**Why:** The `/api/v1/vaults` endpoint returns absolute filesystem paths (including the user's home directory) to Obsidian vaults with no authentication.

**Current code (src/api/v1_routes.py lines 978-986):**
```python
    @router.get("/vaults")
    async def list_vaults():
        """List configured Obsidian vaults."""
        return {
            "vaults": {
                name: {"path": str(path), "exists": path.exists()}
                for name, path in VAULT_PATHS.items()
            }
        }
```

**Files:**
- Modify: `src/api/v1_routes.py:978-986`
- Test: `tests/test_v1_routes.py`

- [x] **Step 1: Add auth dependency**

Change:
```python
    @router.get("/vaults")
    async def list_vaults():
```
To:
```python
    @router.get("/vaults")
    async def list_vaults(permissions: dict[str, bool] = Depends(check_permissions)):
```

- [x] **Step 2: Run tests**

Run: `pytest tests/test_v1_routes.py -v`
Expected: All pass. Note: if the test client runs in open mode (no agents configured), the endpoint will still return 200. The fix ensures non-localhost external callers get 401.

- [x] **Step 3: Commit**

```bash
git add src/api/v1_routes.py
git commit -m "fix: require auth on /api/v1/vaults endpoint (TD-029)"
```

---

### Task 6: KG Schema Migration SQL Safety (TD-030) -- HIGH

**Why:** `_migrate_schema()` uses f-string interpolation for SQL column names. Currently safe (hardcoded values), but the pattern is dangerous and the project has `safe_identifier()` for exactly this.

**Current code (src/graph/knowledge_graph.py lines 296-301):**
```python
                cursor.execute(
                    f"ALTER TABLE entities ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                if col in ("first_seen", "last_seen"):
                    cursor.execute(f"UPDATE entities SET {col} = created_at WHERE {col} = ''")
```

**Files:**
- Modify: `src/graph/knowledge_graph.py:285-320`

- [x] **Step 1: Add import and apply to entity columns**

Add at top of `_migrate_schema`:
```python
from src.utils.query_sanitize import safe_identifier
```

Change entity column loop (lines 296-301):
```python
                col_s = safe_identifier(col)
                type_s = safe_identifier(col_type)
                cursor.execute(
                    f"ALTER TABLE entities ADD COLUMN {col_s} {type_s} DEFAULT {default}"
                )
                if col in ("first_seen", "last_seen"):
                    cursor.execute(f"UPDATE entities SET {col_s} = created_at WHERE {col_s} = ''")
```

- [x] **Step 2: Apply to relationship columns (lines 312-317)**

Same pattern for the relationship column loop.

- [x] **Step 3: Run tests**

Run: `pytest tests/test_knowledge_graph.py -v`
Expected: All pass

- [x] **Step 4: Commit**

```bash
git add src/graph/knowledge_graph.py
git commit -m "fix: use safe_identifier() in KG schema migration SQL (TD-030)"
```

---

### Task 7: Permission Defaults Hardening (TD-042) -- MEDIUM

**Why:** Legacy key migration and open mode silently grant `search_restricted: True`, giving access to unredacted PII without explicit opt-in. Combined with no CSRF, a remote attacker could access the restricted database.

**Current code -- legacy migration (src/settings/settings_manager.py lines 314-318):**
```python
        agents["_legacy"] = {
            "api_key_env": "CORERAG_API_KEY",
            "permissions": {perm: True for perm in DEFAULT_PERMISSIONS},
        }
        logger.info("Migrated legacy CORERAG_API_KEY to _legacy agent.")
```

**Current code -- open mode (src/server.py line 169):**
```python
            perms: dict[str, bool] = {p: True for p in DEFAULT_PERMISSIONS}
```

**Files:**
- Modify: `src/settings/settings_manager.py:314-318`
- Modify: `src/server.py:169`
- Test: `tests/test_settings.py`

- [x] **Step 1: Write the failing test**

```python
def test_legacy_migration_excludes_search_restricted(tmp_path):
    """TD-042: Legacy key migration must NOT grant search_restricted."""
    import os
    os.environ["CORERAG_API_KEY"] = "test_legacy_key_not_real"
    try:
        mgr = SettingsManager(settings_path=tmp_path / "settings.yaml")
        mgr.load()
        agents = mgr.get_agents()
        assert "_legacy" in agents
        assert agents["_legacy"]["permissions"]["search_restricted"] is False
    finally:
        del os.environ["CORERAG_API_KEY"]
```

- [x] **Step 2: Fix legacy migration**

In `settings_manager.py`, change lines 314-318:
```python
        perms = {perm: True for perm in DEFAULT_PERMISSIONS}
        perms["search_restricted"] = False  # Must be explicitly enabled
        agents["_legacy"] = {
            "api_key_env": "CORERAG_API_KEY",
            "permissions": perms,
        }
        logger.warning(
            "Migrated legacy CORERAG_API_KEY to _legacy agent with search_restricted=False. "
            "Review permissions in the Settings tab."
        )
```

- [x] **Step 3: Fix open-mode permissions**

In `server.py`, change line 169:
```python
            perms: dict[str, bool] = {p: True for p in DEFAULT_PERMISSIONS}
            perms["search_restricted"] = False  # Must be explicitly configured
```

- [x] **Step 4: Run tests**

Run: `pytest tests/test_settings.py -v`
Expected: All pass

- [x] **Step 5: Commit**

```bash
git add src/settings/settings_manager.py src/server.py tests/test_settings.py
git commit -m "fix: exclude search_restricted from legacy migration and open mode (TD-042)"
```

---

### Task 8: CSRF Origin Check (TD-041) -- MEDIUM

**Why:** Dashboard mutation endpoints accept POST with no CSRF protection. A malicious website can trigger file commits via cross-origin requests to localhost (DNS rebinding).

**Files:**
- Modify: `src/server.py`

- [x] **Step 1: Add CSRF middleware**

In `src/server.py`, inside `create_app()` after the app is created:

First, add the import if not already present:
```python
from fastapi.responses import JSONResponse
```

Then add the middleware:

```python
    @app.middleware("http")
    async def csrf_origin_check(request: Request, call_next):
        """Block cross-origin mutation requests (CSRF/DNS rebinding protection)."""
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("origin", "")
            if origin and not origin.startswith(("http://localhost", "http://127.0.0.1")):
                return JSONResponse(
                    status_code=403,
                    content={"error": "Cross-origin request blocked"},
                )
        return await call_next(request)
```

Note: Requests without `Origin` header (curl, MCP stdio, API clients) pass through -- they don't come from browsers.

- [x] **Step 2: Run tests**

Run: `pytest -v`
Expected: All pass (test client uses localhost)

- [x] **Step 3: Commit**

```bash
git add src/server.py
git commit -m "fix: add CSRF origin check middleware for dashboard endpoints (TD-041)"
```

---

### Task 9: Error Message Sanitization (TD-043) -- MEDIUM

**Why:** Generic exception handlers return `str(e)` in JSON responses. Python exceptions contain file paths, class names, and schema details -- information disclosure to external API callers.

**Current code pattern (src/api/v1_routes.py lines 451-456):**
```python
        except Exception as e:
            logger.error(f"Search API failed: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "results": [], "total": 0, "query": query},
            )
```

**Files:**
- Modify: `src/api/v1_routes.py` (lines ~451, ~581, ~733, ~817, ~904, ~970)
- Modify: `src/api/settings_routes.py` (lines ~62, ~190, ~293)
- Modify: `src/api/dashboard_routes.py` (lines ~337, ~354)

- [x] **Step 1: Fix v1_routes.py**

For each generic `except Exception as e:` handler, change `"error": str(e)` to `"error": "Internal server error"`. Keep `str(e)` for `CoreRagError` handlers (designed to be user-facing).

- [x] **Step 2: Fix settings_routes.py**

Same pattern change at lines ~62, ~190, ~293.

- [x] **Step 3: Fix dashboard_routes.py**

Change `return {"error": str(e)}` to `return {"error": "Internal server error"}` in generic exception handlers (lines ~337, ~354).

- [x] **Step 4: Run tests**

Run: `pytest tests/test_v1_routes.py tests/test_settings.py -v`
Expected: All pass. If any tests assert on specific error messages from generic exceptions, update them to check for "Internal server error".

- [x] **Step 5: Commit**

```bash
git add src/api/v1_routes.py src/api/settings_routes.py src/api/dashboard_routes.py
git commit -m "fix: sanitize error messages in API responses (TD-043)"
```

---

## Post-Wave Verification

After all 9 tasks are complete:

- [x] **Run full test suite:** `pytest` -- all 693+ tests must pass
- [x] **Run security scanner:** `./scripts/security_scan.sh --staged` -- must pass clean
- [x] **Manual dashboard check:** Start server (`python -m src.server`), open `localhost:8000`, verify dashboard loads and basic operations work
- [x] **Update TECH_DEBT.md:** Mark TD-025, TD-026, TD-027, TD-028, TD-029, TD-030, TD-041, TD-042, TD-043 as Resolved with session reference

---

## Waves 2-4

Wave 2 (Async + Performance), Wave 3 (Test Coverage), and Wave 4 (Docs + Config) will be planned in separate documents after Wave 1 is complete and verified:

- `docs/superpowers/plans/2026-03-17-p9-wave2-async-performance.md`
- `docs/superpowers/plans/2026-03-17-p9-wave3-test-coverage.md`
- `docs/superpowers/plans/2026-03-17-p9-wave4-docs-config-cleanup.md`
