# Resilience & Recovery Architecture

> **Status**: ✅ Implemented | See `src/utils/checkpoint_manager.py, src/utils/backup_manager.py` for implementation

> Ensure the system can recover from failures, handle duplicates, and maintain data integrity.

---

## Overview

This document covers:
- **Resumable Processing**: Checkpoint system for long-running jobs
- **Deduplication**: Prevent duplicate files and content
- **Incremental Updates**: Only reprocess changed files
- **Backup & Restore**: Protect against data loss
- **Retry Logic**: Handle transient failures gracefully

---

## 1. Resumable Processing

### Problem
Processing 10,000 files takes hours. If it fails at file 8,000, we don't want to start over.

### Solution: Checkpoint System

```python
# Checkpoint states
CHECKPOINT_STATES = {
    "pending": "Not started",
    "in_progress": "Currently processing",
    "completed": "Successfully finished",
    "failed": "Failed with error",
    "skipped": "Skipped (duplicate, unsupported, etc.)"
}
```

### Checkpoint File Structure

```
~/.pkm/checkpoints/
├── job_abc123.json           # Active job checkpoint
├── job_abc123.progress       # Detailed progress log
└── completed/
    └── job_xyz789.json       # Completed job (for audit)
```

### Checkpoint Schema

```json
{
    "job_id": "abc123",
    "job_type": "bulk_ingestion",
    "created_at": "2026-01-31T10:00:00Z",
    "updated_at": "2026-01-31T12:30:00Z",
    "status": "in_progress",
    "source_directory": "/Users/tj/PKM/Research",
    "total_files": 10000,
    "processed": 8000,
    "succeeded": 7950,
    "failed": 50,
    "skipped": 0,
    "current_file": "/Users/tj/PKM/Research/paper_8001.pdf",
    "files_status": {
        "/path/to/file1.pdf": {"status": "completed", "doc_id": "uuid1"},
        "/path/to/file2.pdf": {"status": "failed", "error": "Corrupted PDF"},
        "/path/to/file3.pdf": {"status": "skipped", "reason": "duplicate"}
    },
    "errors": [
        {"file": "/path/to/file2.pdf", "error": "Corrupted PDF", "timestamp": "..."}
    ],
    "config": {
        "batch_size": 32,
        "embedding_model": "nomic-embed-text-v1.5"
    }
}
```

### Resume Logic

```python
def resume_job(job_id: str) -> None:
    """Resume a previously interrupted job."""
    checkpoint = load_checkpoint(job_id)

    if checkpoint["status"] == "completed":
        print(f"Job {job_id} already completed")
        return

    # Find files not yet processed
    all_files = get_files_from_directory(checkpoint["source_directory"])
    processed_files = set(checkpoint["files_status"].keys())
    remaining_files = [f for f in all_files if str(f) not in processed_files]

    print(f"Resuming job {job_id}: {len(remaining_files)} files remaining")

    # Continue processing
    process_files(remaining_files, checkpoint)
```

---

## 2. Deduplication

### Problem
- Same file in multiple locations
- Same content in different files (copy-pasted)
- Re-ingesting already processed files

### Solution: Multi-Level Deduplication

#### Level 1: File Hash (Exact Duplicates)
```python
import hashlib

def get_file_hash(file_path: Path) -> str:
    """SHA-256 hash of file content."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
```

#### Level 2: Content Hash (Near Duplicates)
```python
def get_content_hash(text: str) -> str:
    """Hash of normalized text content."""
    # Normalize: lowercase, remove extra whitespace, remove punctuation
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode()).hexdigest()
```

#### Level 3: Semantic Similarity (Conceptual Duplicates)
```python
def is_semantic_duplicate(embedding: List[float], threshold: float = 0.95) -> Optional[str]:
    """Check if content is semantically very similar to existing."""
    results = vector_db.search(embedding, limit=1)
    if results and results[0].score > threshold:
        return results[0].doc_id
    return None
```

### Deduplication Decision Matrix

| Scenario | Detection | Action |
|----------|-----------|--------|
| Exact same file | File hash match | Skip, log as duplicate |
| Same content, different file | Content hash match | Skip, link to original |
| Very similar content (>95%) | Semantic similarity | Warn, ask user |
| Related content (80-95%) | Semantic similarity | Index, mark as related |

### Dedup Database Table

```python
dedup_schema = {
    "file_hash": str,        # SHA-256 of file
    "content_hash": str,     # SHA-256 of normalized text
    "file_paths": List[str], # All paths with this content
    "canonical_doc_id": str, # The "main" document ID
    "first_seen": datetime,
    "last_seen": datetime,
}
```

---

## 3. Incremental Updates

### Problem
When source files change, we need to update the index without reprocessing everything.

### Solution: File Modification Tracking

```python
@dataclass
class FileState:
    """Track file state for change detection."""
    path: str
    size: int
    modified_time: float
    file_hash: str
    last_indexed: datetime
    doc_id: Optional[str]
```

### Change Detection

