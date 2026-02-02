# Complete System Architecture
## Personal Knowledge Management System

> **Status**: ✅ Core Complete | All major components implemented

*Last Updated: January 31, 2026*

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PERSONAL KNOWLEDGE MANAGEMENT SYSTEM                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                        INPUT SOURCES                                   │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐         │ │
│  │  │  PDFs   │ │  DOCX   │ │  Audio  │ │  Video  │ │ Images  │  ...    │ │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘         │ │
│  └───────┼──────────┼──────────┼──────────┼──────────┼──────────────────┘ │
│          │          │          │          │          │                     │
│          ▼          ▼          ▼          ▼          ▼                     │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                     INGESTION PIPELINE                                 │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │
│  │  │   Extract    │ │   Transcribe │ │    Chunk     │ │    Embed     │ │ │
│  │  │    Text      │ │   (Whisper)  │ │   Content    │ │   (nomic)    │ │ │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │ │
│  │         │                │                │                │          │ │
│  │         └────────────────┴────────────────┴────────────────┘          │ │
│  │                                   │                                    │ │
│  │                     ┌─────────────┴─────────────┐                     │ │
│  │                     │    Metadata Extraction    │                     │ │
│  │                     │  (Topics, Dates, Privacy) │                     │ │
│  │                     └─────────────┬─────────────┘                     │ │
│  └───────────────────────────────────┼───────────────────────────────────┘ │
│                                      │                                      │
│                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                       VECTOR DATABASE (LanceDB)                        │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │                         documents table                           │ │ │
│  │  │  (full metadata records for each source document)                │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │                          chunks table                             │ │ │
│  │  │  (embedded text chunks with document references)                  │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │                         context table                             │ │ │
│  │  │  (personal context / "About Me" data)                            │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                      │                                      │
│          ┌───────────────────────────┼───────────────────────────┐         │
│          │                           │                           │         │
│          ▼                           ▼                           ▼         │
│  ┌───────────────┐          ┌───────────────┐          ┌───────────────┐  │
│  │  MCP SERVER   │          │   OBSIDIAN    │          │  LOCAL LLM    │  │
│  │               │          │    VAULT      │          │   (Future)    │  │
│  │  ┌─────────┐  │          │               │          │               │  │
│  │  │ search  │  │          │ ┌───────────┐ │          │  ┌─────────┐  │  │
│  │  │ context │  │          │ │  Notes    │ │          │  │ Ollama  │  │  │
│  │  │ docs    │  │          │ │  Tags     │ │          │  │ Query   │  │  │
│  │  │ topics  │  │          │ │  Graph    │ │          │  │ Actions │  │  │
│  │  └────┬────┘  │          │ └───────────┘ │          │  └─────────┘  │  │
│  │       │       │          │               │          │               │  │
│  └───────┼───────┘          └───────────────┘          └───────────────┘  │
│          │                                                                  │
│          ▼                                                                  │
│  ┌───────────────┐                                                         │
│  │    CLAUDE     │ ◄─── Web Search (for current info)                      │
│  │    DESKTOP    │                                                         │
│  └───────────────┘                                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
~/.corerag/                              # Main CoreRag directory
├── config.yaml                      # Global configuration
├── db/                              # LanceDB vector database
│   ├── documents.lance/
│   ├── chunks.lance/
│   └── context.lance/
├── cache/                           # Processing cache
│   ├── embeddings/
│   └── transcripts/
├── logs/                            # Processing logs
└── quarantine/                      # Failed/problematic files

~/CoreRag/                               # User-facing directories
├── Inbox/                           # Drop files here for ingestion
├── Library/                         # Organized source files
│   ├── Research/
│   ├── Personal/
│   └── Reference/
└── Obsidian_Vault/                  # Obsidian knowledge view
    ├── Notes/                       # AI-generated notes per document
    ├── Topics/                      # Topic index pages
    ├── Context/                     # Personal context files
    ├── Projects/                    # Project tracking
    └── _templates/                  # Note templates

~/Code/corerag-system/                   # Application code
├── corerag_mcp_server/                  # MCP server
├── corerag_ingestion/                   # Ingestion pipeline
├── corerag_obsidian/                    # Obsidian sync
└── scripts/                         # Utility scripts
```

---

## Component Details

### 1. Ingestion Pipeline

**Purpose**: Watch for new files, extract content, generate embeddings, store in database.

```python
# corerag_ingestion/pipeline.py

