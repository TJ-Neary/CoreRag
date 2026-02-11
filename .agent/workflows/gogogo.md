# /gogogo — AG Session Startup (CoreRag)

> Run this at the start of every session. Type `/gogogo` in the Antigravity sidebar.

## Steps

### Step 1: Load Project Context
// turbo

Read the project instruction files:
1. Read `CLAUDE.md` — project overview, commands, architecture
2. Read `ANTIGRAVITY.md` — your instruction file, composure conventions, domain lanes
3. Read `_project/DevPlan.md` — current roadmap and phase (if it exists)

### Step 2: Load HQ Context
// turbo

This is a **PUBLIC** project. Load public context only:
1. Read `~/Tech_Projects/_HQ/me/persona_public.md` — Who TJ is (PUBLIC)

3. Read `~/Tech_Projects/_HQ/sessions/session_memory.md` — recent session context across all projects

### Step 3: Check Agent Activity
// turbo

1. Read `sessions/agent_activity.md` — has CCT been active in this project? Any handoff notes?
2. Read `sessions/scratchpad.md` — any inter-agent notes from CCT?

If these files don't exist yet, that's fine — they'll be created during `/wrapup`.

### Step 4: Check HQ Message Board
// turbo

1. Read `~/Tech_Projects/_HQ/messages/BOARD.md` — any messages addressed to `CoreRag` or `ALL`?
2. Check `~/Tech_Projects/_HQ/messages/bulletins/` — any unacknowledged announcements?

### Step 5: Log Session Start

Append to `sessions/agent_activity.md` (create the file if it doesn't exist):
```markdown
### [current ISO datetime] — AG — Session Start
- Workspace: CoreRag
- Model: [your current model]
- Plan: [will be filled after TJ describes the task]
```

### Step 6: Present Status

Summarize for TJ:
1. **Project status** — key info from CLAUDE.md / DevPlan.md
2. **Recent activity** — what happened in the last session (from session_memory.md)
3. **CCT handoff notes** — anything CCT left in agent_activity.md or scratchpad.md
4. **Messages** — any relevant board messages or bulletins
5. **Ask what TJ wants to work on**
