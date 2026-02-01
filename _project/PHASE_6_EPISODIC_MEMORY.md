# Phase 6: Episodic Memory Implementation

> **Status**: Planning  
> **Created**: 2026-02-01  
> **Priority**: High  
> **Dependencies**: Core ingestion pipeline (complete), MCP server (complete)

---

## Overview

Phase 6 introduces episodic memory to AntiGravity PKM, enabling the system to learn from user corrections and maintain context continuity across MCP sessions. This transforms the system from a stateless tool into a collaborative assistant that improves over time.

### Core Objectives

1. **Correction Learning** — Track when users override LLM suggestions and feed patterns back into future analysis
2. **Context Continuity** — Maintain session history so MCP conversations can pick up where they left off
3. **User Profile** — Aggregate facts, preferences, and current focus from observed behavior

---

## Priority 1: Correction Learning

### Problem Statement

The LLM makes suggestions for filenames, folders, and PII sensitivity. Users frequently override these in the dashboard. Currently, these corrections are lost — the system makes the same mistakes repeatedly.

### Data Already Available

At commit time in `executor.py`, we have access to:

| Field | Source | Description |
|-------|--------|-------------|
| `item['proposed']['filename']` | LLM suggestion | Original suggested filename |
| `item['proposed']['category']` | LLM suggestion | Original suggested category |
| `item['proposed']['target_folder']` | LLM suggestion | Original suggested folder path |
| `item['metadata']['is_sensitive']` | LLM + Presidio | Original PII determination |
| Final values | Dashboard edits | What the user actually chose |
| `item['metadata']['summary']` | LLM analysis | Document summary for context |
| `item['redacted_text']` | Processor | Document content (sampled) |

### Implementation

#### 1. Correction Event Schema

```python
# src/memory/correction_store.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json

@dataclass
class CorrectionEvent:
    id: str                          # UUID
    timestamp: datetime
    document_summary: str            # For semantic matching
    document_category: str           # LLM-assigned category
    
    # What the LLM suggested
    proposed_filename: str
    proposed_folder: str
    proposed_sensitive: bool
    
    # What the user chose
    actual_filename: str
    actual_folder: str
    actual_sensitive: bool
    
    # Derived
    filename_changed: bool
    folder_changed: bool
    sensitivity_changed: bool
    
    # Optional context
    sample_text: Optional[str] = None  # First 500 chars for pattern matching
```

#### 2. Capture Corrections at Commit Time

```python
# In executor.py, during commit_item()

def capture_correction(item: dict, final_edits: dict) -> Optional[CorrectionEvent]:
    """Compare proposed vs actual and log if different."""
    
    proposed = item.get('proposed', {})
    metadata = item.get('metadata', {})
    
    filename_changed = proposed.get('filename') != final_edits.get('filename')
    folder_changed = proposed.get('target_folder') != final_edits.get('target_folder')
    sensitivity_changed = metadata.get('is_sensitive') != final_edits.get('is_sensitive')
    
    if not (filename_changed or folder_changed or sensitivity_changed):
        return None  # No correction needed
    
    return CorrectionEvent(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(),
        document_summary=metadata.get('summary', ''),
        document_category=metadata.get('category', 'Unknown'),
        proposed_filename=proposed.get('filename', ''),
        proposed_folder=proposed.get('target_folder', ''),
        proposed_sensitive=metadata.get('is_sensitive', False),
        actual_filename=final_edits.get('filename', ''),
        actual_folder=final_edits.get('target_folder', ''),
        actual_sensitive=final_edits.get('is_sensitive', False),
        filename_changed=filename_changed,
        folder_changed=folder_changed,
        sensitivity_changed=sensitivity_changed,
        sample_text=item.get('redacted_text', '')[:500]
    )
```

#### 3. Storage Options

**Option A: SQLite (Recommended)**
- Simple, file-based, no dependencies
- Easy to query by correction type
- Can add FTS for text search

```python
# Schema
CREATE TABLE corrections (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    document_summary TEXT,
    document_category TEXT,
    proposed_filename TEXT,
    proposed_folder TEXT,
    proposed_sensitive INTEGER,
    actual_filename TEXT,
    actual_folder TEXT,
    actual_sensitive INTEGER,
    filename_changed INTEGER,
    folder_changed INTEGER,
    sensitivity_changed INTEGER,
    sample_text TEXT,
    embedding BLOB  -- Optional: for semantic retrieval
);

CREATE INDEX idx_corrections_category ON corrections(document_category);
CREATE INDEX idx_corrections_folder_changed ON corrections(folder_changed);
```

