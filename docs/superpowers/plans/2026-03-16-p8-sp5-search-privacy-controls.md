# P8 SP5: Search Fan-out + Privacy Controls — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-agent access control with permission toggles, a Settings tab for managing agents/LLM/models/databases, and enforce permissions across all API and MCP endpoints.

**Architecture:** New `SettingsManager` module reads `~/.corerag/settings.yaml` for agent configs and permissions. Replaces the single-key auth with per-agent API keys and per-action permission toggles. Settings tab in dashboard provides full GUI management. All defaults are least-privilege (false). Localhost trust boundary for dashboard access.

**Tech Stack:** Python 3.12+, FastAPI, PyYAML, Tailwind CSS, vanilla JavaScript

**Spec:** `docs/superpowers/specs/2026-03-16-p8-sp5-search-privacy-controls-spec.md`

**Context files to read before implementing:**
- `src/server.py` — current `verify_api_key()`, FastAPI lifespan
- `src/auth/access_control.py` — existing RBAC scaffold (being deprecated)
- `src/api/v1_routes.py` — current Depends(verify_api_key) on all routes
- `src/mcp_server/server.py` — MCP tool definitions
- `src/mcp_server/tools.py` — CoreRagTools (where MCP permission checks go)
- `src/config.py` — STATE_DIR, current constants
- `src/llm/provider.py` — LLM provider singleton, factory

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/settings/__init__.py` | Create | Package init |
| `src/settings/settings_manager.py` | Create | SettingsManager: YAML read/write, agent CRUD, key cache, .env management |
| `src/config.py` | Modify | Add SETTINGS_PATH constant |
| `src/server.py` | Modify | Replace verify_api_key with check_permissions, mount settings routes |
| `src/api/settings_routes.py` | Create | Settings API endpoints (dashboard-only) |
| `src/api/v1_routes.py` | Modify | Replace Depends(verify_api_key) with permission checks |
| `src/mcp_server/server.py` | Modify | Load _mcp permissions at startup |
| `src/mcp_server/tools.py` | Modify | Permission checks on tool methods |
| `src/ui/templates/dashboard.html` | Modify | Settings tab (agents, LLM, models, DB) |
| `settings.example.yaml` | Create | Example settings file (committed) |
| `tests/test_settings.py` | Create | SettingsManager tests |
| `tests/test_permissions.py` | Create | Permission enforcement tests |

---

## Task 1: SettingsManager Module

**Files:**
- Create: `src/settings/__init__.py`
- Create: `src/settings/settings_manager.py`
- Create: `settings.example.yaml`
- Modify: `src/config.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Add SETTINGS_PATH to config**

In `src/config.py`, after STATE_DIR:
```python
SETTINGS_PATH = STATE_DIR / "settings.yaml"
```

- [ ] **Step 2: Create SettingsManager**

Create `src/settings/__init__.py` (empty) and `src/settings/settings_manager.py` with:

- `SettingsManager` class with `settings_path` parameter (defaults to `config.SETTINGS_PATH`)
- `load()` — read YAML, cache with mtime check. If file doesn't exist, create with factory defaults.
- `save()` — write current settings to YAML
- `get_agents()` — return all agent configs
- `get_agent(name)` — return single agent config
- `get_agent_by_key(api_key)` — lookup agent by API key value (uses cached key→name dict). Returns None for unknown keys.
- `create_agent(name)` — validate name (`[a-zA-Z0-9_-]{1,64}`), generate API key via `secrets.token_urlsafe(32)`, write key to `.env` as `CORERAG_AGENT_{NAME}_KEY`, add to settings.yaml with default permissions (all false). Return the generated key.
- `update_agent(name, permissions)` — update permissions dict
- `delete_agent(name)` — remove from settings.yaml, remove key from `.env`
- `get_llm_config()` — return provider/model from settings
- `update_llm_config(provider, model, api_key_name, api_key_value)` — write to `.env` and settings.yaml
- `_build_key_cache()` — iterate agent configs, resolve `api_key_env` from os.environ, build `{key_value: agent_name}` dict
- `_invalidate_if_stale()` — check file mtimes, reload if changed

