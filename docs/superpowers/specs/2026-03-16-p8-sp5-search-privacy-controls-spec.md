# P8 Sub-project 5: Search Fan-out + Privacy Controls — Full Spec

**Date:** 2026-03-16
**Author:** Claude Opus 4.6 (Session 32)
**Status:** Approved (all sections reviewed by TJ)
**North Star:** Per-agent access control with least-privilege defaults, managed entirely from the dashboard UI.

---

## 1. Permission-Based Access Control

### Per-Action Permissions (replaces RBAC roles)

Instead of rigid VIEWER/EDITOR/ADMIN roles, each agent gets granular per-action permissions. All default to `false` (least privilege). TJ toggles each on/off per agent from the Settings UI.

**Permission actions:**

| Permission | Description | Default |
|-----------|-------------|---------|
| `search_main` | Search the main RAG database | `false` |
| `search_restricted` | Search the restricted RAG database (unredacted PII) | `false` |
| `ingest` | Add documents via API | `false` |
| `delete` | Delete documents from catalog/RAG | `false` |
| `server_admin` | Restart server, optimize DB, run health checks | `false` |
| `catalog_read` | Browse catalog and archive manager | `false` |
| `catalog_write` | Modify catalog entries, cold storage migration | `false` |

### Agent Registration

Agents identify themselves by API key. Each agent has a unique key and a permission set.

**Special agents:**
- `_dashboard` — the built-in dashboard UI. Cannot be revoked. Permissions managed like any other agent but accessed via browser session (no API key). Has its own `chat_provider` setting that determines which LLM powers the dashboard chat.
- `_mcp` — MCP stdio connections (Claude Desktop, local agents). Defaults to all permissions on (trusted local access).

### Enforcement

- Every API endpoint checks the caller's permissions before executing
- Dashboard Settings endpoints (`/api/settings/*`) are dashboard-only — any request with an API key is rejected. **Agents cannot modify their own or any other agent's permissions.**
- Unknown API keys are rejected (not defaulted to any permission set)
- MCP access defaults to `_mcp` agent permissions

### Provider-Independent Security

CoreRag cannot know what LLM powers an external agent. The `search_restricted` permission is a trust decision made by the user, not an automated check. The UI shows a warning when enabling restricted access: "This agent will receive unredacted PII. Ensure it uses a local-only LLM."

For the dashboard's built-in chat, the `chat_provider` setting IS known — so the UI can show a specific warning if `search_restricted` is enabled while `chat_provider` is a cloud model.

---

## 2. Settings Persistence

### File split:
- **`~/.corerag/.env`** — API keys only (secrets). Written by Settings UI for new agent keys.
- **`~/.corerag/settings.yaml`** — everything else (agent config, permissions, provider selection, UI preferences). Read/written by Settings UI.

### settings.yaml structure:

```yaml
agents:
  _dashboard:
    permissions:
      search_main: true
      search_restricted: false
      ingest: false
      delete: false
      server_admin: true
      catalog_read: true
      catalog_write: true
    chat_provider: claude-cli  # What LLM powers the dashboard chat

  _mcp:
    permissions:
      search_main: true
      search_restricted: false
      ingest: true
      delete: false
      server_admin: true
      catalog_read: true
      catalog_write: false

  kendra:
    api_key_env: CORERAG_AGENT_KENDRA_KEY
    permissions:
      search_main: true
      search_restricted: false
      ingest: true
      delete: false
      server_admin: false
      catalog_read: true
      catalog_write: false

  centaur:
    api_key_env: CORERAG_AGENT_CENTAUR_KEY
    permissions:
      search_main: true
      search_restricted: false
      ingest: false
      delete: false
      server_admin: false
      catalog_read: true
      catalog_write: false

llm:
  provider: claude-cli
  model: ""  # Provider default if empty
  ollama_model: qwen3:32b

default_permissions:  # Applied to unknown/new agents as template
  search_main: false
  search_restricted: false
  ingest: false
  delete: false
  server_admin: false
  catalog_read: false
  catalog_write: false
```

