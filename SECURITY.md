# Security & Data Sanitization Guide

Rules for keeping personal data out of version control. Use this as a reference for this project and any new project.

---

## Core Rule

**Never commit personal data to git.** This includes names, emails, usernames, file paths, employer names, medical/financial/legal references, and any content from ingested documents.

---

## What Counts as Personal Data

| Category | Examples | Where It Hides |
|----------|----------|----------------|
| Identity | Name, email, username, pronouns | pyproject.toml, README, config files |
| File paths | `/Users/yourname/...`, `~/Desktop/...` | Scripts, config, examples in docs |
| Org structure | Employer names, folder categories | Sorting rules, classification configs |
| Document content | Text from ingested files, summaries | Staging manifests, logs, test fixtures |
| Hardware/env | Machine specs, IP addresses | Architecture docs, config files |
| Credentials | API keys, tokens, passwords | .env files, config files |
| Session logs | Processing history, batch results | Progress logs, debug output |

---

## Rules for New Files

### Scripts (.sh, .py)
- Use `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"` for path resolution
- Use environment variables (`$HOME`, `$INBOX_PATH`) instead of hardcoded paths
- Never embed usernames or absolute paths

### Configuration (.yaml, .json, .toml, .env)
- Commit only `.example` templates with placeholder values
- Gitignore the actual config file (e.g., `sorting_rules.yaml`)
- Use generic placeholders: `/Users/yourname/`, `your@email.com`, `Employer1`

### Documentation (.md)
- Use generic paths in examples: `$HOME/...` or `/path/to/project/`
- Don't include real names in ownership/author lines
- Keep session-specific logs (progress, findings) in gitignored directories

### Test Files (.py)
- Use synthetic/fake data only (e.g., `john.doe@example.com`, `123-45-6789`)
- Never copy real document content into test fixtures
- Use `tempfile.TemporaryDirectory()` for test outputs

### Architecture Docs (.md)
- Use role labels instead of names: "(Owner)", "(Admin)", "User"
- Use shortened generic paths in diagrams: `/Users/user/...`
- If a doc must contain personal context (like a "personal context" design), gitignore it

---

## Gitignore Checklist

Every project should gitignore these categories. Copy this block into `.gitignore`:

```gitignore
# Environment & Secrets
.env
.env.local
.env.*.local
*.pem
*.key
secrets.json
credentials.json

# User-specific config (commit .example versions instead)
sorting_rules.yaml
sorting_rules.yml
pii_terms.yaml
pii_terms.yml

# Runtime data
*.log
logs/
staging_manifest.json
*.lancedb/
*.lance/
*.sqlite
*.db

# Personal project notes
_project/progress.md
_project/project_memory.md
_project/findings.md

# Test artifacts
temp_test_*/
.coverage
.coverage.*
htmlcov/
.pytest_cache/
```

---

## Template File Convention

For any file that contains user-specific data:

1. Create the real file locally (gitignored): `config.yaml`
2. Create a committed template: `config.example.yaml`
3. Add a comment at the top of the template: `# Copy to config.yaml and customize`
4. Document the setup in README or CLAUDE.md

Current template files in this project:
- `.env.example` → `.env`
- `sorting_rules.example.yaml` → `sorting_rules.yaml`
- `pii_terms.example.yaml` → `pii_terms.yaml` (at `~/.pkm/`)
- `scripts/com.user.pkm.example.plist` → `scripts/com.user.pkm.plist`

---

## Pre-Commit Checklist

Before committing, verify:

- [ ] No real names, emails, or usernames in changed files
- [ ] No hardcoded `/Users/yourname/` paths (use dynamic resolution or env vars)
- [ ] No document content from the RAG database or ingestion pipeline
- [ ] No employer names, medical/financial/legal folder names
- [ ] Config files use `.example` pattern (real file gitignored)
- [ ] Test fixtures use only synthetic data
- [ ] `git diff --cached` doesn't show any personal identifiers

Quick check command:
```bash
git diff --cached | grep -iE "(yourname|your@email|/Users/[a-z])"
```
Replace `yourname` and `your@email` with your actual values to catch leaks.

---

## If Personal Data Was Already Committed

1. Add the file to `.gitignore`
2. Remove from tracking: `git rm --cached <file>`
3. Commit the removal
4. If the repo is public or shared, consider `git filter-repo` to purge history

---

## AI Session Notes

When working with AI assistants (Claude Code, Copilot, etc.):
- Session logs and progress files often contain personal context — keep them gitignored
- AI-generated docs may include your name or details from conversation — review before committing
- Architecture docs created during AI sessions may reference personal use cases — sanitize or gitignore

---

*Reusable across projects. Copy this file to any new repo as a starting point.*