Factory defaults (when no settings.yaml exists):
```yaml
agents:
  _dashboard:
    permissions: {search_main: true, search_restricted: false, ingest: false, delete: false, server_admin: true, catalog_read: true, catalog_write: true}
    chat_provider: ""  # Uses global LLM provider
  _mcp:
    permissions: {search_main: true, search_restricted: false, ingest: true, delete: false, server_admin: true, catalog_read: true, catalog_write: false}
llm:
  provider: ""
  model: ""
  ollama_model: qwen3:32b
default_permissions:
  search_main: false
  search_restricted: false
  ingest: false
  delete: false
  server_admin: false
  catalog_read: false
  catalog_write: false
```

- [ ] **Step 3: Create settings.example.yaml**

At project root, create `settings.example.yaml` with the same structure as factory defaults plus example agent entries (kendra, centaur).

- [ ] **Step 4: Write tests**

`tests/test_settings.py`:
- `test_load_creates_defaults` — no file exists, creates with factory defaults
- `test_load_reads_existing` — file exists, reads correctly
- `test_mtime_cache` — second load with no change returns cached data
- `test_create_agent` — creates agent, generates key, writes to settings
- `test_create_agent_invalid_name` — rejects invalid names
- `test_get_agent_by_key` — resolves agent from API key
- `test_get_agent_by_key_unknown` — returns None for unknown key
- `test_update_agent_permissions` — updates and persists
- `test_delete_agent` — removes from settings
- `test_get_llm_config` — returns current config

Use `tmp_path` for all file operations, mock `os.environ` for key lookups.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_settings.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/settings/ src/config.py settings.example.yaml tests/test_settings.py
git commit -m "feat: SettingsManager — agent CRUD, permissions, key cache, YAML persistence"
```

---

## Task 2: Permission Middleware + Auth Replacement

**Files:**
- Modify: `src/server.py`
- Modify: `src/api/v1_routes.py`
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Replace verify_api_key in server.py**

Remove the existing `verify_api_key()` function. Create a new `check_permissions` FastAPI dependency:

```python
from src.settings.settings_manager import SettingsManager

_settings_mgr = SettingsManager()

async def check_permissions(request: Request):
    """Resolve agent permissions from API key."""
    api_key = request.headers.get("X-API-Key", "")

    if not api_key:
        # No key — check if open mode (no agents configured)
        agents = _settings_mgr.get_agents()
        if not agents or all(a.startswith("_") for a in agents):
            # Open mode: localhost trust, full permissions
            request.state.agent_name = "_open"
            request.state.permissions = {p: True for p in DEFAULT_PERMISSIONS}
            return
        raise HTTPException(status_code=401, detail="API key required")

    agent = _settings_mgr.get_agent_by_key(api_key)
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")

    request.state.agent_name = agent["name"]
    request.state.permissions = agent["permissions"]
```

Remove all `Depends(verify_api_key)` from v1_routes.py and replace with `Depends(check_permissions)`.

Update the startup warning about missing API key to reference settings instead.

- [ ] **Step 2: Add per-endpoint permission checks to v1_routes.py**

Each endpoint checks the specific permission it needs:

```python
# On search endpoint:
if not request.state.permissions.get("search_main"):
    return JSONResponse(status_code=403, content={"error": "search_main permission required"})

# On ingest endpoint:
if not request.state.permissions.get("ingest"):
    return JSONResponse(status_code=403, content={"error": "ingest permission required"})

# For search_scope enforcement:
if search_scope in ("restricted", "all"):
    if not request.state.permissions.get("search_restricted"):
        return JSONResponse(status_code=403, content={"error": "search_restricted permission required"})
