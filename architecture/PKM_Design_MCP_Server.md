# MCP Server Architecture
## Personal Knowledge Management System

> **Status**: ✅ Core Complete | All major components implemented

*Last Updated: January 31, 2026*

---

## Overview

The MCP (Model Context Protocol) server exposes your personal knowledge base to Claude Desktop as callable tools. Claude can search, retrieve, and interact with your documents through natural language.

---

## Server Configuration

### Claude Desktop Config (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "pkm": {
      "command": "python",
      "args": ["-m", "pkm_mcp_server"],
      "env": {
        "PKM_DB_PATH": "/Users/tj/PKM/vector_db",
        "PKM_PRIVACY_MODE": "hybrid"
      }
    }
  }
}
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PKM_DB_PATH` | Path to LanceDB/vector database | `~/.pkm/db` |
| `PKM_OBSIDIAN_VAULT` | Path to Obsidian vault | `~/.pkm/obsidian` |
| `PKM_PRIVACY_MODE` | `local_only`, `hybrid`, `cloud_ok` | `hybrid` |
| `PKM_EMBEDDING_MODEL` | Model for query embeddings | `nomic-embed-text` |
| `PKM_LOG_LEVEL` | Logging verbosity | `INFO` |

---

## Tool Definitions

### 1. `search_knowledge`
**Primary search tool for semantic retrieval**

```python
@mcp.tool()
async def search_knowledge(
    query: str,
    collections: list[str] | None = None,
    topics: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    privacy_max: str = "private",
    limit: int = 10
) -> list[SearchResult]:
    """
    Search the personal knowledge base using semantic similarity.

    Args:
        query: Natural language search query
        collections: Filter to specific collections (research, personal, context)
        topics: Filter to specific topic tags
        date_from: Only documents published/collected after this date (YYYY-MM-DD)
        date_to: Only documents published/collected before this date
        privacy_max: Maximum privacy tier to include (public, private, sensitive)
        limit: Maximum number of results to return

    Returns:
        List of relevant document chunks with metadata and source citations
    """
```

**Example Usage by Claude:**
> "Let me search your knowledge base for information about transformer architectures..."
> *Calls: `search_knowledge(query="transformer architecture attention mechanisms", topics=["AI/LLMs"])`*

---

### 2. `get_document`
**Retrieve full document content and metadata**

```python
@mcp.tool()
async def get_document(
    document_id: str | None = None,
    source_path: str | None = None,
    include_content: bool = True,
    include_chunks: bool = False
) -> Document:
    """
    Retrieve a specific document by ID or path.

    Args:
        document_id: UUID of the document
        source_path: Original file path (alternative to ID)
        include_content: Whether to include full extracted text
        include_chunks: Whether to include individual chunk texts

    Returns:
        Full document record with metadata and optionally content
    """
```

---

### 3. `get_context`
**Retrieve personal context information**

```python
@mcp.tool()
async def get_context(
    context_type: str | None = None,
    specific_key: str | None = None
) -> ContextInfo:
    """
    Retrieve personal context information about the user.

    Args:
        context_type: Category of context (preferences, projects, background, style)
        specific_key: Specific context item to retrieve

    Returns:
        Relevant personal context for personalized responses

    Context Types:
        - preferences: Writing style, communication preferences, interests
        - projects: Current active projects and their status
        - background: Professional background, expertise areas
        - style: Writing samples, tone preferences
        - history: Previous topics discussed, decisions made
    """
```

**Example:**
> "Let me check your preferences for writing style..."
> *Calls: `get_context(context_type="style")`*

---

### 4. `list_topics`
**Browse the topic hierarchy**

```python
@mcp.tool()
async def list_topics(
    parent_topic: str | None = None,
    include_counts: bool = True
) -> list[TopicInfo]:
    """
    List topics in the knowledge base hierarchy.

    Args:
        parent_topic: Show children of this topic (None for root)
        include_counts: Include document counts per topic

    Returns:
        List of topics with optional document counts
    """
