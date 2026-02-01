# Chunking Strategy: Parent-Child Indexing

> **Status**: ✅ Implemented | See `src/chunking/parent_child.py` for implementation

## The Problem

Standard recursive character splitting creates two failures:

1. **Context Fracture**: Splits occur mid-explanation, separating premise from conclusion
2. **Retrieval-Generation Mismatch**: Optimal search units (specific sentences) ≠ optimal context units (full paragraphs/sections)

## Solution: Small-to-Big Retrieval

Decouple the **Search Unit** from the **Context Unit**.

```
┌─────────────────────────────────────────────────────────────┐
│                     PARENT CHUNK                            │
│  (Full section/page - 1000-2000 tokens)                    │
│  Stored in: parent_chunks table                             │
│  Returned to: LLM for context                               │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │   CHILD 1   │ │   CHILD 2   │ │   CHILD 3   │           │
│  │ 100-200 tok │ │ 100-200 tok │ │ 100-200 tok │           │
│  │  Embedded   │ │  Embedded   │ │  Embedded   │           │
│  │  Searched   │ │  Searched   │ │  Searched   │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## Data Model

```python
@dataclass
class ParentChunk:
    id: str                    # UUID
    document_id: str           # FK to document
    content: str               # Full section text (1000-2000 tokens)
    start_char: int            # Position in original document
    end_char: int
    section_title: Optional[str]
    metadata: dict

@dataclass
class ChildChunk:
    id: str                    # UUID
    parent_id: str             # FK to ParentChunk
    document_id: str           # FK to document
    content: str               # Small text (100-200 tokens)
    embedding: List[float]     # 768-dim vector
    start_char: int            # Position within parent
    end_char: int
    chunk_index: int           # Order within parent
```

## LanceDB Schema

```python
# Parent chunks table (no embeddings - just storage)
parent_schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("document_id", pa.string()),
    pa.field("content", pa.string()),
    pa.field("section_title", pa.string()),
    pa.field("start_char", pa.int64()),
    pa.field("end_char", pa.int64()),
    pa.field("token_count", pa.int32()),
    pa.field("metadata", pa.string()),  # JSON
])

# Child chunks table (with embeddings - searchable)
child_schema = pa.schema([
    pa.field("id", pa.string()),
    pa.field("parent_id", pa.string()),
    pa.field("document_id", pa.string()),
    pa.field("content", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 768)),
    pa.field("start_char", pa.int64()),
    pa.field("end_char", pa.int64()),
    pa.field("chunk_index", pa.int32()),
])
```

## Chunking Algorithm

### Step 1: Create Parent Chunks (Section-Level)

```python
def create_parent_chunks(document: str, max_tokens: int = 1500) -> List[ParentChunk]:
    """
    Split document into parent chunks at natural boundaries.
    Priority order:
    1. Markdown headers (# ## ###)
    2. Double newlines (paragraph breaks)
    3. Token limit fallback
    """
    # Detect document type
    if has_markdown_headers(document):
        return split_by_headers(document, max_tokens)
    else:
        return split_by_paragraphs(document, max_tokens)
```

### Step 2: Create Child Chunks (Sentence-Level)

```python
def create_child_chunks(
    parent: ParentChunk,
    target_tokens: int = 150,
    overlap_tokens: int = 25
) -> List[ChildChunk]:
    """
    Split parent into overlapping child chunks.
    Respects sentence boundaries where possible.
    """
    sentences = sent_tokenize(parent.content)
    children = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = count_tokens(sentence)

        if current_tokens + sent_tokens > target_tokens and current_chunk:
            # Emit chunk
            children.append(create_child(current_chunk, parent))
            # Overlap: keep last N tokens worth
            current_chunk = get_overlap(current_chunk, overlap_tokens)
            current_tokens = count_tokens(" ".join(current_chunk))

        current_chunk.append(sentence)
        current_tokens += sent_tokens

    # Final chunk
    if current_chunk:
        children.append(create_child(current_chunk, parent))

    return children
```

## Retrieval Pipeline

```python
async def search_with_parent_context(
    query: str,
    k: int = 10,
    parent_k: int = 5
) -> List[RetrievalResult]:
    """
    1. Embed query
    2. Search child chunks (high precision)
    3. Deduplicate by parent_id
    4. Fetch parent content (high context)
    5. Return parent chunks with child match info
    """
    # Step 1: Vector search on children
    query_embedding = embed(query)
    child_results = child_table.search(query_embedding).limit(k * 3).to_list()

    # Step 2: Group by parent, keep best child per parent
    parent_scores = {}
    for child in child_results:
        pid = child["parent_id"]
        if pid not in parent_scores or child["_distance"] < parent_scores[pid]["score"]:
            parent_scores[pid] = {
                "parent_id": pid,
                "score": child["_distance"],
                "matched_child": child["content"],
                "child_id": child["id"]
            }

    # Step 3: Sort by score, take top parent_k
    top_parents = sorted(parent_scores.values(), key=lambda x: x["score"])[:parent_k]

    # Step 4: Fetch full parent content
    results = []
    for p in top_parents:
        parent = parent_table.search().where(f"id = '{p['parent_id']}'").to_list()[0]
        results.append(RetrievalResult(
            content=parent["content"],           # FULL CONTEXT
            matched_snippet=p["matched_child"],  # What matched
            score=p["score"],
            document_id=parent["document_id"],
            section_title=parent.get("section_title")
        ))

    return results
```

## Token Budget Recommendations

| Document Type | Parent Size | Child Size | Overlap |
|---------------|-------------|------------|---------|
| Technical docs | 1500 tokens | 150 tokens | 25 tokens |
| Narrative text | 2000 tokens | 200 tokens | 50 tokens |
| Code files | Variable (function/class) | 100 tokens | 0 |
| Transcripts | 1000 tokens (by topic) | 150 tokens | 25 tokens |

## Integration with Existing Systems

### Deduplication
- Deduplicate at **document level** before chunking
- Child chunks inherit parent's `content_hash` for incremental updates

### Citation Tracking
- Citations reference `parent_id` + `child_id` for precision
- Display shows parent context with matched child highlighted

### Privacy Tiers
- Privacy tier applies at **parent level**
- All children inherit parent's tier

## Migration from Flat Chunks

```python
def migrate_to_parent_child(existing_table: str):
    """
    One-time migration from flat chunks to parent-child structure.
    """
    # 1. Group existing chunks by document_id
    # 2. Reconstruct approximate parents (consecutive chunks)
    # 3. Re-embed children with new smaller size
    # 4. Build parent-child relationships
    # 5. Atomic swap of tables
```

## Performance Considerations

- **Storage**: ~10% overhead (parent content duplicated from children)
- **Ingestion**: Slightly slower (two-pass chunking)
- **Retrieval**: Faster (fewer vectors to return, dedup at DB level)
- **LLM Context**: Much better (complete thoughts, not fragments)
