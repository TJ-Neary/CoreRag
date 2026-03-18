# Metadata Schema Design
## Personal Knowledge Management System

> **Status**: ✅ Core Complete | All major components implemented
>
> **Note (P8/P9 updates):** `embedding_model` field value is now `BAAI/bge-m3` (1024d). Live chunk records include additional fields: `content_hash`, `context_prefix`, `quality_score`, `source_authority`, `date_extracted`, `is_sensitive`, `tags` (comma-delimited string). Authentication references in this doc are superseded by per-agent SettingsManager.

*Last Updated: January 31, 2026 (architecture notes updated March 2026)*

---

## Design Principles

1. **Capture once, use everywhere** - Metadata should serve RAG retrieval, Obsidian organization, and future local LLM access
2. **Enable filtering** - Support queries like "AI research from 2024" or "private documents only"
3. **Track freshness** - Know when information might be stale
4. **Preserve provenance** - Always know where information came from
5. **Support privacy tiers** - Distinguish what can go to cloud APIs vs. local-only

---

## Core Metadata Fields

### Document Identity

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `id` | UUID | Unique identifier for this document | `550e8400-e29b-41d4-a716-446655440000` |
| `source_path` | string | Original file location | `/Users/yourname/Research/AI/paper.pdf` |
| `source_filename` | string | Original filename | `attention_is_all_you_need.pdf` |
| `source_type` | enum | File format | `pdf`, `docx`, `audio`, `video`, `image`, `webpage`, `note` |
| `source_url` | string? | Original URL if web-sourced | `https://arxiv.org/abs/1706.03762` |
| `checksum` | string | SHA-256 hash for deduplication | `a1b2c3...` |

### Temporal Metadata

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `date_collected` | datetime | When you saved/downloaded this | `2026-01-15T14:30:00Z` |
| `date_published` | datetime? | When content was originally published | `2017-06-12T00:00:00Z` |
| `date_last_verified` | datetime? | Last time content was checked for accuracy | `2026-01-30T00:00:00Z` |
| `date_indexed` | datetime | When embedded into vector DB | `2026-01-15T15:00:00Z` |

### Content Classification

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `topics` | string[] | Primary topic tags (hierarchical allowed) | `["AI", "AI/Transformers", "Research"]` |
| `topic_volatility` | enum | How fast this domain changes | `stable`, `moderate`, `fast_moving` |
| `content_type` | enum | Nature of content | `research_paper`, `tutorial`, `news`, `reference`, `personal`, `notes` |
| `language` | string | ISO language code | `en`, `es`, `multi` |

### Privacy & Access Control

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `privacy_tier` | enum | Where this can be processed | `public`, `private`, `sensitive` |
| `contains_pii` | boolean | Whether PII was detected | `true` |
| `pii_types` | string[]? | What PII types if detected | `["name", "address", "ssn"]` |
| `redacted_version_id` | UUID? | Link to PII-scrubbed version | `...` |
| `share_with_cloud` | boolean | Explicit flag for cloud API use | `false` |

### Quality & Status

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `status` | enum | Document lifecycle state | `active`, `superseded`, `archived`, `deprecated` |
| `superseded_by` | UUID? | If replaced, link to newer version | `...` |
| `confidence_score` | float? | Trust/quality rating 0-1 | `0.95` |
| `extraction_quality` | enum | How clean was text extraction | `excellent`, `good`, `fair`, `poor` |
| `needs_review` | boolean | Flagged for human review | `false` |

### Processing Metadata

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `chunk_count` | int | Number of chunks in vector DB | `47` |
| `embedding_model` | string | Model used for embeddings | `nomic-embed-text-v1.5` |
| `processing_pipeline` | string | Version of ingestion pipeline | `v1.0.0` |
| `word_count` | int | Approximate word count | `12500` |
| `page_count` | int? | For documents with pages | `15` |
| `duration_seconds` | int? | For audio/video | `3600` |

### Relationships

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `related_documents` | UUID[] | Manually or AI-linked related docs | `[...]` |
| `parent_document` | UUID? | If this is a section of a larger work | `...` |
| `collection` | string | Logical grouping | `research`, `personal`, `context` |
| `project` | string? | Associated project if any | `CoreRag Development` |