**Option B: LanceDB Table**
- Already in your stack
- Native vector search for semantic matching
- Consistent with RAG storage

#### 4. Inject Corrections into Analysis Prompt

```python
# In intelligence.py

def get_relevant_corrections(doc_summary: str, doc_category: str, k: int = 3) -> str:
    """Retrieve corrections similar to current document."""
    
    # Option 1: Category-based (simple)
    corrections = query_corrections_by_category(doc_category, limit=k)
    
    # Option 2: Semantic (better)
    # corrections = semantic_search_corrections(doc_summary, k=k)
    
    if not corrections:
        return ""
    
    examples = []
    for c in corrections:
        if c.folder_changed:
            examples.append(
                f"- Document about '{c.document_summary[:100]}' was categorized as "
                f"'{c.proposed_folder}' but user moved it to '{c.actual_folder}'"
            )
        if c.filename_changed:
            examples.append(
                f"- Suggested filename '{c.proposed_filename}' was changed to "
                f"'{c.actual_filename}'"
            )
    
    if not examples:
        return ""
    
    return f"""

Based on past corrections, the user has these preferences:
{chr(10).join(examples)}

Apply these patterns when making suggestions.
"""
```

Update `_ANALYSIS_PROMPT` to include:

```python
_ANALYSIS_PROMPT = """<document>
{text}
</document>
{correction_examples}
Analyze the document above and respond with ONLY a valid JSON object...
"""
```

#### 5. Pattern Aggregation

Over time, aggregate corrections into rules:

```python
def analyze_correction_patterns() -> dict:
    """Identify systematic user preferences."""
    
    corrections = get_all_corrections()
    
    patterns = {
        'folder_mappings': {},      # "Education" -> "Certifications/PHR" (3 times)
        'filename_preferences': [], # "Prefers underscores over spaces"
        'sensitivity_overrides': [] # "Marks financial docs as sensitive even when no PII detected"
    }
    
    # Folder remapping patterns
    folder_changes = [c for c in corrections if c.folder_changed]
    for c in folder_changes:
        key = c.proposed_folder
        if key not in patterns['folder_mappings']:
            patterns['folder_mappings'][key] = {}
        actual = c.actual_folder
        patterns['folder_mappings'][key][actual] = \
            patterns['folder_mappings'][key].get(actual, 0) + 1
    
    return patterns
```

---

## Priority 2: Context Continuity for MCP

### Problem Statement

Each MCP session starts fresh. Claude has no memory of previous conversations, forcing the user to re-establish context every time. The `get_user_context` tool exists but returns empty data.

### Design Goals

1. Automatically capture session activity without user action
2. Summarize sessions for efficient retrieval
3. Expose context through existing MCP tool
4. Keep storage lightweight (not a full chat log)

### Implementation

#### 1. Session Event Schema

```python
# src/memory/session_store.py

@dataclass
class SessionEvent:
    id: str
    session_id: str              # Groups events within a session
    timestamp: datetime
    event_type: str              # 'tool_call', 'search', 'ingest', 'commit'
    tool_name: Optional[str]
    parameters_summary: str      # Brief description, not full params
    result_summary: Optional[str]

@dataclass 
class SessionSummary:
    session_id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    summary: str                 # LLM-generated summary
    topics: list[str]            # Extracted topics
    documents_discussed: list[str]
    actions_taken: list[str]     # "Ingested 42 files", "Searched for X"
```

#### 2. Event Capture in MCP Server

```python
# In src/mcp_server/tools.py

from src.memory.session_store import log_session_event, get_or_create_session

# At module level or server init
_current_session_id = None

def _ensure_session():
    global _current_session_id
    if _current_session_id is None:
        _current_session_id = get_or_create_session()
    return _current_session_id

# Wrap each tool to log events
def search_knowledge(query: str, k: int = 5, **kwargs):
    session_id = _ensure_session()
    
    # Log the event
    log_session_event(
        session_id=session_id,
        event_type='search',
        tool_name='search_knowledge',
        parameters_summary=f"Query: '{query[:100]}', k={k}",
        result_summary=None  # Filled after execution
    )
    
    # Execute actual search
    results = _do_search(query, k, **kwargs)
    
    # Update with result summary
    update_event_result(
        session_id=session_id,
        result_summary=f"Found {len(results)} results"
    )
    
    return results
```