class IngestionPipeline:
    def __init__(self, config: Config):
        self.extractors = {
            ".pdf": PDFExtractor(),
            ".docx": DocxExtractor(),
            ".xlsx": ExcelExtractor(),
            ".pptx": PowerPointExtractor(),
            ".mp3": AudioExtractor(),   # Uses Whisper
            ".mp4": VideoExtractor(),   # Audio track + keyframes
            ".png": ImageExtractor(),   # OCR + vision description
            ".jpg": ImageExtractor(),
            ".md": MarkdownExtractor(),
            ".txt": TextExtractor(),
        }
        self.embedder = EmbeddingModel()
        self.chunker = SemanticChunker()
        self.classifier = TopicClassifier()
        self.pii_detector = PIIDetector()
        self.db = DatabaseConnection()

    async def process_file(self, path: Path) -> ProcessingResult:
        """Full processing pipeline for a single file."""

        # 1. Extract content
        ext = path.suffix.lower()
        extractor = self.extractors.get(ext)
        if not extractor:
            raise UnsupportedFormatError(ext)

        content = await extractor.extract(path)

        # 2. Detect PII
        pii_result = await self.pii_detector.scan(content.text)

        # 3. Classify topics
        topics = await self.classifier.classify(content.text)

        # 4. Determine privacy tier
        privacy_tier = self.determine_privacy(pii_result, path)

        # 5. Build metadata
        metadata = DocumentMetadata(
            source_path=str(path),
            source_filename=path.name,
            source_type=ext[1:],  # Remove dot
            date_collected=datetime.now(),
            date_published=content.publication_date,
            topics=topics,
            topic_volatility=self.assess_volatility(topics),
            privacy_tier=privacy_tier,
            contains_pii=pii_result.has_pii,
            pii_types=pii_result.types,
            word_count=len(content.text.split()),
            page_count=content.page_count,
            checksum=compute_checksum(path),
        )

        # 6. Chunk content
        chunks = await self.chunker.chunk(
            content.text,
            metadata=content.section_info
        )

        # 7. Generate embeddings
        embeddings = await self.embedder.embed_batch(
            [c.text for c in chunks]
        )

        # 8. Store in database
        doc_id = await self.db.store_document(metadata)
        await self.db.store_chunks(doc_id, chunks, embeddings)

        # 9. Generate Obsidian note
        await self.generate_obsidian_note(doc_id, metadata, chunks)

        return ProcessingResult(
            document_id=doc_id,
            chunks_created=len(chunks),
            topics=topics,
            privacy_tier=privacy_tier
        )
```

**File Watcher**:
```python
# corerag_ingestion/watcher.py

class InboxWatcher:
    """Watch inbox folder and process new files."""

    def __init__(self, inbox_path: Path, pipeline: IngestionPipeline):
        self.inbox = inbox_path
        self.pipeline = pipeline

    async def run(self):
        async for changes in awatch(self.inbox):
            for change_type, path in changes:
                if change_type == Change.added:
                    await self.handle_new_file(Path(path))

    async def handle_new_file(self, path: Path):
        try:
            result = await self.pipeline.process_file(path)
            # Move to Library with organization
            dest = self.organize_file(path, result)
            shutil.move(path, dest)
            logger.info(f"Processed {path.name}: {result}")
        except Exception as e:
            # Move to quarantine
            shutil.move(path, self.quarantine / path.name)
            logger.error(f"Failed to process {path.name}: {e}")
```

---

### 2. Chunking Strategy

**Semantic chunking** preserves context better than fixed-size splits:

```python
# corerag_ingestion/chunker.py

class SemanticChunker:
    """Split documents into meaningful chunks."""

    def __init__(
        self,
        target_size: int = 512,      # Target tokens per chunk
        overlap: int = 64,            # Overlap between chunks
        respect_boundaries: bool = True
    ):
        self.target_size = target_size
        self.overlap = overlap
        self.respect_boundaries = respect_boundaries
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    async def chunk(
        self,
        text: str,
        metadata: SectionInfo | None = None
    ) -> list[Chunk]:
        chunks = []

        # If document has structure, respect it
        if metadata and metadata.sections:
            for section in metadata.sections:
                section_chunks = self.chunk_section(section)
                chunks.extend(section_chunks)
        else:
            # Fall back to paragraph-based chunking
            chunks = self.chunk_by_paragraphs(text)

        return chunks

    def chunk_section(self, section: Section) -> list[Chunk]:
        """Chunk a document section, keeping header context."""
        chunks = []
        header_prefix = f"## {section.title}\n\n"

        # Split section content
        paragraphs = section.content.split("\n\n")
        current_chunk = header_prefix
        current_tokens = len(self.tokenizer.encode(header_prefix))

        for para in paragraphs:
            para_tokens = len(self.tokenizer.encode(para))

            if current_tokens + para_tokens > self.target_size:
                # Save current chunk and start new one
                if current_chunk.strip():
                    chunks.append(Chunk(
                        text=current_chunk,
                        section_title=section.title,
                        start_page=section.start_page
                    ))
                current_chunk = header_prefix + para + "\n\n"
                current_tokens = len(self.tokenizer.encode(current_chunk))
            else:
                current_chunk += para + "\n\n"
                current_tokens += para_tokens

        # Don't forget last chunk
        if current_chunk.strip() and current_chunk != header_prefix:
            chunks.append(Chunk(
                text=current_chunk,
                section_title=section.title,
                start_page=section.start_page
            ))

        return chunks
