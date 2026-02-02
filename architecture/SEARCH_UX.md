# Search UI/UX Specifications

> **Status**: ✅ Implemented | See `src/search/hybrid_search.py, src/search/hyde_search.py` for implementation

## Result Presentation

### Result Card Structure

Each search result should display:

```
┌────────────────────────────────────────────────────────────┐
│ 📄 Document Title                           Score: 0.89   │
│ ─────────────────────────────────────────────────────────  │
│ "...relevant snippet with **highlighted** query terms..." │
│                                                            │
│ 📁 Projects/ML-Research  │  📅 2024-01-15  │  🏷️ ml, rag │
│ 📍 Page 3, Para 2        │  📎 PDF         │  ⏱️ 5 min    │
└────────────────────────────────────────────────────────────┘
```

### Result Fields

| Field | Description | Source |
|-------|-------------|--------|
| Title | Document or chunk title | Metadata |
| Score | Relevance score (0.0-1.0) | Vector similarity |
| Snippet | Context around match | Chunk content |
| Location | Folder path | File system |
| Date | Last modified | File metadata |
| Tags | Applied tags | User + AI tags |
| Position | Page/paragraph/timestamp | Chunk metadata |
| Type | File type icon | File extension |
| Read time | Estimated read time | Word count / 200 |

### Highlighting

- Query terms: **bold**
- Semantic matches: *italic*
- Exact phrases: `highlighted background`
- Truncation: "...beginning...end..."

---

## Pagination Strategy

### Cursor-Based Pagination

```python
@dataclass
class SearchPage:
    results: List[SearchResult]
    cursor: Optional[str]  # Opaque cursor for next page
    has_more: bool
    total_estimate: int  # Approximate total results
    page_size: int
    search_time_ms: float
```

### Page Sizes

| Context | Default | Max |
|---------|---------|-----|
| Quick search | 5 | 10 |
| Full search | 20 | 50 |
| API response | 10 | 100 |
| Export | 100 | 1000 |

### Infinite Scroll vs Pages

- **MCP/Claude**: Return top 5-10 results, offer "show more"
- **CLI**: Traditional pages with --page flag
- **Obsidian**: Infinite scroll with lazy loading

---

## Result Ranking

### Default Ranking Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| Vector similarity | 0.50 | Core semantic match |
| Recency | 0.15 | Newer documents boosted |
| Access frequency | 0.10 | User engagement signal |
| Completeness | 0.10 | Metadata richness |
| Source quality | 0.10 | Trusted sources boosted |
| Exact match bonus | 0.05 | Keyword in title/tags |

### Ranking Formula

```python
final_score = (
    similarity * 0.50 +
    recency_boost(days_old) * 0.15 +
    access_score(access_count) * 0.10 +
    completeness_score(metadata) * 0.10 +
    source_quality(source) * 0.10 +
    exact_match_bonus(query, title) * 0.05
)
```

### Personalization

- Track which results user clicks
- Boost documents from frequently accessed folders
- Learn preferred file types per query type

---

## Search Modes

### Mode 1: Quick Search

- Single query box
- Returns top 5 results immediately
- No filters applied
- Optimized for speed (<500ms)

### Mode 2: Advanced Search

```
Query: machine learning
Filters:
  - Type: [PDF, MD]
  - Date: Last 30 days
  - Folder: /Projects/*
  - Tags: must have "ml"
  - Exclude: archived
Sort: relevance | date | title
```

### Mode 3: Natural Language

```
"Find my notes about neural networks from last month"
→ Parsed: {
    query: "neural networks",
    date_range: "last 30 days",
    type_hint: "notes"
  }
```

---

## Result Grouping

### Group by Document

When chunks from same document match:

```
📄 ML Fundamentals.pdf (3 matches)
├── Chapter 2: Neural Networks (0.92)
├── Chapter 5: Training Methods (0.87)
└── Appendix A: Glossary (0.71)
```

### Group by Topic

AI-detected topic clusters:

```
🏷️ Machine Learning (8 results)
🏷️ Data Processing (4 results)
🏷️ Python Programming (3 results)
```

### Group by Time

```
📅 This Week (2)
📅 This Month (5)
📅 Older (12)
```

---

## Empty/Error States

### No Results

```
🔍 No results found for "quantum computing"

Suggestions:
• Try broader terms: "computing", "physics"
• Check spelling
• Remove filters
• Search in: [All folders] [All time]
```

### Partial Results

```
⚠️ Showing 15 of ~100 results (some sources unavailable)

Unavailable:
• /Archive/old-notes/ (permission denied)
• 3 files still processing
```

### Search Error

```
❌ Search failed: Database connection timeout

[Retry] [Search cached results only] [Report issue]
```

---

## Keyboard Shortcuts (CLI/UI)

| Shortcut | Action |
|----------|--------|
| Enter | Open first result |
| ↑/↓ | Navigate results |
| Tab | Expand/collapse groups |
| / | Focus search box |
| Esc | Clear search |
| Ctrl+C | Copy result link |
| ? | Show help |

---

## MCP Response Format

```json
{
  "query": "machine learning concepts",
  "results": [
    {
      "title": "ML Fundamentals",
      "snippet": "...neural networks learn through...",
      "score": 0.89,
      "source": "📄 ML-Guide.pdf, Page 12",
      "link": "corerag://doc/abc123#chunk-5"
    }
  ],
  "meta": {
    "total": 47,
    "shown": 5,
    "time_ms": 234,
    "has_more": true
  },
  "suggestions": ["neural networks", "deep learning"]
}
```

### For Claude Display

```markdown
## Search Results for "machine learning concepts"

1. **ML Fundamentals** (89% match)
   > "...neural networks learn through backpropagation..."
   📄 ML-Guide.pdf, Page 12 | 🏷️ ml, tutorial

2. **Deep Learning Notes** (84% match)
   > "...gradient descent optimizes the loss function..."
   📝 deep-learning.md | 🏷️ ml, notes

[Show 42 more results]
```