#### 3. Session Timeout and Summary Generation

```python
# src/memory/session_manager.py

SESSION_TIMEOUT_MINUTES = 30

def check_session_timeout():
    """Called periodically or on each tool call."""
    current = get_current_session()
    if not current:
        return
    
    last_activity = get_last_event_time(current.session_id)
    if datetime.now() - last_activity > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        finalize_session(current.session_id)

def finalize_session(session_id: str):
    """Generate summary and close session."""
    events = get_session_events(session_id)
    
    if not events:
        return
    
    # Generate summary with LLM
    summary_prompt = f"""Summarize this PKM session in 2-3 sentences:

Events:
{format_events_for_summary(events)}

Focus on: what the user was working on, key actions taken, any decisions made.
"""
    
    summary_text = generate_summary(summary_prompt)  # Use your LLM provider
    
    # Extract topics
    topics = extract_topics(events)
    
    # Save summary
    save_session_summary(SessionSummary(
        session_id=session_id,
        start_time=events[0].timestamp,
        end_time=events[-1].timestamp,
        duration_minutes=calculate_duration(events),
        summary=summary_text,
        topics=topics,
        documents_discussed=extract_documents(events),
        actions_taken=extract_actions(events)
    ))
    
    # Clear current session
    clear_current_session()
```

#### 4. Wire Up get_user_context

```python
# In src/mcp_server/tools.py

@mcp.tool()
def get_user_context() -> dict:
    """Get user profile and episodic memory context."""
    
    return {
        "facts": load_user_facts(),
        "preferences": get_aggregated_preferences(),
        "recent_sessions": get_recent_sessions(days=7),
        "current_focus": infer_current_focus(),
        "correction_patterns": get_correction_patterns_summary()
    }

def get_recent_sessions(days: int = 7) -> list[dict]:
    """Get session summaries from recent days."""
    cutoff = datetime.now() - timedelta(days=days)
    sessions = query_sessions_after(cutoff)
    
    return [
        {
            "date": s.start_time.isoformat(),
            "duration_minutes": s.duration_minutes,
            "summary": s.summary,
            "topics": s.topics
        }
        for s in sessions
    ]

def infer_current_focus() -> str:
    """Determine what user is currently working on based on recent activity."""
    recent = get_recent_sessions(days=3)
    
    if not recent:
        return "No recent activity"
    
    # Aggregate topics
    all_topics = []
    for s in recent:
        all_topics.extend(s.get('topics', []))
    
    if not all_topics:
        return "General PKM management"
    
    # Return most frequent topic
    from collections import Counter
    topic_counts = Counter(all_topics)
    return topic_counts.most_common(1)[0][0]
```

#### 5. Example Output

When Claude calls `get_user_context()` at the start of a conversation:

```json
{
  "facts": [
    "Prefers underscore_filenames over spaces",
    "PHR/SPHR certification in progress",
    "Marks all financial documents as sensitive"
  ],
  "preferences": {
    "filename_style": "underscore",
    "default_sensitive_categories": ["Financial", "Medical", "Legal"]
  },
  "recent_sessions": [
    {
      "date": "2026-02-01T09:15:00",
      "duration_minutes": 45,
      "summary": "Ingested 42 PHR study guide documents. Discussed Phase 6 episodic memory implementation. User interested in correction learning and context continuity.",
      "topics": ["PHR certification", "episodic memory", "system architecture"]
    },
    {
      "date": "2026-01-30T14:30:00", 
      "duration_minutes": 20,
      "summary": "Searched for HR compliance documents. Reorganized folder structure for Certifications category.",
      "topics": ["HR compliance", "folder organization"]
    }
  ],
  "current_focus": "PHR certification",
  "correction_patterns": {
    "folder": "Often moves 'Education' suggestions to 'Certifications/PHR'",
    "sensitivity": "Marks financial docs as sensitive regardless of PII detection"
  }
}
```

---

## Priority 3: User Facts and Preferences

### Manual Fact Storage

Allow explicit fact recording via MCP tool:

```python
@mcp.tool()
def add_user_fact(fact: str, category: str = "general") -> dict:
    """Add a fact about the user to episodic memory."""
    
    fact_id = store_user_fact(
        fact=fact,
        category=category,
        source="explicit",  # vs "inferred"
        timestamp=datetime.now()
    )
    
    return {
        "status": "stored",
        "fact_id": fact_id,
        "message": f"Remembered: {fact}"
    }
```

### Inferred Preferences