---

## Topic Hierarchy (Starter Set)

Based on your described interests, here's an initial topic taxonomy:

```
AI/
├── Fundamentals/
├── LLMs/
│   ├── Architecture/
│   ├── Training/
│   ├── Inference/
│   └── Local_Models/
├── RAG/
├── Agents/
├── Computer_Use/
└── Ethics_Safety/

Technology/
├── Programming/
│   ├── Python/
│   ├── JavaScript/
│   └── Tools/
├── Infrastructure/
├── Security/
└── Emerging_Tech/

Research/
├── Papers/
├── Tutorials/
├── Documentation/
└── Case_Studies/

Personal/
├── Projects/
├── Notes/
├── Reference/
└── Context/   (About Me data)

Business/
├── Ideas/
├── Models/
└── Analysis/

Media/
├── Podcasts/
├── Videos/
├── Articles/
└── Books/
```

*This is extensible - new topics auto-create as needed*

---

## Privacy Tier Definitions

### `public`
- Can be sent to cloud APIs (Claude, OpenAI)
- Can be shared in Obsidian publish
- Research papers, public articles, tutorials

### `private`
- Process locally when possible
- Can send to cloud APIs if user explicitly approves per-query
- Personal notes, business ideas, unpublished work

### `sensitive`
- **Never** send to cloud APIs
- Local processing only
- Financial docs, medical records, credentials, PII-heavy content

---

## Volatility Ratings

### `stable`
- Content unlikely to become outdated
- Historical documents, classics, reference material
- Math, physics fundamentals, literature

### `moderate`
- May need verification after 1-2 years
- Programming tutorials, software documentation
- Business practices, industry standards

### `fast_moving`
- Potentially outdated within months
- AI/ML research, cutting-edge tech
- Current events, trending topics
- **Trigger**: Auto-flag for review after 6 months

---

## Chunk-Level Metadata

Each chunk (vector) also carries:

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | UUID | Unique chunk identifier |
| `document_id` | UUID | Parent document reference |
| `chunk_index` | int | Position in document |
| `chunk_text` | string | The actual text |
| `start_page` | int? | Page number if applicable |
| `section_title` | string? | Heading/section this belongs to |

---

## Example Document Record

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source_path": "/Users/yourname/Research/AI/attention_paper.pdf",
  "source_filename": "attention_is_all_you_need.pdf",
  "source_type": "pdf",
  "source_url": "https://arxiv.org/abs/1706.03762",
  "checksum": "sha256:a1b2c3d4...",

  "date_collected": "2026-01-15T14:30:00Z",
  "date_published": "2017-06-12T00:00:00Z",
  "date_indexed": "2026-01-15T15:00:00Z",

  "topics": ["AI", "AI/LLMs", "AI/LLMs/Architecture", "Research/Papers"],
  "topic_volatility": "moderate",
  "content_type": "research_paper",
  "language": "en",

  "privacy_tier": "public",
  "contains_pii": false,
  "share_with_cloud": true,

  "status": "active",
  "confidence_score": 0.98,
  "extraction_quality": "excellent",

  "chunk_count": 47,
  "embedding_model": "nomic-embed-text-v1.5",
  "word_count": 12500,
  "page_count": 15,

  "collection": "research",
  "related_documents": ["uuid-of-bert-paper", "uuid-of-gpt-paper"]
}
```

---

## Auto-Tagging Strategy

The ingestion pipeline should attempt automatic metadata extraction:

1. **Topic detection**: Use LLM to classify into topic hierarchy
2. **Date extraction**: Parse publication dates from content/filename
3. **PII scanning**: Run Presidio or similar to detect sensitive data
4. **Quality assessment**: Evaluate extraction completeness
5. **Relationship suggestion**: Find similar documents in existing corpus

Human review queue for:
- Low confidence classifications
- Newly detected topics not in hierarchy
- PII detection for sensitive tier assignment

---

## Future Extensions

- `embeddings_multimodal`: For image/diagram understanding
- `audio_transcript_id`: Link to transcript for audio/video
- `citation_count`: For research papers
- `personal_rating`: User's importance rating
- `access_count`: How often retrieved (for pruning)
- `summary`: AI-generated summary for quick reference
