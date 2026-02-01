# Project Planning & Development Files

> ⚠️ **Internal Use Only** - These files are development artifacts, not part of the public codebase.

---

## Purpose

This folder contains planning documents, progress logs, and AI agent instructions used during development. They are kept for reference but should be **excluded from any public portfolio or release**.

---

## Contents

| File | Purpose |
|------|---------|
| `Master_Prompt.md` | AI agent system prompt with project context |
| `AGENT_INSTRUCTIONS.md` | Detailed instructions for AI development agents |
| `PRD.md` | Product Requirements Document (internal planning) |
| `task_plan.md` | Development task tracking and phase planning |
| `progress.md` | Session-by-session development log |
| `findings.md` | Research notes and technical discoveries |
| `project_memory.md` | Context preservation between sessions |
| `SETUP_TASKS.md` | User setup checklist |

---

## When to Delete

Before making this repository public or adding it to a portfolio:

1. Delete this entire `_project/` folder, OR
2. Add `_project/` to `.gitignore`

These files contain:
- Personal information (name, hardware details)
- Internal development notes
- AI agent instructions (not relevant to end users)

---

## Quick Cleanup Command

```bash
# Option 1: Delete the folder entirely
rm -rf _project/

# Option 2: Add to .gitignore (keeps locally but hides from git)
echo "_project/" >> .gitignore
```

---

*This folder is intentionally prefixed with `_` to sort it first alphabetically, making it easy to spot and manage.*