```

---

### 3. Obsidian Integration

**Two-way sync** between RAG database and Obsidian vault:

```python
# corerag_obsidian/sync.py

class ObsidianSync:
    """Sync between LanceDB and Obsidian vault."""

    def __init__(self, vault_path: Path, db: DatabaseConnection):
        self.vault = vault_path
        self.db = db
        self.templates = self.load_templates()

    async def generate_document_note(
        self,
        doc_id: str,
        metadata: DocumentMetadata,
        chunks: list[Chunk]
    ):
        """Create/update Obsidian note for a document."""

        note_content = self.templates["document"].format(
            title=metadata.source_filename,
            source_path=metadata.source_path,
            date_collected=metadata.date_collected,
            date_published=metadata.date_published or "Unknown",
            topics=self.format_topic_links(metadata.topics),
            privacy=metadata.privacy_tier,
            summary=await self.generate_summary(chunks),
            key_points=await self.extract_key_points(chunks),
            tags=self.format_tags(metadata.topics),
            related=await self.find_related_links(doc_id),
        )

        note_path = self.get_note_path(metadata)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(note_content)

    async def generate_topic_index(self, topic: str):
        """Create/update topic index page."""

        docs = await self.db.get_documents_by_topic(topic)

        note_content = self.templates["topic"].format(
            topic=topic,
            document_count=len(docs),
            document_links=self.format_document_links(docs),
            subtopics=await self.get_subtopics(topic),
            related_topics=await self.get_related_topics(topic),
        )

        note_path = self.vault / "Topics" / f"{topic.replace('/', '_')}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(note_content)

    def format_topic_links(self, topics: list[str]) -> str:
        """Convert topics to Obsidian wiki links."""
        return " ".join([f"[[Topics/{t.replace('/', '_')}|{t}]]" for t in topics])
```

**Document Note Template**:
```markdown
---
created: {{date_collected}}
published: {{date_published}}
source: "{{source_path}}"
privacy: {{privacy}}
tags: {{tags}}
---

# {{title}}

## Summary
{{summary}}

## Key Points
{{key_points}}

## Topics
{{topics}}

## Related Documents
{{related}}

---
*Auto-generated by CoreRag*
```

---

### 4. Database Schema (LanceDB)

```python
# corerag_mcp_server/database/models.py

import lancedb
from lancedb.pydantic import LanceModel, Vector
from pydantic import Field
from datetime import datetime

class DocumentRecord(LanceModel):
    """Main document metadata table."""

    id: str = Field(description="UUID")
    source_path: str
    source_filename: str
    source_type: str
    source_url: str | None = None
    checksum: str

    date_collected: datetime
    date_published: datetime | None = None
    date_indexed: datetime

    topics: list[str]
    topic_volatility: str  # stable, moderate, fast_moving
    content_type: str      # research_paper, tutorial, etc.

    privacy_tier: str      # public, private, sensitive
    contains_pii: bool
    share_with_cloud: bool

    status: str            # active, superseded, archived
    collection: str        # research, personal, context

    chunk_count: int
    word_count: int
    embedding_model: str


class ChunkRecord(LanceModel):
    """Embedded text chunks for vector search."""

    chunk_id: str
    document_id: str       # Foreign key to DocumentRecord
    chunk_index: int
    chunk_text: str
    section_title: str | None = None
    start_page: int | None = None

    # Vector embedding
    vector: Vector(768)    # Dimension depends on embedding model

    # Denormalized for filtering
    topics: list[str]
    privacy_tier: str
    collection: str


class ContextRecord(LanceModel):
    """Personal context data."""

    id: str
    context_type: str      # identity, preferences, projects, etc.
    context_key: str       # Specific item within type
    content: dict          # Structured content
    vector: Vector(768)    # For semantic retrieval
    last_updated: datetime
    source: str            # user_input, learned, imported
```

---

### 5. Configuration

```yaml
# ~/.corerag/config.yaml

database:
  path: ~/.corerag/db
  type: lancedb

embedding:
  model: nomic-ai/nomic-embed-text-v1.5
  dimension: 768
  batch_size: 32
  device: mps  # Use Apple Silicon GPU