```

- [ ] **Step 3: Write tests**

`tests/test_permissions.py`:
- `test_valid_key_resolves_permissions` — known key returns agent permissions
- `test_unknown_key_rejected` — unknown key returns 401
- `test_no_key_open_mode` — no key + no agents = open mode (full access)
- `test_no_key_with_agents_rejected` — no key + agents configured = 401
- `test_permission_denied_on_search` — agent without search_main gets 403
- `test_permission_denied_on_ingest` — agent without ingest gets 403
- `test_restricted_scope_denied` — agent without search_restricted gets 403 for scope=all
- `test_settings_endpoints_reject_api_key` — API key on /api/settings/* returns 403

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_permissions.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/server.py src/api/v1_routes.py tests/test_permissions.py
git commit -m "feat: permission-based auth — replace single API key with per-agent permissions"
```

---

## Task 3: MCP Permission Enforcement

**Files:**
- Modify: `src/mcp_server/server.py`
- Modify: `src/mcp_server/tools.py`

- [ ] **Step 1: Load _mcp permissions at MCP startup**

In `src/mcp_server/server.py` `_startup()`, load permissions:

```python
from src.settings.settings_manager import SettingsManager
settings = SettingsManager()
mcp_agent = settings.get_agent("_mcp")
mcp_permissions = mcp_agent["permissions"] if mcp_agent else {p: True for p in DEFAULT_PERMISSIONS}
```

Pass `mcp_permissions` to `CoreRagTools.__init__()`.

- [ ] **Step 2: Add permission checks to CoreRagTools**

In `src/mcp_server/tools.py`, store permissions on `self._permissions`. Each tool method checks before executing:

```python
async def search_knowledge(self, ...):
    if not self._permissions.get("search_main"):
        return {"error": "search_main permission not granted"}
    if search_scope in ("restricted", "all"):
        if not self._permissions.get("search_restricted"):
            return {"error": "search_restricted permission not granted"}
    # ... existing logic ...
```

- [ ] **Step 3: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_server/server.py src/mcp_server/tools.py
git commit -m "feat: MCP permission enforcement — _mcp agent permissions loaded at startup"
```

---

## Task 4: Settings API Endpoints

**Files:**
- Create: `src/api/settings_routes.py`
- Modify: `src/server.py` (mount routes)

- [ ] **Step 1: Create settings_routes.py**

New file with `create_settings_router()` factory function. All endpoints reject requests with `X-API-Key` header (dashboard-only):

```python
def create_settings_router() -> APIRouter:
    router = APIRouter(prefix="/api/settings")

    @router.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE"])
    async def block_api_keys(request: Request, path: str):
        if request.headers.get("X-API-Key"):
            return JSONResponse(status_code=403, content={"error": "Settings are dashboard-only"})
        # Fall through to actual handlers
```

Endpoints:
- `GET /api/settings` — full settings + restart_required flag
- `GET /api/settings/agents` — list agents
- `POST /api/settings/agents` — create agent (validate name, generate key, return key once)
- `PUT /api/settings/agents/{name}` — update permissions
- `DELETE /api/settings/agents/{name}` — revoke agent
- `PUT /api/settings/llm` — update provider/model (writes .env + settings.yaml)
- `GET /api/settings/ollama-models` — fetch from localhost:11434/api/tags
- `GET /api/settings/model-status` — loaded models + restart_required
- `GET /api/settings/db-stats` — database sizes and counts
- `POST /api/settings/db-action` — optimize/backup/health-check

- [ ] **Step 2: Mount in server.py**

In the lifespan or app setup, mount the settings router:
```python
from src.api.settings_routes import create_settings_router
app.include_router(create_settings_router())
```

- [ ] **Step 3: Run tests**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/api/settings_routes.py src/server.py
git commit -m "feat: settings API endpoints — agent CRUD, LLM config, DB management"
```

---

## Task 5: Legacy Auth Migration

**Files:**
- Modify: `src/settings/settings_manager.py`

- [ ] **Step 1: Add migration logic**

In `SettingsManager.load()`, after creating factory defaults, check for legacy `CORERAG_API_KEY`:

```python
legacy_key = os.getenv("CORERAG_API_KEY")
if legacy_key and "_legacy" not in self._settings.get("agents", {}):
    self._settings["agents"]["_legacy"] = {
        "api_key_env": "CORERAG_API_KEY",
        "permissions": {p: True for p in DEFAULT_PERMISSIONS},  # Full access for backward compat
    }
    self.save()
```

This ensures existing single-key users aren't broken.

- [ ] **Step 2: Add test**

```python
def test_legacy_migration(self):
    """Existing CORERAG_API_KEY creates _legacy agent with full permissions."""
```

- [ ] **Step 3: Run tests + commit**

```bash
git add src/settings/settings_manager.py tests/test_settings.py
git commit -m "feat: legacy API key migration — creates _legacy agent with full permissions"
```

---

## Task 6: Settings Tab — Agent Management UI

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Add Settings tab to tab bar**

Add "Settings" tab button next to Ingestion and Archive. Add `<div id="settings-view" class="hidden">` with four sections.

- [ ] **Step 2: Build Agent Management section**

Agent table with safe DOM rendering. "Add Agent" button with name input + create flow. Per-agent expandable permission toggle grid. Revoke button with confirmation. Setup instructions shown after key generation.

- [ ] **Step 3: Build LLM Configuration section**

Provider dropdown, API key input (writes to .env via PUT /api/settings/llm), Ollama model list (fetched from API), "Restart Required" banner.

- [ ] **Step 4: Build Model Status section**

Read-only table showing loaded models with status indicators.

- [ ] **Step 5: Build Database Management section**

Stats table for main/restricted/catalog DBs. Action buttons (optimize, backup, health check).

- [ ] **Step 6: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: Settings tab — agent management, LLM config, model status, DB management"
```

---

## Task 7: Deprecate access_control.py

**Files:**
- Modify: `src/auth/access_control.py`
- Modify: `src/server.py`

- [ ] **Step 1: Remove access_control.py imports from server.py**

Remove `_get_access_control()` function and any imports of `AccessControl` from server.py. The new `check_permissions` dependency replaces it entirely.

- [ ] **Step 2: Add deprecation notice to access_control.py**

Add a module-level docstring:
```python
"""DEPRECATED: Replaced by src.settings.settings_manager.SettingsManager in P8 SP5.
This module is no longer imported by active code paths. Retained for reference only.
"""
```

- [ ] **Step 3: Run full test suite**

Run: `pytest --no-cov --tb=short -q 2>&1 | tail -5`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/auth/access_control.py src/server.py
git commit -m "chore: deprecate access_control.py — replaced by SettingsManager"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --no-cov --tb=short -q`
Expected: 671+ pass, no regressions.

- [ ] **Manual verification**

1. Start server, open dashboard Settings tab
2. Verify _dashboard and _mcp agents shown with permission toggles
3. Add a new agent "test-agent" — verify key generated and shown
4. Toggle permissions — verify changes persist after page refresh
5. Copy test-agent key, use curl with it — verify permissions enforced
6. Try curl with unknown key — verify 401
7. Try curl with no key (agents configured) — verify 401
8. Switch LLM provider — verify "Restart Required" shown
9. Check model status — verify loaded models displayed
10. Check DB stats — verify counts shown
11. Try accessing /api/settings with an API key — verify 403

---

## Summary

| Task | What | Files | Effort |
|------|------|-------|--------|
| 1 | SettingsManager module | settings_manager.py, config.py, tests | ~250 lines |
| 2 | Permission middleware + auth replacement | server.py, v1_routes.py, tests | ~100 lines |
| 3 | MCP permission enforcement | mcp_server/*.py | ~30 lines |
| 4 | Settings API endpoints | settings_routes.py, server.py | ~200 lines |
| 5 | Legacy auth migration | settings_manager.py | ~20 lines |
| 6 | Settings tab UI | dashboard.html | ~400 lines |
| 7 | Deprecate access_control.py | access_control.py, server.py | ~10 lines |

**Total: 7 tasks, ~1,010 lines. Task 1 (SettingsManager) and Task 6 (UI) are the largest.**