```python
def detect_changes(directory: Path) -> ChangeSet:
    """Detect new, modified, and deleted files."""
    current_files = scan_directory(directory)
    known_files = load_file_states()

    changes = ChangeSet()

    for path, state in current_files.items():
        if path not in known_files:
            changes.new.append(path)
        elif state.modified_time > known_files[path].last_indexed:
            # File modified since last index
            if state.file_hash != known_files[path].file_hash:
                changes.modified.append(path)

    for path in known_files:
        if path not in current_files:
            changes.deleted.append(path)

    return changes

@dataclass
class ChangeSet:
    new: List[Path] = field(default_factory=list)
    modified: List[Path] = field(default_factory=list)
    deleted: List[Path] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.new or self.modified or self.deleted)
```

### Update Strategies

| Change Type | Strategy |
|-------------|----------|
| New file | Full ingestion |
| Modified file | Delete old chunks, re-ingest |
| Deleted file | Mark as deleted (soft delete) or remove |
| Renamed file | Update path, keep content if hash matches |

---

## 4. Backup & Restore

### What to Backup

| Component | Location | Priority |
|-----------|----------|----------|
| Vector database | `~/.pkm/lancedb/` | Critical |
| File states | `~/.pkm/state/` | Critical |
| Configuration | `~/.pkm/config/` | High |
| Personal context | `~/.pkm/context/` | High |
| Checkpoints | `~/.pkm/checkpoints/` | Medium |
| Logs | `~/.pkm/logs/` | Low |

### Backup Script

```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="$HOME/.pkm/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="pkm_backup_$TIMESTAMP"

mkdir -p "$BACKUP_DIR"

# Create backup
tar -czf "$BACKUP_DIR/$BACKUP_NAME.tar.gz" \
    -C "$HOME/.pkm" \
    lancedb state config context

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +8 | xargs -r rm

echo "Backup created: $BACKUP_DIR/$BACKUP_NAME.tar.gz"
```

### Restore Script

```bash
#!/bin/bash
# scripts/restore.sh

BACKUP_FILE=$1

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: restore.sh <backup_file.tar.gz>"
    exit 1
fi

# Stop any running services
pkill -f "pkm_server" || true

# Backup current state (just in case)
mv "$HOME/.pkm" "$HOME/.pkm.old.$(date +%s)"

# Restore
mkdir -p "$HOME/.pkm"
tar -xzf "$BACKUP_FILE" -C "$HOME/.pkm"

echo "Restored from: $BACKUP_FILE"
```

### Automated Backup Schedule

```python
# Add to crontab: crontab -e
# Run backup daily at 2am
# 0 2 * * * /path/to/scripts/backup.sh >> ~/.pkm/logs/backup.log 2>&1
```

---

## 5. Retry Logic

### Retry Configuration

```python
@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True

    # Which exceptions to retry
    retryable_exceptions: tuple = (
        ConnectionError,
        TimeoutError,
        RateLimitError,
    )
```

### Retry Decorator

```python
import random
import time
from functools import wraps

def with_retry(config: RetryConfig = None):
    """Decorator for automatic retry with exponential backoff."""
    config = config or RetryConfig()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    if attempt == config.max_attempts - 1:
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** attempt),
                        config.max_delay
                    )

                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        delay *= (0.5 + random.random())

                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

            raise last_exception
        return wrapper
    return decorator

# Usage
@with_retry()
def call_openai_api(text: str) -> List[float]:
    return openai.embeddings.create(input=text, model="text-embedding-3-small")
```

### Rate Limit Handler

```python
class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, calls_per_minute: int = 60):
        self.calls_per_minute = calls_per_minute
        self.tokens = calls_per_minute
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 60.0) -> bool:
        """Wait for a token, return True if acquired."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            with self._lock:
                self._refill()
                if self.tokens > 0:
                    self.tokens -= 1
                    return True
            time.sleep(0.1)

        return False

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        refill = elapsed * (self.calls_per_minute / 60.0)
        self.tokens = min(self.calls_per_minute, self.tokens + refill)
        self.last_refill = now

# Usage
rate_limiter = RateLimiter(calls_per_minute=60)

def call_api_with_rate_limit(text: str):
    if not rate_limiter.acquire():
        raise RateLimitError("Could not acquire rate limit token")
    return call_api(text)
```

---

## 6. Error Categories

### Error Classification

| Category | Examples | Retry? | Action |
|----------|----------|--------|--------|
| Transient | Network timeout, rate limit | Yes | Retry with backoff |
| Recoverable | Corrupted file, unsupported format | No | Skip, log error |
| Fatal | Out of disk space, DB corruption | No | Stop, alert user |
| User Error | Bad config, missing permissions | No | Stop, show fix |

### Error Handling Flow

```
Error Occurs
    ↓
Is it transient? ──Yes──→ Retry (up to max_attempts)
    │                              ↓
    No                      Still failing?
    ↓                              ↓
Is it recoverable? ──Yes──→ Skip file, continue job
    │
    No
    ↓
Is it fatal? ──Yes──→ Stop job, save checkpoint, alert user
    │
    No
    ↓
Log and continue
```

---

## Implementation Priority

1. **Checkpoint System** - Essential for long jobs
2. **File Hash Deduplication** - Prevents obvious waste
3. **Retry Logic** - Handles network issues
4. **Backup Script** - Protects data
5. **Incremental Updates** - Efficiency for ongoing use
6. **Content Deduplication** - Nice to have
7. **Semantic Deduplication** - Advanced feature

---

*All processing operations must be resumable. Never lose user's time or data.*