chunking:
  target_size: 512
  overlap: 64
  respect_boundaries: true

ingestion:
  inbox_path: ~/CoreRag/Inbox
  library_path: ~/CoreRag/Library
  watch_interval: 5  # seconds

  transcription:
    model: mlx-whisper
    language: auto

  pii_detection:
    enabled: true
    model: presidio
    redact_for_cloud: true

obsidian:
  vault_path: ~/CoreRag/Obsidian_Vault
  sync_enabled: true
  generate_summaries: true
  auto_link: true

privacy:
  default_tier: private
  sensitive_path_patterns:
    - "*/Personal/*"
    - "*/Financial/*"
    - "*/Medical/*"

topics:
  auto_classify: true
  max_depth: 3
  min_confidence: 0.7

mcp:
  port: null  # stdio mode
  privacy_mode: hybrid
  log_queries: true
```

---

## Data Flow Examples

### Adding a New PDF

```
1. User drops "AI_Research_Paper.pdf" into ~/CoreRag/Inbox/

2. File Watcher detects new file

3. Ingestion Pipeline:
   a. PDFExtractor reads text, identifies sections
   b. PIIDetector scans for sensitive data → none found
   c. TopicClassifier → ["AI", "AI/LLMs", "Research/Papers"]
   d. Privacy tier → "public" (no PII, research content)
   e. SemanticChunker creates 23 chunks
   f. EmbeddingModel generates 23 vectors

4. Database Storage:
   a. DocumentRecord created with full metadata
   b. 23 ChunkRecords stored with vectors

5. Obsidian Sync:
   a. Note created: ~/CoreRag/Obsidian_Vault/Notes/AI_Research_Paper.md
   b. Topic indexes updated: AI.md, AI_LLMs.md, Research_Papers.md
   c. Related document links added

6. File moved to ~/CoreRag/Library/Research/AI/AI_Research_Paper.pdf

7. Available to Claude via MCP:
   search_knowledge("transformer attention") → Returns relevant chunks
```

### Claude Query Flow

```
User: "What do I know about attention mechanisms in transformers?"

Claude (internally):
1. Calls search_knowledge(query="attention mechanisms transformers", topics=["AI"])

2. MCP Server:
   a. Embeds query using same model as ingestion
   b. Vector search in chunks table
   c. Filters by topic and privacy tier
   d. Returns top 10 relevant chunks with sources

3. Claude synthesizes response from chunks

4. Response includes source citations:
   "Based on your research collection:
    - 'Attention Is All You Need' discusses... [Source: AI_Research_Paper.pdf, p.3]
    - Your notes on BERT mention... [Source: BERT_Notes.md]"
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Set up LanceDB with basic schema
- [ ] Implement PDF extractor
- [ ] Basic chunking and embedding
- [ ] Simple CLI for adding documents
- [ ] Test with 40 PDFs + Word doc

### Phase 2: MCP Integration (Week 3-4)
- [ ] Build MCP server with FastMCP
- [ ] Implement search_knowledge tool
- [ ] Implement get_document tool
- [ ] Connect to Claude Desktop
- [ ] Test querying workflow

### Phase 3: Obsidian Sync (Week 5-6)
- [ ] Document note generation
- [ ] Topic index pages
- [ ] Bi-directional linking
- [ ] Manual tag editing sync

### Phase 4: Personal Context (Week 7-8)
- [ ] Context data structures
- [ ] get_context MCP tool
- [ ] Initial context bootstrap
- [ ] Preference learning from conversations

### Phase 5: Full Pipeline (Week 9-12)
- [ ] File watcher automation
- [ ] Multi-format extractors (audio, video, images)
- [ ] PII detection and redaction
- [ ] Topic auto-classification
- [ ] Quality monitoring dashboard

### Phase 6: Scale & Polish (Ongoing)
- [ ] Performance optimization
- [ ] Backup/restore procedures
- [ ] Deduplication
- [ ] Freshness monitoring
- [ ] Usage analytics

---

## Success Metrics

1. **Query Quality**: Relevant results for natural language queries
2. **Processing Speed**: < 1 minute per document (excluding transcription)
3. **Coverage**: All major file types supported
4. **Privacy**: Zero cloud leakage of sensitive content
5. **Obsidian Usability**: Clear, navigable knowledge graph
6. **Claude Integration**: Seamless tool usage in conversations

---

## Related Documents

- [Metadata Schema Design](./CoreRag_Design_Metadata_Schema.md)
- [MCP Server Architecture](./CoreRag_Design_MCP_Server.md)
- [Personal Context Layer](./CoreRag_Design_Personal_Context.md)
- [Project Memory](./CoreRag_Project_Memory.docx)
