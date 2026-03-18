# System Architecture

> Technical architecture documentation for CoreRag.
> Follows the [C4 Model](https://c4model.com/) with Mermaid.js diagrams.

---

## 1. System Context (C4 Level 1)

How CoreRag fits into the broader ecosystem.

```mermaid
C4Context
    title System Context — CoreRag

    Person(user, "User", "Knowledge worker managing documents")

    System(corerag, "CoreRag", "Local-first knowledge engine with semantic search, document ingestion, and PII detection")

    System_Ext(claude, "Claude Desktop", "AI assistant consuming CoreRag via MCP")
    System_Ext(obsidian, "Obsidian Vault", "Markdown knowledge base for exported documents")
    System_Ext(ollama, "Ollama", "Local LLM for document classification and analysis")

    Rel(user, corerag, "Manages documents, searches knowledge", "Dashboard / CLI / REST API")
    Rel(claude, corerag, "Searches knowledge base", "MCP stdio")
    Rel(corerag, obsidian, "Exports redacted markdown", "Filesystem")
    Rel(corerag, ollama, "Document analysis, classification", "HTTP localhost:11434")
```

---

## 2. Container Architecture (C4 Level 2)

The logical containers that compose CoreRag.

```mermaid
C4Container
    title Container Diagram — CoreRag

    Container(dashboard, "HITL Dashboard", "FastAPI + Jinja2", "Web UI for reviewing AI proposals, editing tags, approving documents")
    Container(api, "REST API v1", "FastAPI", "Authenticated endpoints for search, ingest, stats, document management")
    Container(mcp, "MCP Server", "FastMCP, stdio", "30 tools exposed to Claude Desktop for knowledge operations")
    Container(ingestion, "Ingestion Pipeline", "Python", "Watchdog + batch processor + PII detection + LLM classification")
    Container(search, "Search Stack", "Python", "Hybrid vector+BM25, reranking, HyDE, CRAG, multi-query fusion")
    Container(cli, "CLI", "Python argparse", "13 commands for search, ingest, health, backup, graph, memory")

    ContainerDb(lancedb, "LanceDB (Main)", "Lance format", "Vector store with parent-child chunks (BGE-M3, 1024d) — redacted content")
    ContainerDb(restricted_lancedb, "LanceDB (Restricted)", "Lance format", "Unredacted sensitive document chunks — access gated by per-agent search_restricted permission")
    ContainerDb(kg, "Knowledge Graph", "SQLite", "Bitemporal entity-relationship graph with confidence decay")
    ContainerDb(catalog_db, "Catalog", "SQLite", "Document catalog tracking files across all destinations (RAG, Obsidian, archive)")
    ContainerDb(staging, "Staging Manifest", "JSON file", "Pipeline state for documents in review")

    Rel(dashboard, ingestion, "Triggers batch processing")
    Rel(dashboard, staging, "Reads/writes document state")
    Rel(api, search, "Delegates search queries")
    Rel(mcp, search, "Delegates search queries")
    Rel(ingestion, lancedb, "Indexes redacted chunks with embeddings")
    Rel(ingestion, restricted_lancedb, "Indexes unredacted sensitive chunks")
    Rel(ingestion, kg, "Extracts entities and relationships")
    Rel(ingestion, catalog_db, "Registers documents at commit time")
    Rel(search, lancedb, "Hybrid search (vector + BM25 + RRF)")
    Rel(search, restricted_lancedb, "Restricted search (when search_scope=restricted or all)")
    Rel(search, kg, "Entity-based graph search")
```

---

## 3. Key Design Decisions

| Decision | Choice | Why | Alternatives Considered |
|----------|--------|-----|------------------------|
| Vector database | LanceDB (embedded) | Zero-config, Lance columnar format, native hybrid search | ChromaDB (less mature FTS), Qdrant (server overhead) |
| Embedding model | BAAI/bge-m3 (1024d) | Strong multilingual, MPS-optimized, good retrieval benchmarks | all-MiniLM-L6-v2 (384d, lower quality), OpenAI ada-002 (cloud dependency) |
| LLM provider | Ollama (local, qwen3:32b) | Privacy-preserving, no API costs, runs well on M4 Max | Claude API (better quality but sends data externally), Gemini API (same concern) |
| PII detection | Three-layer (Presidio + custom dict + LLM) | Defense in depth — NER catches patterns, dictionary catches known terms, LLM catches context | Single-layer Presidio (misses custom terms), LLM-only (unreliable for structured patterns) |
| Search fusion | RRF (Reciprocal Rank Fusion) | Simple, effective, no hyperparameter tuning needed | Linear combination (requires weight tuning), Borda count (less robust) |
| MCP transport | stdio | Claude Desktop native, no network setup | HTTP/SSE (requires server management, port conflicts) |
| Chunking | Parent-child hierarchical | Preserves document context, enables multi-resolution retrieval | Fixed-size (loses context), sentence-level (too granular) |

---

## 4. Data Flow

### Ingestion Pipeline

```mermaid
flowchart TD
    A[File dropped in Inbox] --> B[Watchdog / Batch Processor]
    B --> C[Text Extraction]
    C --> D{File Type}
    D -->|PDF| E[PyMuPDF + OCR fallback]
    D -->|DOCX| F[python-docx]
    D -->|Image| G[Vision.framework OCR + VLM]
    D -->|Audio| H[mlx-whisper transcription]
    D -->|Video| I[Keyframe extraction + audio]
    D -->|Text/MD/CSV/JSON| J[Direct read]
    E & F & G & H & I & J --> K[LLM Classification]
    K --> L[PII Detection — 3 layers]
    L --> M[Staging Manifest — pending]
    M --> N{Dashboard Review}
    N -->|Approved| O[Archive Original]
    O --> P[Export Redacted Markdown to Obsidian]
    O --> Q[RAG Indexing]
    Q --> R[Content Hash Dedup]
    R --> S[Contextual Retrieval — LLM prefix]
    S --> T[BGE-M3 Embedding]
    T --> U[LanceDB Insert]
    Q --> V[Knowledge Graph Entity Extraction]
    N -->|Rejected| W[Remove from staging]
```

### Search Flow

```mermaid
flowchart TD
    A[Query] --> B[HyDE Expansion]
    A --> C[Multi-Query Variants]
    B & C --> D[BGE-M3 Query Embedding]
    D --> E[Vector Search — LanceDB]
    A --> F[BM25 Full-Text Search]
    E & F --> G[RRF Fusion]
    G --> H[Cross-Encoder Reranking]
    H --> I[Corrective RAG Filter]
    I --> J[Time-Decay Scoring]
    J --> K[Ranked Results]
```

---

## 5. Security Posture

| Concern | Approach |
|---------|----------|
| Authentication | API key via `X-API-Key` header (optional — omit for open local access). Manifest endpoint always public. |
| Secrets Management | `.env` file (gitignored), loaded via python-dotenv. Template at `.env.example`. |
| Data at Rest | LanceDB + SQLite stored in `~/.corerag/` with user-level permissions. macOS FileVault for disk encryption. |
| Data in Transit | Localhost-only binding (`127.0.0.1:8000`). Ollama on `localhost:11434`. No external network calls by default. |
| PII Protection | Three-layer detection (Presidio NER + custom dictionary + LLM advisory). Redacted exports. `CUI_` filename prefix. |
| Input Validation | Query length limits, parameter validation on all API endpoints, path traversal prevention. |
| Rate Limiting | slowapi on REST API endpoints. |
| Memory Safety | Auto-pause at 75% RAM, resume at 65%. GC between files. Notification cooldown on pressure alerts. |

---

## 6. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python 3.12+ | Primary implementation |
| Web Framework | FastAPI + Jinja2 | REST API + dashboard |
| Vector Database | LanceDB (embedded) | Hybrid vector + full-text storage |
| Knowledge Graph | SQLite | Bitemporal entity-relationship store |
| Embeddings | BAAI/bge-m3 (1024d) | Semantic vector representations |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 | Post-retrieval relevance scoring |
| LLM | Ollama (qwen3:32b) | Document classification, contextual retrieval |
| PII Detection | Presidio + spaCy (en_core_web_lg) | NER-based entity detection |
| Audio | mlx-whisper | Apple Silicon speech-to-text |
| OCR | Vision.framework | Native macOS text extraction |
| MCP | FastMCP | Claude Desktop integration (stdio) |
| Rate Limiting | slowapi | API endpoint protection |
| CI/CD | GitHub Actions | Lint, test (matrix), security scan, build |
| Testing | pytest | Unit + integration with coverage |

---

## 7. Component Interaction

### Search Request via MCP

```mermaid
sequenceDiagram
    participant C as Claude Desktop
    participant M as MCP Server
    participant S as HybridSearcher
    participant E as EmbeddingService
    participant L as LanceDB
    participant R as CrossEncoderReranker

    C->>M: search_knowledge(query, k, tags)
    M->>E: embed(query)
    E-->>M: query_vector (1024d)
    M->>S: search(query, query_vector, k, filters)
    S->>L: Vector search + BM25
    L-->>S: Candidate results
    S->>S: RRF fusion
    S->>R: rerank(query, candidates)
    R-->>S: Reranked results
    S->>S: CRAG filter + time decay
    S-->>M: SearchResults
    M-->>C: Formatted results with context
```

---

*This document is updated when architectural decisions change.*