```

---

### 5. `list_collections`
**Show available document collections**

```python
@mcp.tool()
async def list_collections() -> list[CollectionInfo]:
    """
    List all document collections with statistics.

    Returns:
        Collection names, document counts, and descriptions
    """
```

---

### 6. `get_related`
**Find documents related to a given document**

```python
@mcp.tool()
async def get_related(
    document_id: str,
    limit: int = 5,
    same_collection: bool = False
) -> list[RelatedDocument]:
    """
    Find documents related to a specific document.

    Args:
        document_id: The reference document
        limit: Maximum related documents to return
        same_collection: Only search within same collection

    Returns:
        Related documents with similarity scores
    """
```

---

### 7. `check_freshness`
**Verify if information might be outdated**

```python
@mcp.tool()
async def check_freshness(
    document_id: str | None = None,
    topic: str | None = None
) -> FreshnessReport:
    """
    Check if documents in a topic or specific document might be outdated.

    Args:
        document_id: Check specific document
        topic: Check all documents in a topic

    Returns:
        Freshness assessment with recommendations
    """
```

---

### 8. `add_note`
**Add a quick note to the knowledge base**

```python
@mcp.tool()
async def add_note(
    content: str,
    topics: list[str],
    title: str | None = None,
    collection: str = "personal"
) -> NoteResult:
    """
    Add a quick note or insight to the knowledge base.

    Args:
        content: The note content (markdown supported)
        topics: Topic tags for classification
        title: Optional title for the note
        collection: Which collection to add to

    Returns:
        Confirmation with document ID and Obsidian link
    """
```

---

### 9. `summarize_topic`
**Get an overview of knowledge on a topic**

```python
@mcp.tool()
async def summarize_topic(
    topic: str,
    depth: str = "overview"
) -> TopicSummary:
    """
    Summarize what's known about a topic from the knowledge base.

    Args:
        topic: Topic to summarize
        depth: "overview" (quick), "detailed" (comprehensive)

    Returns:
        Summary of knowledge with key sources cited
    """
```

---

## Response Structures

### SearchResult
```python
@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    content: str           # The matching chunk text
    score: float           # Similarity score 0-1
    source_filename: str
    source_path: str
    page_number: int | None
    section_title: str | None
    date_published: str | None
    topics: list[str]
    privacy_tier: str
```

### Document
```python
@dataclass
class Document:
    id: str
    source_filename: str
    source_path: str
    source_type: str
    topics: list[str]
    date_collected: str
    date_published: str | None
    content: str | None      # If include_content=True
    metadata: dict           # Full metadata record
    obsidian_link: str       # Link to Obsidian note
```

---

## Server Implementation Skeleton

```python
# pkm_mcp_server/__main__.py

from mcp.server import Server
from mcp.server.fastmcp import FastMCP
import lancedb
from sentence_transformers import SentenceTransformer
import os

# Initialize
mcp = FastMCP("Personal Knowledge Manager")

# Connect to vector database
db_path = os.environ.get("PKM_DB_PATH", "~/.pkm/db")
db = lancedb.connect(db_path)
documents_table = db.open_table("documents")
chunks_table = db.open_table("chunks")

# Load embedding model
embed_model = SentenceTransformer(
    os.environ.get("PKM_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5"),
    trust_remote_code=True
)

