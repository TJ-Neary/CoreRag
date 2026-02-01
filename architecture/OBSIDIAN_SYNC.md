# Obsidian Sync & Conflict Resolution

> **Status**: ✅ Implemented | See `src/sync/` for implementation

## Overview

The PKM system syncs with Obsidian to enable visual exploration of your knowledge base using Obsidian's graph view, linking, and search capabilities.

---

## Sync Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PKM System                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   LanceDB   │  │   Metadata  │  │   Document Store    │  │
│  │   (Vector)  │  │   (SQLite)  │  │    (Original)       │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼─────────────────────┼────────────┘
          │                │                     │
          └────────────────┼─────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Sync Engine │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Export    │    │   Import    │    │  Conflict   │
│  (PKM→Obs)  │    │  (Obs→PKM)  │    │  Resolver   │
└─────────────┘    └─────────────┘    └─────────────┘
                           │
                    ┌──────▼──────┐
                    │   Obsidian   │
                    │    Vault     │
                    └─────────────┘
```

---

## Sync Modes

### Mode 1: Export Only (Recommended for Start)

PKM exports metadata to Obsidian; Obsidian is read-only mirror.

```python
class ExportOnlySync:
    """PKM is source of truth, Obsidian is display layer."""

    def sync(self):
        for doc in pkm.get_all_documents():
            obsidian_path = self.map_to_vault_path(doc)

            if not obsidian_path.exists():
                self.create_note(doc, obsidian_path)
            elif self.pkm_is_newer(doc, obsidian_path):
                self.update_note(doc, obsidian_path)
```

**Pros**: Simple, no conflicts possible
**Cons**: Edits in Obsidian are overwritten

### Mode 2: Bidirectional with Conflict Detection

Changes in either system are synced; conflicts are flagged.

```python
class BidirectionalSync:
    """Both systems can edit, conflicts require resolution."""

    def sync(self):
        pkm_changes = self.detect_pkm_changes()
        obs_changes = self.detect_obsidian_changes()

        # Check for conflicts
        conflicts = self.find_conflicts(pkm_changes, obs_changes)

        if conflicts:
            self.create_conflict_notes(conflicts)
            return  # User must resolve

        # Apply non-conflicting changes
        self.apply_pkm_to_obsidian(pkm_changes - conflicts)
        self.apply_obsidian_to_pkm(obs_changes - conflicts)
```

### Mode 3: Obsidian as Primary

Obsidian vault is source of truth; PKM indexes it.

```python
class ObsidianPrimarySync:
    """Obsidian is source of truth, PKM indexes it."""

    def sync(self):
        for note in vault.get_all_notes():
            if self.note_changed_since_last_sync(note):
                doc = self.convert_note_to_document(note)
                pkm.upsert_document(doc)
```

---

## Conflict Types & Resolution

### Type 1: Content Conflict

Both systems modified the same document.

**Detection**:
```python
def detect_content_conflict(doc_id):
    pkm_mtime = pkm.get_modified_time(doc_id)
    obs_mtime = obsidian.get_modified_time(doc_id)
    last_sync = sync_log.get_last_sync_time(doc_id)

    return pkm_mtime > last_sync and obs_mtime > last_sync
```

**Resolution Options**:

1. **Keep PKM version**
   ```python
   def resolve_keep_pkm(doc_id):
       pkm_content = pkm.get_content(doc_id)
       obsidian.write_note(doc_id, pkm_content)
   ```

2. **Keep Obsidian version**
   ```python
   def resolve_keep_obsidian(doc_id):
       obs_content = obsidian.read_note(doc_id)
       pkm.update_content(doc_id, obs_content)
   ```

3. **Create conflict note**
   ```python
   def resolve_create_conflict(doc_id):
       # Keep both versions
       obsidian.rename_note(doc_id, f"{doc_id} (PKM conflict)")
       obsidian.write_note(
           f"{doc_id} (Obsidian version)",
           obsidian.read_note(doc_id)
       )
   ```

4. **Merge (if possible)**
   ```python
   def resolve_merge(doc_id):
       pkm_content = pkm.get_content(doc_id)
       obs_content = obsidian.read_note(doc_id)
       merged = three_way_merge(base, pkm_content, obs_content)

       if merged.has_conflicts:
           # Manual merge needed
           return resolve_create_conflict(doc_id)

       pkm.update_content(doc_id, merged.content)
       obsidian.write_note(doc_id, merged.content)
   ```

### Type 2: Rename Conflict

Document renamed in both systems to different names.

**Resolution**:
```python
def resolve_rename_conflict(doc_id, pkm_name, obs_name):
    # Create mapping note
    obsidian.create_note("_conflicts/rename_conflicts.md", f"""
    ## Rename Conflict: {doc_id}

    - PKM name: {pkm_name}
    - Obsidian name: {obs_name}

    [Keep PKM name](pkm://resolve/rename/{doc_id}/pkm)
    [Keep Obsidian name](pkm://resolve/rename/{doc_id}/obsidian)
    """)
```

### Type 3: Delete Conflict

Deleted in one system, modified in other.

**Resolution**:
```python
def resolve_delete_conflict(doc_id, deleted_in, modified_in):
    # Always preserve modifications
    if modified_in == "pkm":
        pkm_content = pkm.get_content(doc_id)
        obsidian.write_note(doc_id, pkm_content)
    else:
        obs_content = obsidian.read_note(doc_id)
        pkm.restore_and_update(doc_id, obs_content)