### Override order:
1. `.env` values loaded first (via python-dotenv)
2. `settings.yaml` overlays for non-secret configuration
3. Settings UI reads/writes `settings.yaml` (and `.env` for API keys only)

### Settings reload:
- Agent permissions: reloaded on each request (lazy read from `settings.yaml`, cached with mtime check)
- LLM provider/model changes: require server restart (singleton pattern)
- New API keys: available immediately (added to `.env`, read on next auth check)

---

## 3. Settings Tab UI

### Access
New "Settings" tab in the dashboard (alongside Ingestion, Archive). Four sections:

### 3a. Agent Management

**Agent table:** Name | API Key (masked) | Permissions Summary | Last Seen | Actions

**Add Agent flow:**
1. Click "Add Agent" → form: agent name (required)
2. Click "Create" → backend generates unique API key, saves to `.env` as `CORERAG_AGENT_{NAME}_KEY`, adds entry to `settings.yaml` with all permissions `false`
3. UI updates immediately — new agent appears with full key visible + "Copy Key" button
4. Warning: "Save this key — it won't be shown again"
5. Agent row auto-expands to show permission toggles
6. No restart required — key loaded on next request

**Permission toggle grid (per agent):**
```
Agent: kendra
  [ON ] Search Main RAG          [OFF] Search Restricted RAG ⚠️
  [ON ] Ingest Documents          [OFF] Delete Documents
  [OFF] Server Admin              [ON ] Catalog Read
  [OFF] Catalog Write
```

The ⚠️ warning appears next to `Search Restricted RAG` toggle with tooltip: "This agent will receive unredacted PII. Ensure it uses a local-only LLM."

**Dashboard chat provider** shown on the `_dashboard` agent entry:
- Dropdown: ollama, claude-cli, gemini-cli, etc.
- Warning if `search_restricted` is ON while chat_provider is cloud
- Changes require restart

**Setup instructions:** After key generation, the UI shows agent-specific setup guidance:
- "Add this key to the agent's environment: `CORERAG_API_KEY=<key>`"
- "The agent must include this key in the `X-API-Key` HTTP header with every request to CoreRag."
- For MCP agents (Claude Desktop): "MCP connections use stdio transport — no API key needed. Access is controlled via the `_mcp` agent permissions."

**Revoke:** Click "Revoke" → confirmation → removes agent from `settings.yaml`, removes key from `.env`. The agent's next request will be rejected.

### 3b. LLM Configuration

- **Current provider:** display name + status (connected/error)
- **Provider selector:** dropdown (ollama, claude-cli, gemini-cli, gemini, anthropic, codex-cli)
- **API key entry:** text input, writes to `.env`, displayed masked after save
- **Ollama models:** list fetched from `localhost:11434/api/tags` (if Ollama is running)
- **Selected model:** dropdown for Ollama model selection
- **"Restart Required"** banner when provider/model changed but not yet applied

### 3c. Model Status (read-only)

| Model | Type | Status |
|-------|------|--------|
| BAAI/bge-m3 | Embedding (1024d) | Loaded |
| cross-encoder/ms-marco-MiniLM-L-6-v2 | Reranker | Loaded |
| en_core_web_lg | NER (spaCy) | Loaded |
| qwen3:32b | LLM (Ollama) | Connected |

Status indicators: green dot (loaded), yellow (loading), red (error/offline)

### 3d. Database Management

| Database | Chunks | Size | Actions |
|----------|--------|------|---------|
| Main RAG | 7,329 | ~45 MB | [Optimize] [Backup] |
| Restricted RAG | 0 | 0 | [Optimize] [Backup] |
| Catalog | 102 docs | ~94 KB | [Health Check] |

Actions call existing endpoints/CLI commands. Results shown inline.

---

## 4. Backend Endpoints