@mcp.tool()
async def search_knowledge(
    query: str,
    collections: list[str] | None = None,
    topics: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    privacy_max: str = "private",
    limit: int = 10
) -> list[dict]:
    """Search the personal knowledge base."""

    # Generate query embedding
    query_embedding = embed_model.encode(query)

    # Build filter conditions
    filter_conditions = []

    if collections:
        filter_conditions.append(f"collection IN {collections}")

    if topics:
        # Topic matching (handles hierarchical topics)
        topic_conditions = [f"topics LIKE '%{t}%'" for t in topics]
        filter_conditions.append(f"({' OR '.join(topic_conditions)})")

    if privacy_max == "public":
        filter_conditions.append("privacy_tier = 'public'")
    elif privacy_max == "private":
        filter_conditions.append("privacy_tier IN ('public', 'private')")
    # 'sensitive' includes all

    if date_from:
        filter_conditions.append(f"date_published >= '{date_from}'")
    if date_to:
        filter_conditions.append(f"date_published <= '{date_to}'")

    # Execute search
    where_clause = " AND ".join(filter_conditions) if filter_conditions else None

    results = chunks_table.search(query_embedding) \
        .where(where_clause) \
        .limit(limit) \
        .to_pandas()

    # Format results
    return [
        {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "content": row["chunk_text"],
            "score": float(row["_distance"]),
            "source_filename": row["source_filename"],
            "page_number": row.get("start_page"),
            "section_title": row.get("section_title"),
            "topics": row["topics"],
        }
        for _, row in results.iterrows()
    ]


@mcp.tool()
async def get_context(
    context_type: str | None = None,
    specific_key: str | None = None
) -> dict:
    """Retrieve personal context about the user."""

    # Context is stored in a special 'context' collection
    results = documents_table.search() \
        .where("collection = 'context'") \
        .to_pandas()

    context = {}
    for _, row in results.iterrows():
        ctx_type = row.get("context_type", "general")
        if context_type and ctx_type != context_type:
            continue
        context[ctx_type] = row.get("content", {})

    if specific_key:
        for ctx_type, data in context.items():
            if isinstance(data, dict) and specific_key in data:
                return {specific_key: data[specific_key]}

    return context


# Add other tools...

if __name__ == "__main__":
    mcp.run()
```

---

## Directory Structure

```
pkm_mcp_server/
├── __init__.py
├── __main__.py           # Server entry point
├── config.py             # Configuration management
├── database/
│   ├── __init__.py
│   ├── connection.py     # LanceDB connection
│   ├── queries.py        # Common query patterns
│   └── models.py         # Data models
├── tools/
│   ├── __init__.py
│   ├── search.py         # search_knowledge tool
│   ├── documents.py      # get_document, get_related
│   ├── context.py        # get_context tool
│   ├── topics.py         # list_topics, summarize_topic
│   └── notes.py          # add_note tool
├── embeddings/
│   ├── __init__.py
│   └── encoder.py        # Embedding model wrapper
└── utils/
    ├── __init__.py
    ├── privacy.py        # Privacy tier filtering
    └── freshness.py      # Freshness checking logic
```

---

## Privacy Handling

The MCP server respects privacy tiers:

```python
PRIVACY_HIERARCHY = {
    "public": 1,
    "private": 2,
    "sensitive": 3
}

def filter_by_privacy(results, max_tier: str) -> list:
    """Filter results to only include allowed privacy tiers."""
    max_level = PRIVACY_HIERARCHY[max_tier]
    return [
        r for r in results
        if PRIVACY_HIERARCHY[r["privacy_tier"]] <= max_level
    ]
```

In `hybrid` mode:
- Local processing for all queries
- Only `public` tier content sent to cloud APIs for enhancement
- User prompted for `private` tier on per-query basis
- `sensitive` tier never leaves local system

---

## Integration with Obsidian

When Claude retrieves documents, include Obsidian links:

```python
def generate_obsidian_link(document_id: str, vault_path: str) -> str:
    """Generate an Obsidian URI for a document."""
    # Assuming documents have corresponding notes in vault
    note_path = get_obsidian_note_path(document_id)
    return f"obsidian://open?vault={vault_name}&file={note_path}"
```

This allows Claude to say: "Here's what I found. [Open in Obsidian](obsidian://...)"

---

## Future Enhancements

1. **Streaming responses** - For large document retrieval
2. **Write-back tools** - Update metadata, add relationships
3. **Ingestion tool** - Add new documents via Claude
4. **Analytics** - Track what's being searched, improve retrieval
5. **Conversation memory** - Store conversation insights back to context
6. **Multi-modal search** - Query by image similarity
