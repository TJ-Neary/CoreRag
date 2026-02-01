# Project Security Guide

Comprehensive security reference for all projects. Covers secrets management, personal data protection, dependency security, secure coding, infrastructure, and incident response.

---

## Table of Contents

1. [Core Principles](#core-principles)
2. [Secrets & Credentials](#secrets--credentials)
3. [API Keys & Tokens](#api-keys--tokens)
4. [Personal Data Protection](#personal-data-protection)
5. [Secure Coding Practices](#secure-coding-practices)
6. [Dependency Security](#dependency-security)
7. [Database & Storage Security](#database--storage-security)
8. [Network & Infrastructure](#network--infrastructure)
9. [Authentication & Authorization](#authentication--authorization)
10. [File Rules by Type](#file-rules-by-type)
11. [Gitignore Checklist](#gitignore-checklist)
12. [Template File Convention](#template-file-convention)
13. [Pre-Commit Checklist](#pre-commit-checklist)
14. [Incident Response](#incident-response)
15. [AI Session Security](#ai-session-security)

---

## Core Principles

1. **Never commit secrets to git.** No API keys, passwords, tokens, certificates, or credentials — ever.
2. **Never commit personal data to git.** No names, emails, usernames, file paths, employer names, or document content.
3. **Least privilege.** Every component gets the minimum access it needs and nothing more.
4. **Defense in depth.** Don't rely on a single layer. Combine gitignore + env vars + runtime validation + access controls.
5. **Fail secure.** When something goes wrong, deny access rather than grant it. Default to restrictive.
6. **Local-first.** Keep sensitive data on-device. Only send to external services when explicitly required and consented to.

---

## Secrets & Credentials

### What Counts as a Secret

| Type | Examples | Common File Locations |
|------|----------|-----------------------|
| API keys | `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID` | .env, config.py, settings.json |
| Passwords | Database passwords, service account passwords | .env, docker-compose.yml, config files |
| Tokens | OAuth tokens, JWT signing keys, refresh tokens | .env, auth configs, cookie stores |
| Certificates | TLS/SSL certs, private keys, signing certs | *.pem, *.key, *.crt, *.p12 |
| Connection strings | Database URLs with embedded credentials | .env, config files, docker-compose.yml |
| Webhook URLs | Slack webhooks, Discord webhooks, CI/CD triggers | .env, config files, scripts |
| Encryption keys | AES keys, Fernet keys, master keys | .env, keyfiles, config |
| Service accounts | GCP service account JSON, AWS credentials files | credentials.json, *.json |

### How to Handle Secrets

**Do:**
- Store in environment variables loaded from `.env` (gitignored)
- Use a secrets manager for production (AWS Secrets Manager, HashiCorp Vault, 1Password CLI)
- Use `.example` files with placeholder values committed to the repo
- Load secrets at runtime, never at import time
- Rotate secrets on a schedule and after any suspected leak

**Don't:**
- Hardcode secrets anywhere in source code
- Pass secrets as command-line arguments (visible in process lists)
- Log secrets — even at DEBUG level
- Store secrets in comments, TODOs, or documentation
- Copy secrets between projects — generate new ones per project
- Commit secrets "temporarily" with plans to remove later

### Environment Variable Pattern

```bash
# .env (GITIGNORED — never committed)
DATABASE_URL=postgresql://user:password@localhost:5432/mydb
OPENAI_API_KEY=sk-proj-abc123...
WEBHOOK_SECRET=whsec_xyz789...

# .env.example (COMMITTED — safe template)
DATABASE_URL=postgresql://user:password@localhost:5432/mydb
OPENAI_API_KEY=sk-proj-your-key-here
WEBHOOK_SECRET=whsec_your-secret-here
```

```python
# config.py — load from environment, never hardcode
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("OPENAI_API_KEY")

# Validate at startup — fail fast if missing
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set. Copy .env.example to .env and configure.")
```

---

## API Keys & Tokens

### Key Management Rules

1. **One key per service per environment.** Don't reuse keys between dev/staging/prod.
2. **Scope keys minimally.** If the API supports scoped permissions, use the narrowest scope possible.
3. **Set expiry dates.** Use short-lived tokens where possible. Rotate long-lived keys quarterly.
4. **Monitor usage.** Set up billing alerts and usage caps on paid APIs.
5. **Revoke immediately** if a key is committed to git, logged, or exposed in any way.

### If a Key Is Leaked

1. **Revoke the key immediately** from the service provider's dashboard
2. Generate a new key
3. Update `.env` (and any deployed environments)
4. If committed to git: remove from history with `git filter-repo`
5. Check service logs for unauthorized usage during the exposure window
6. Enable billing alerts if not already set

### Common API Key Patterns to Gitignore

```gitignore
# API keys and tokens
.env
.env.*
!.env.example
*.key
*.pem
*.crt
*.p12
*.pfx
credentials.json
service-account*.json
token.json
.secrets/
```

### Runtime Validation

```python
def validate_api_key(key: str, service_name: str) -> None:
    """Validate API key format before making requests."""
    if not key:
        raise ValueError(f"{service_name} API key not configured")
    if key.startswith("sk-proj-your") or key == "your-key-here":
        raise ValueError(f"{service_name} API key is still a placeholder")
    if len(key) < 20:
        raise ValueError(f"{service_name} API key looks malformed")
```

---

## Personal Data Protection

### What Counts as Personal Data

| Category | Examples | Where It Hides |
|----------|----------|----------------|
| Identity | Name, email, username, pronouns | pyproject.toml, README, config files |
| File paths | `/Users/yourname/...`, `~/Desktop/...` | Scripts, config, examples in docs |
| Org structure | Employer names, folder categories | Sorting rules, classification configs |
| Document content | Text from ingested files, summaries | Staging manifests, logs, test fixtures |
| Hardware/env | Machine specs, IP addresses, MAC addresses | Architecture docs, config files, logs |
| Location | Timezone, address, GPS coordinates | Config files, metadata |
| Session logs | Processing history, batch results, queries | Progress logs, debug output, analytics |
| Financial | Account numbers, transaction IDs, salary info | Config, logs, test data |
| Medical | Health records, prescriptions, insurance IDs | Document content, metadata |

### Rules

- Never commit real personal data — use synthetic/placeholder data
- Use role labels instead of names: "(Owner)", "(Admin)", "User"
- Use generic paths in examples: `$HOME/...`, `/path/to/project/`, `/Users/yourname/`
- Keep session-specific logs in gitignored directories
- If a document must contain personal context, gitignore it

---

## Secure Coding Practices

### Input Validation

Always validate and sanitize at system boundaries (user input, API requests, file uploads).

```python
# Validate input types and ranges
def search(query: str, k: int = 5) -> list:
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")
    if not 1 <= k <= 100:
        raise ValueError("k must be between 1 and 100")
    query = query.strip()[:1000]  # Enforce max length
    # ... proceed with validated input
```

### Injection Prevention

| Attack | Prevention |
|--------|------------|
| SQL injection | Use parameterized queries, never string concatenation |
| Command injection | Use `subprocess.run(["cmd", arg])` with list args, never `shell=True` with user input |
| Path traversal | Validate paths with `os.path.realpath()`, reject `..` components |
| XSS | Escape HTML output, use template engines with auto-escaping |
| SSRF | Validate URLs against an allowlist, reject internal IPs |

```python
# SQL — parameterized queries
cursor.execute("SELECT * FROM docs WHERE id = ?", (doc_id,))  # Safe
cursor.execute(f"SELECT * FROM docs WHERE id = '{doc_id}'")   # VULNERABLE

# Commands — list args, no shell
subprocess.run(["ffmpeg", "-i", input_path, output_path])       # Safe
subprocess.run(f"ffmpeg -i {input_path} {output_path}", shell=True)  # VULNERABLE

# Paths — validate and resolve
def safe_path(base_dir: str, user_path: str) -> str:
    resolved = os.path.realpath(os.path.join(base_dir, user_path))
    if not resolved.startswith(os.path.realpath(base_dir)):
        raise ValueError("Path traversal detected")
    return resolved
```

### Error Handling

- Never expose stack traces, internal paths, or system info in API responses
- Log full errors server-side, return generic messages to clients
- Don't include secrets or PII in error messages or logs

```python
# API error response — generic for clients
@app.exception_handler(Exception)
async def handle_error(request, exc):
    logger.error(f"Internal error: {exc}", exc_info=True)  # Full detail in logs
    return JSONResponse(status_code=500, content={"error": "Internal server error"})  # Generic to client
```

### Logging

- Never log secrets, passwords, tokens, or API keys
- Never log full request/response bodies that may contain PII
- Sanitize user input before logging
- Use structured logging with levels (DEBUG for dev only, INFO+ for production)

```python
# Safe logging
logger.info("Search request", extra={"query_length": len(query), "k": k})

# Dangerous logging — don't do this
logger.debug(f"API key: {api_key}")
logger.info(f"User submitted: {raw_user_input}")
logger.debug(f"Full request body: {request.body()}")
```

---

## Dependency Security

### Rules

1. **Pin versions** in `requirements.txt` or `pyproject.toml` for reproducible builds
2. **Audit regularly** with `pip audit`, `npm audit`, or `safety check`
3. **Update promptly** when security advisories are published
4. **Minimize dependencies** — fewer deps = smaller attack surface
5. **Verify sources** — only install from official registries (PyPI, npm)
6. **Review new deps** before adding — check maintenance status, download counts, known vulnerabilities

### Audit Commands

```bash
# Python
pip audit                          # Check for known vulnerabilities
pip list --outdated                # See what needs updating
safety check                       # Alternative vulnerability scanner

# Node.js
npm audit                          # Check for known vulnerabilities
npm audit fix                      # Auto-fix where possible

# General
dependabot / renovate              # Automated PR-based updates (GitHub)
```

### Lock Files

Always commit lock files for reproducibility:
- Python: `requirements.txt` with pinned versions (or `poetry.lock`, `Pipfile.lock`)
- Node.js: `package-lock.json` or `yarn.lock`
- Rust: `Cargo.lock`
- Go: `go.sum`

---

## Database & Storage Security

### Local Databases (SQLite, LanceDB)

- Store database files outside the project directory (e.g., `~/.appname/`)
- Gitignore all database files (`*.db`, `*.sqlite`, `*.lance`, `*.lancedb/`)
- Set restrictive file permissions: `chmod 600` for database files
- Back up regularly with checksums to detect corruption

### Connection Strings

- Always use environment variables for connection strings
- Never embed credentials in URLs committed to git
- Use SSL/TLS for remote database connections

```bash
# .env (gitignored)
DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require

# NOT in code
db = connect("postgresql://user:pass@host:5432/db")  # NEVER do this
```

### Data at Rest

- Encrypt sensitive local data where possible (macOS: FileVault covers disk-level)
- Use content hashing (SHA-256) to verify data integrity
- Implement access controls even for single-user systems (defense in depth)

---

## Network & Infrastructure

### Localhost Binding

For local development servers and APIs:

```python
# Bind to localhost only — not accessible from network
app.run(host="127.0.0.1", port=8000)  # Safe

# NEVER do this for dev servers with no auth
app.run(host="0.0.0.0", port=8000)    # Exposes to entire network
```

### HTTPS/TLS

- Always use HTTPS for external API calls
- Verify SSL certificates (never set `verify=False` in production)
- Use TLS 1.2+ only

```python
# Safe
requests.get("https://api.example.com", timeout=30)

# DANGEROUS in production
requests.get("https://api.example.com", verify=False)  # Disables cert verification
```

### CORS (Cross-Origin Resource Sharing)

- Restrict CORS origins to known domains
- Never use `allow_origins=["*"]` with credentials or sensitive endpoints

### Rate Limiting

- Apply rate limits to all public-facing endpoints
- Use exponential backoff for outgoing API calls
- Set timeouts on all network requests

---

## Authentication & Authorization

### Local-First Applications

Even for single-user local applications:
- Bind servers to `127.0.0.1` only
- Validate that requests come from localhost
- Don't expose admin/destructive endpoints without confirmation

### API Authentication (When Needed)

For APIs that will be accessed by other systems:

```python
# Simple bearer token auth for local services
API_TOKEN = os.getenv("PKM_API_TOKEN")

async def verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
```

### Password Storage

- Never store plaintext passwords
- Use bcrypt, argon2, or scrypt for hashing
- Use unique salts per password (most libraries handle this automatically)

```python
# Python — bcrypt
import bcrypt
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
bcrypt.checkpw(password.encode(), hashed)
```

---

## File Rules by Type

### Scripts (.sh, .py)
- Use `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"` for path resolution
- Use environment variables (`$HOME`, `$INBOX_PATH`) instead of hardcoded paths
- Never embed usernames, absolute paths, or credentials

### Configuration (.yaml, .json, .toml, .env)
- Commit only `.example` templates with placeholder values
- Gitignore the actual config file
- Use generic placeholders: `/Users/yourname/`, `your@email.com`, `your-key-here`

### Documentation (.md)
- Use generic paths in examples: `$HOME/...` or `/path/to/project/`
- Don't include real names in ownership/author lines
- Keep session-specific logs in gitignored directories
- Don't include real API keys in curl examples (use `$API_KEY` or `your-key-here`)

### Test Files (.py)
- Use synthetic/fake data only (e.g., `john.doe@example.com`, `123-45-6789`)
- Never copy real document content into test fixtures
- Use `tempfile.TemporaryDirectory()` for test outputs
- Never use real API keys in tests — mock external services

### Architecture Docs (.md)
- Use role labels instead of names: "(Owner)", "(Admin)", "User"
- Use shortened generic paths in diagrams: `/Users/user/...`
- If a doc must contain personal context, gitignore it

### Docker / CI Files
- Never embed secrets in Dockerfiles or CI configs
- Use build args or mounted secrets for Docker
- Use CI platform secret stores (GitHub Secrets, GitLab CI Variables)

---

## Gitignore Checklist

Every project should gitignore these categories. Copy and adapt for your project:

```gitignore
# =============================================================
# Secrets & Credentials
# =============================================================
.env
.env.*
!.env.example
*.pem
*.key
*.crt
*.p12
*.pfx
secrets.json
credentials.json
service-account*.json
token.json
.secrets/

# =============================================================
# User-Specific Config (commit .example versions instead)
# =============================================================
# Add your project-specific config files here:
# sorting_rules.yaml
# pii_terms.yaml
# local_settings.py

# =============================================================
# Database & Runtime Data
# =============================================================
*.db
*.sqlite
*.sqlite3
*.lancedb/
*.lance/
*.log
logs/
staging_manifest.json

# =============================================================
# Personal Notes & Session Logs
# =============================================================
_project/progress.md
_project/project_memory.md
_project/findings.md

# =============================================================
# Python
# =============================================================
__pycache__/
*.py[cod]
*.so
*.egg-info/
dist/
build/
.venv/
venv/

# =============================================================
# Testing & Coverage
# =============================================================
.pytest_cache/
.coverage
.coverage.*
htmlcov/
temp_test_*/

# =============================================================
# IDE & OS
# =============================================================
.idea/
.vscode/
.claude/
.DS_Store
*.swp
*~

# =============================================================
# Node.js (if applicable)
# =============================================================
node_modules/
.env.local
.next/
```

---

## Template File Convention

For any file that contains user-specific data or secrets:

1. Create the real file locally (gitignored): `config.yaml`
2. Create a committed template: `config.example.yaml`
3. Add a comment at the top: `# Copy to config.yaml and customize`
4. Document the setup step in README

**Naming convention:** `<filename>.example.<ext>`
- `.env` → `.env.example`
- `config.yaml` → `config.example.yaml`
- `credentials.json` → `credentials.example.json`

---

## Pre-Commit Checklist

Before every commit, verify:

**Secrets:**
- [ ] No API keys, tokens, passwords, or connection strings in code or config
- [ ] No `.env` file staged (check with `git status`)
- [ ] No certificates or private keys staged
- [ ] Secrets loaded from environment variables, not hardcoded

**Personal Data:**
- [ ] No real names, emails, or usernames in changed files
- [ ] No hardcoded `/Users/yourname/` paths
- [ ] No document content from databases or user files
- [ ] No employer names, medical/financial/legal references
- [ ] Config files use `.example` pattern

**Code Quality:**
- [ ] No `verify=False` on HTTPS requests
- [ ] No `shell=True` with user-controlled input
- [ ] No raw SQL string concatenation
- [ ] No sensitive data in log statements
- [ ] Error responses don't expose internal details

**Quick scan commands:**
```bash
# Check staged changes for secrets and personal data
git diff --cached | grep -iE "(api_key|secret|password|token|bearer|sk-|/Users/[a-z])"

# Check for common secret patterns
git diff --cached | grep -iE "(['\"]sk-|['\"]ghp_|['\"]AKIA|['\"]xox[bsp]-)"

# Replace with your actual identifiers to catch personal data leaks
git diff --cached | grep -iE "(yourname|your@email)"
```

---

## Incident Response

### If a Secret Was Committed

1. **Revoke immediately** — rotate the key/password at the source
2. **Remove from git tracking**: `git rm --cached <file>` + add to `.gitignore`
3. **Purge from history** (if repo is shared/public):
   ```bash
   # Install git-filter-repo (pip install git-filter-repo)
   git filter-repo --path <file> --invert-paths
   ```
4. **Force push** (coordinate with team): `git push --force-with-lease`
5. **Audit** — check service logs for unauthorized usage during exposure window
6. **Post-mortem** — identify how it happened and add safeguards

### If Personal Data Was Committed

1. Add the file to `.gitignore`
2. Remove from tracking: `git rm --cached <file>`
3. Commit the removal
4. If the repo is public, purge history with `git filter-repo`
5. If data was exposed publicly, assess notification obligations (GDPR, etc.)

### Prevention Tools

- **pre-commit hooks**: Use `detect-secrets` or `gitleaks` to scan before each commit
- **CI scanning**: Add secret scanning to CI pipeline (GitHub has built-in secret scanning)
- **git-secrets**: AWS tool that prevents committing AWS credentials

```bash
# Install detect-secrets (Python)
pip install detect-secrets
detect-secrets scan > .secrets.baseline
detect-secrets audit .secrets.baseline

# Install gitleaks
brew install gitleaks
gitleaks detect --source .
```

---

## AI Session Security

When working with AI assistants (Claude Code, Copilot, ChatGPT, etc.):

- **Session logs** often contain personal context (name, projects, preferences) — keep them gitignored
- **AI-generated code** may include placeholder secrets that look real — verify before committing
- **AI-generated docs** may include your name or details from conversation — review before committing
- **Architecture docs** created during AI sessions may reference personal use cases — sanitize or gitignore
- **Don't paste secrets** into AI conversations — use placeholder values when asking for help
- **Review AI output** for hardcoded paths, names, or config values pulled from conversation context

---

*Reusable across projects. Copy this file to any new repo as a starting point.*