### Settings API (dashboard-only, no API key access)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/settings` | GET | Full settings (agents, llm config, model status, db stats) |
| `GET /api/settings/agents` | GET | List all agents with permissions |
| `POST /api/settings/agents` | POST | Create new agent (generates key) |
| `PUT /api/settings/agents/{name}` | PUT | Update agent permissions |
| `DELETE /api/settings/agents/{name}` | DELETE | Revoke agent |
| `PUT /api/settings/llm` | PUT | Update LLM provider/model (writes to .env/settings.yaml) |
| `GET /api/settings/ollama-models` | GET | Fetch available Ollama models |
| `GET /api/settings/model-status` | GET | Current model load status |
| `GET /api/settings/db-stats` | GET | Database sizes and counts |
| `POST /api/settings/db-action` | POST | Optimize/backup/health-check |

**Security:** These endpoints reject any request that includes an `X-API-Key` header. They are only accessible from the dashboard browser session.

### Permission Middleware

New middleware in `server.py` that runs on every `/api/v1/*` request:
1. Extract API key from `X-API-Key` header
2. Look up agent in `settings.yaml` by matching key
3. Store permissions on `request.state.permissions`
4. Each endpoint checks `request.state.permissions[action]` before executing

---

## 5. Settings Manager Module

New module: `src/settings/settings_manager.py`

**SettingsManager class:**
- `load()` — read `settings.yaml`, cache with mtime check
- `get_agent(name)` — returns agent config with permissions
- `get_agent_by_key(api_key)` — lookup agent by API key (checks .env values)
- `create_agent(name)` — generate key, add to .env + settings.yaml
- `update_agent(name, permissions)` — update permissions in settings.yaml
- `delete_agent(name)` — remove from settings.yaml + .env
- `get_llm_config()` — current provider/model settings
- `update_llm_config(provider, model, api_key)` — write to .env/settings.yaml
- `get_ollama_models()` — fetch from Ollama API

---

## 6. File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/settings/__init__.py` | Create | Package init |
| `src/settings/settings_manager.py` | Create | SettingsManager class — YAML read/write, agent CRUD, .env management |
| `src/server.py` | Modify | Permission middleware, settings endpoint mounting |
| `src/api/settings_routes.py` | Create | Settings API endpoints (dashboard-only) |
| `src/api/v1_routes.py` | Modify | Permission checks on all endpoints |
| `src/mcp_server/server.py` | Modify | Load permissions for MCP tools |
| `src/mcp_server/tools.py` | Modify | Permission checks on tool execution |
| `src/ui/templates/dashboard.html` | Modify | Settings tab UI (agents, LLM, models, DB management) |
| `tests/test_settings.py` | Create | Tests for SettingsManager |
| `tests/test_permissions.py` | Create | Tests for permission enforcement |
| `settings.example.yaml` | Create | Example settings file (committed, gitignored real one) |

---

## 7. Success Criteria

1. Each agent has a unique API key and per-action permission toggles
2. All permissions default to `false` (least privilege)
3. Settings UI shows all agents with toggle grid — changes take effect immediately
4. "Add Agent" generates key, shows once, updates UI
5. "Revoke" removes agent access completely
6. Agents cannot access `/api/settings/*` endpoints
7. `search_restricted` permission controls access to restricted RAG
8. Warning displayed when restricted access enabled for cloud-provider agent
9. Dashboard chat provider configurable, with restricted access gated on local model
10. LLM provider/model changeable from UI (restart required)
11. Ollama model list populated from live API
12. Database stats and management actions work from UI
13. Existing tests pass unchanged
14. Unknown API keys are rejected (not defaulted)

---

## 8. Migration from Current Auth

Currently: single `CORERAG_API_KEY` in `.env`. The migration:

1. If `CORERAG_API_KEY` exists and no `settings.yaml` exists, create a `_legacy` agent with that key and all permissions enabled (backward compatible)
2. Going forward, new agents are created via the Settings UI
3. The old `CORERAG_API_KEY` continues to work as the `_legacy` agent until explicitly revoked

---

## 9. Future: Keychain Storage (SP6)

When CoreRag becomes a native app (SP6), API keys can be stored in macOS Keychain instead of `.env`. The `SettingsManager` would use `security` CLI or PyObjC `SecItemAdd` for key storage. The UI interface stays the same — only the storage backend changes.
