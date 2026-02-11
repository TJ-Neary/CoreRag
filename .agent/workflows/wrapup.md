# /wrapup — AG Session Close (CoreRag)

> Run this at the end of every session. Type `/wrapup` in the Antigravity sidebar.

## Steps

### Step 1: Summarize Session

Review the current conversation and identify:
- What was accomplished
- What files were created or modified
- What's still in progress or needs follow-up
- Any handoff notes for CCT

### Step 2: Update Session Memory

Append to `~/Tech_Projects/_HQ/sessions/session_memory.md` using this format:

```markdown
---
## [ISO Date] — [Agent: AG] — [Brief Title]
**Project:** CoreRag

**What was done:**
- [Item 1]
- [Item 2]

**Files changed:**
- `path/to/file.md` — [what changed]

**Open items / handoff notes:**
- [Anything CCT or TJ should know]

---
```

### Step 3: Update Agent Activity Log

Append to `sessions/agent_activity.md`:

```markdown
### [current ISO datetime] — AG — Session End
- Model used: [model name throughout session, note any swaps]
- Files changed:
  - `path/to/file` — [what changed]
- Handoff notes: [anything CCT should know]
- Uncommitted changes: [yes/no — if yes, list them]
```

### Step 4: Leave Scratchpad Notes (if applicable)

If there are tasks that CCT should pick up, add them to `sessions/scratchpad.md`:

```markdown
### From AG ([date])
- [Task or note for CCT]
```

### Step 5: Ecosystem Updates (if applicable)

If during this session you noticed:
- New extensions installed → Update `~/Tech_Projects/_HQ/research/tech_ecosystem.md`
- Version changes in tools → Update `~/Tech_Projects/_HQ/research/tech_ecosystem.md`
- Changes made without proper logging → Post `[PROCESS]` message to `~/Tech_Projects/_HQ/messages/BOARD.md`

### Step 6: Remind About Git

**Do NOT commit changes.** Remind TJ that uncommitted changes should be committed by CCT during its next session, unless TJ explicitly requests AG to commit.

### Step 7: Present Summary

Tell TJ:
1. What was accomplished this session
2. What's left in progress
3. Any handoff notes for CCT
4. Whether there are uncommitted changes that need CCT's attention