```

### Type 4: Tag/Link Conflict

Tags or links differ between systems.

**Resolution**:
- Union of tags (combine both)
- Links validated against both systems

---

## Conflict Resolution UI

### In Obsidian

Create a `_conflicts/` folder with resolution notes:

```markdown
# Sync Conflicts

## Unresolved Conflicts (2)

### 1. [[Project Notes]] - Content Conflict
**Modified in PKM**: 2024-01-15 14:30
**Modified in Obsidian**: 2024-01-15 15:45

- [View PKM version](pkm://view/doc123)
- [View Obsidian version](obsidian://open?vault=PKM&file=Project%20Notes)

**Resolution**:
- [ ] Keep PKM version
- [ ] Keep Obsidian version
- [ ] Merge manually

### 2. [[Meeting Notes]] - Rename Conflict
**PKM name**: "Team Meeting 2024-01-15"
**Obsidian name**: "Weekly Standup"

- [ ] Use PKM name
- [ ] Use Obsidian name
```

### Via MCP

```python
@mcp_tool
def list_sync_conflicts():
    """List all sync conflicts."""
    conflicts = sync_engine.get_conflicts()
    return format_conflicts_for_claude(conflicts)

@mcp_tool
def resolve_conflict(conflict_id: str, resolution: str):
    """Resolve a sync conflict."""
    sync_engine.resolve(conflict_id, resolution)
    return f"Conflict {conflict_id} resolved with: {resolution}"
```

---

## Sync State Tracking

### Sync Log

```python
@dataclass
class SyncLogEntry:
    doc_id: str
    sync_time: str
    pkm_hash: str  # Content hash at sync time
    obs_hash: str
    sync_type: str  # "export", "import", "bidirectional"
    result: str  # "success", "conflict", "error"
```

### Last Known State

```json
{
  "doc123": {
    "last_sync": "2024-01-15T14:30:00Z",
    "pkm_hash": "abc123",
    "obs_hash": "abc123",
    "obs_path": "Projects/Project Notes.md"
  }
}
```

---

## Path Mapping

### PKM to Obsidian Path

```python
def map_pkm_to_obsidian(doc):
    """Map PKM document to Obsidian vault path."""

    # Use folder from source path or topic
    if doc.source_path:
        folder = Path(doc.source_path).parent.name
    elif doc.topic:
        folder = doc.topic
    else:
        folder = "Uncategorized"

    # Sanitize title for filename
    filename = sanitize_filename(doc.title) + ".md"

    return vault_root / folder / filename
```

### Obsidian to PKM ID

```python
def map_obsidian_to_pkm(note_path):
    """Find PKM document ID for Obsidian note."""

    # Check sync state
    for doc_id, state in sync_state.items():
        if state["obs_path"] == str(note_path):
            return doc_id

    # Try to match by title
    title = note_path.stem
    matches = pkm.search_by_title(title)

    if len(matches) == 1:
        return matches[0].id

    return None  # New note, needs import
```

---

## Note Format

### Exported Note Structure

```markdown
---
id: doc_abc123
source: /path/to/original.pdf
created: 2024-01-10T10:00:00Z
modified: 2024-01-15T14:30:00Z
tags:
  - project
  - ml
  - research
pkm_sync: true
---

# Document Title

## Summary

AI-generated summary of the document...

## Content

Full text content or key excerpts...

## Related

- [[Other Document]]
- [[Another Note]]

## Source

[Open original](file:///path/to/original.pdf)
```

### YAML Frontmatter Fields

| Field | Purpose |
|-------|---------|
| `id` | PKM document ID |
| `source` | Original file path |
| `created` | Creation timestamp |
| `modified` | Last modification |
| `tags` | Document tags |
| `pkm_sync` | Marker for synced notes |
| `pkm_hash` | Content hash for conflict detection |

---

## Handling Special Cases

### Large Documents

```python
if doc.content_length > 100_000:  # >100KB
    # Create summary note + link to full
    create_summary_note(doc)
    create_full_note(doc, in_archive=True)
```

### Binary Attachments

```python
if doc.type in ["pdf", "image", "audio"]:
    # Copy to attachments folder
    attachment_path = vault / "attachments" / doc.filename
    shutil.copy(doc.source_path, attachment_path)

    # Create note linking to attachment
    create_attachment_note(doc, attachment_path)
```

### Backlinks

```python
def generate_backlinks(doc_id):
    """Find and create backlinks."""
    mentions = pkm.find_documents_mentioning(doc_id)

    backlinks = []
    for mention in mentions:
        obs_path = map_pkm_to_obsidian(mention)
        backlinks.append(f"[[{obs_path.stem}]]")

    return backlinks
```

---

## Sync Schedule

```python
SYNC_SCHEDULE = {
    "full_sync": "daily at 3am",
    "incremental": "every 15 minutes",
    "on_change": True,  # Immediate sync on save
    "conflict_check": "every 5 minutes"
}
```

### Triggered Sync

```python
# When PKM ingests new document
@on_document_created
def sync_new_to_obsidian(doc):
    obsidian.create_note(map_pkm_to_obsidian(doc), doc.to_markdown())

# When Obsidian note changes (via file watcher)
@on_obsidian_change
def sync_change_to_pkm(note_path):
    doc_id = map_obsidian_to_pkm(note_path)
    if doc_id:
        check_for_conflicts(doc_id)
```