Derive preferences from behavior:

```python
def infer_preferences() -> dict:
    """Analyze behavior to infer preferences."""
    
    preferences = {}
    
    # Filename style preference
    corrections = get_filename_corrections()
    if corrections:
        underscore_count = sum(1 for c in corrections if '_' in c.actual_filename)
        space_count = sum(1 for c in corrections if ' ' in c.actual_filename)
        if underscore_count > space_count * 2:
            preferences['filename_style'] = 'underscore'
        elif space_count > underscore_count * 2:
            preferences['filename_style'] = 'spaces'
    
    # Sensitive category defaults
    sensitivity_overrides = get_sensitivity_corrections(override_to_sensitive=True)
    categories_marked_sensitive = [c.document_category for c in sensitivity_overrides]
    frequent_sensitive = get_frequent_items(categories_marked_sensitive, threshold=2)
    if frequent_sensitive:
        preferences['default_sensitive_categories'] = frequent_sensitive
    
    return preferences
```

---

## Storage Architecture

### Recommended: Single SQLite Database

```
~/.pkm/episodic.db
├── corrections        # Correction events
├── session_events     # Raw session activity  
├── session_summaries  # LLM-generated summaries
├── user_facts         # Explicit facts
└── preferences        # Derived preferences (cached)
```

### Schema

```sql
-- Corrections
CREATE TABLE corrections (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    document_summary TEXT,
    document_category TEXT,
    proposed_filename TEXT,
    proposed_folder TEXT,
    proposed_sensitive INTEGER,
    actual_filename TEXT,
    actual_folder TEXT,
    actual_sensitive INTEGER,
    filename_changed INTEGER,
    folder_changed INTEGER,
    sensitivity_changed INTEGER,
    sample_text TEXT
);

-- Session Events
CREATE TABLE session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    parameters_summary TEXT,
    result_summary TEXT
);

CREATE INDEX idx_session_events_session ON session_events(session_id);

-- Session Summaries
CREATE TABLE session_summaries (
    session_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_minutes INTEGER,
    summary TEXT,
    topics TEXT,  -- JSON array
    documents_discussed TEXT,  -- JSON array
    actions_taken TEXT  -- JSON array
);

-- User Facts
CREATE TABLE user_facts (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    source TEXT DEFAULT 'explicit',  -- 'explicit' or 'inferred'
    timestamp TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

-- Cached Preferences
CREATE TABLE preferences (
    key TEXT PRIMARY KEY,
    value TEXT,  -- JSON
    last_updated TEXT
);
```

---

## Implementation Phases

### Phase 6a: Correction Learning (Week 1)

- [ ] Create `src/memory/correction_store.py`
- [ ] Add SQLite schema for corrections
- [ ] Capture corrections in `executor.py` at commit time
- [ ] Update `intelligence.py` to query and inject corrections
- [ ] Test with 10+ manual corrections

### Phase 6b: Session Events (Week 2)

- [ ] Create `src/memory/session_store.py`
- [ ] Add session event logging to MCP tools
- [ ] Implement session timeout detection
- [ ] Add LLM summarization on session close

### Phase 6c: User Context (Week 3)

- [ ] Wire up `get_user_context` MCP tool
- [ ] Implement `add_user_fact` MCP tool
- [ ] Add preference inference logic
- [ ] Test end-to-end context retrieval

### Phase 6d: Polish (Week 4)

- [ ] Add dashboard panel for viewing/editing facts
- [ ] Implement correction pattern visualization
- [ ] Add session history browser
- [ ] Performance optimization (caching, indexing)

---

## Future Considerations

### Document Access Tracking

Track when documents are accessed (not just modified):

- Which documents are frequently referenced together
- Seasonal access patterns ("tax docs every March")
- Staleness based on access, not just age

### Knowledge Gap Detection

Identify what's missing from the knowledge base:

- Track searches with zero results
- Suggest documents to acquire
- "You've searched for X 5 times but have no documents on it"

### Cross-Session Continuity

More sophisticated session linking:

- Detect when user returns to a previous topic
- "Last week you were working on X, want to continue?"
- Project-based session grouping

---

## References

- `src/memory/episodic_memory.py` — Existing stub (Phase 6 placeholder)
- `src/correction_log.py` — Current simple correction logging
- `src/mcp_server/tools.py` — MCP tool definitions
- `architecture/data_schema.md` — Core data structures

---

*Document created during MCP session 2026-02-01. Topic: Phase 6 episodic memory planning.*
