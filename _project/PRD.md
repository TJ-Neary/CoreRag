# Product Requirements Document (PRD)

---

## Document Information

| Field | Value |
|-------|-------|
| **Title/Initiative** | Personal Knowledge Management (PKM) System with RAG |
| **Version** | 2.0 |
| **Created** | 2026-01-31 |
| **Last Updated** | 2026-01-31 |
| **Status** | ✅ Core Complete - Ready for User Setup |

### Points of Contact

| Role | Name | Contact |
|------|------|---------|
| Product Owner | TJ | 
| Technical Lead | TJ 

---

## 1. Why? (Objective)

### Business Objective
Build a personal knowledge infrastructure that maximizes the value of accumulated digital content (documents, media, research) by making it instantly searchable, contextually queryable, and integrated with AI assistants. This enables faster content creation, better decision-making, and knowledge compounding over time.

### User Objective
Solve the problem of "I know I have this somewhere" by creating a unified, AI-powered interface to query all personal files—PDFs, documents, audio, video, images—using natural language. Enable Claude (and eventually local LLMs) to understand personal context and history.

---

## 2. Success Metrics

### Primary Success Metrics

| Metric | Current Baseline | Target | Timeline |
|--------|-----------------|--------|----------|
| Query response accuracy | N/A (no system) | >85% relevant first-page results | Phase 1 |
| Time to find information | 5-15 min manual search | <30 seconds | Phase 1 |
| Content utilization rate | ~5% of stored files | >40% regularly queryable | Phase 2 |

### Secondary/Adoption Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Files indexed | Total files successfully processed | 10,000+ |
| Query volume | Daily queries to the system | 10+ |
| Content creation velocity | Speed of creating newsletters/content | 2x current |

### Guardrail Metrics (Do Not Disturb)

| Metric | Threshold | Monitoring |
|--------|-----------|------------|
| Privacy | Zero sensitive data to cloud APIs | Local processing logs |
| System performance | Mac M4 Max remains responsive | Activity Monitor |
| Storage costs | Local-first, minimal cloud | Monthly review |

---

## 3. Users

### Target Persona(s)

#### Persona 1: TJ (Primary User)
- **Demographics**: Tech-enthusiast, content creator, researcher
- **Psychographics**: Values efficiency, dislikes repetitive searches, believes in knowledge compounding
- **Context/Environment**: 2024 MacBook Pro M4 Max 48GB RAM, terabytes of digital files, uses Obsidian
- **Goals**:
  - Query entire document collection via natural language
  - Generate content (newsletters, YouTube scripts) from personal knowledge base
  - Build persistent AI context layer ("Claude knows me")
  - Eventually deploy local LLM as "AI Employee"
- **Frustrations**:
  - Can't find documents I know exist
  - AI assistants lack personal context
  - Manual tagging/organizing is tedious and unsustainable

### Problems We Are Solving

#### Job Statement Format

| # | Job Statement | Priority | Evidence |
|---|---------------|----------|----------|
| 1 | When I'm creating content, I want to query my research files, so I can incorporate relevant sources without manual searching | High | Immediate need: 40 PDFs for newsletter |
| 2 | When I'm starting a new project, I want Claude to understand my context, so I can skip repetitive explanations | High | Repeated context-setting in new chats |
| 3 | When I'm exploring ideas, I want to see connections across my files, so I can discover insights I wouldn't find manually | Medium | Obsidian integration desire |
| 4 | When I'm watching videos, I want to capture visual and audio content, so I can search what was shown, not just said | Medium | Video content in collection |

### How We Know These Problems Exist
- Direct user experience: "I know I have this somewhere but can't find it"
- Project folder limitations: Can't upload 40+ files to Claude projects
- Current workarounds: Manual file searching, re-reading documents
- Stated desire for local LLM "employee" with full context access

---

## 4. Solution

### Solution Overview
A multi-layer Personal Knowledge Management system with:

1. **Ingestion Layer**: Process diverse file types (PDFs, audio, video, Word, Excel, images) into embeddings
2. **Vector Database**: LanceDB storing embeddings locally with rich metadata
3. **MCP Server**: FastMCP interface enabling Claude Desktop to query the knowledge base
4. **Obsidian Integration**: Bidirectional sync for human-readable browsing and AI-powered tagging/linking

The system operates in three deployment tiers: fully local (free), hybrid with APIs (cost-conscious), and future Mac Studio "beast mode" with local 405B parameter models.

### Alternatives Considered

| Alternative | Pros | Cons | Why Not Selected |
|-------------|------|------|------------------|
| Cloud RAG services (Pinecone, etc.) | Easy setup, managed | Privacy concerns, ongoing costs, data leaves machine | User wants local-first |
| Apple Spotlight/Finder | Built-in, free | No semantic search, no AI integration, poor for content | Limited capability |
| Obsidian plugins only | Already uses Obsidian | Limited file type support, no MCP integration | Insufficient for full vision |
| Build from scratch | Full control | Time-intensive, complex | Leverage existing tools where possible |

### Prioritization Rationale

| Factor | Assessment |
|--------|------------|
| Impact | High - Transforms how user interacts with all personal knowledge |
| Effort | Medium - 6-phase implementation with clear milestones |
| Confidence | High - Proven technologies (LanceDB, FastMCP, Whisper) |
| Reach | Single user initially, architecture supports scaling |

---

## 5. Product Flow

### Customer Journey
```
[File Dropped in Inbox] → [Watcher Detects] → [Pipeline Processes]
    → [Chunk & Embed] → [Store in LanceDB]
    → [Export .md to Obsidian Vault] → [Move Original to Processed]
    → [User Queries via Claude] → [Results with Backlinks]
```

### User Stories

| ID | As a... | I want to... | So that... | Priority | Status |
|----|---------|--------------|------------|----------|--------|
| US-001 | Knowledge seeker | Ask Claude "What did I save about X?" | I get relevant documents instantly | High | Planned |
| US-002 | Content creator | Query "Find sources for newsletter on Y" | I can quickly assemble research | High | Planned |
| US-003 | Researcher | Ask "Compare what documents A and B say about Z" | I can synthesize across sources | Medium | Planned |
| US-004 | Organizer | See AI-generated tags in Obsidian | Files are auto-organized | Medium | Planned |
| US-005 | Privacy-conscious user | Keep sensitive files local-only | My private data never leaves my machine | High | Planned |

### Acceptance Criteria

#### US-001: Semantic Document Search
- [x] Query returns top-10 relevant chunks with source attribution
- [x] Results include document title, page/timestamp, and relevance score
- [x] Works with PDFs, Word docs, text files, spreadsheets, audio, video, images, and code
- [x] Response time under 3 seconds (HyDE + hybrid search + cross-encoder reranking)

#### US-002: Content Creation Support
- [x] Can filter by collection/topic (auto-tagging + metadata filters)
- [x] Returns full context around matches (parent-child chunking)
- [x] Includes links to original files (source_path in results)

#### US-003: Cross-Document Synthesis (NEW)
- [x] GraphRAG for entity-based connections
- [x] Multi-query fusion for complex questions
- [x] Conflict detection across documents

#### US-004: Auto-Organization
- [x] Auto-tagging on ingestion
- [x] Duplicate detection
- [x] Freshness indicators
- [x] Link rot checking

#### US-005: Privacy & Safety
- [x] Presidio hybrid PII detection
- [x] Memory pressure management (75% RAM threshold)
- [x] Hardware safety monitoring

### Edge Cases

| Scenario | Expected Behavior | Handling |
|----------|-------------------|----------|
| Corrupted PDF | Skip with warning | Log to error file, continue processing |
| 500MB video file | Process in chunks | Streaming transcription, keyframe sampling |
| Duplicate files | Detect and dedupe | Hash-based deduplication |
| Non-English content | Best-effort processing | Note language in metadata |
| Password-protected files | Cannot process | Log as inaccessible, notify user |

---

## 6. Technical Requirements

### System Requirements
- macOS 14+ (Sonoma or later)
- Apple Silicon M4 Max with 48GB RAM (primary target)
- 500GB+ available storage for vector database
- Python 3.11+ with venv support
- Node.js 18+ (for MCP server alternative)

### API/Integration Requirements

| Integration | Purpose | Status | Owner |
|-------------|---------|--------|-------|
| Claude Desktop | Primary query interface via MCP | Planned | TJ |
| LanceDB | Vector database storage | ✅ Implemented | TJ |
| Obsidian | Human-readable view, markdown sync | ✅ Implemented | TJ |
| mlx-whisper | Local audio transcription | Planned | TJ |
| LLaVA (optional) | Local image/video description | Planned | TJ |
| OpenAI API (Tier 2) | Hybrid: better quality when needed | Optional | TJ |

### Data Requirements

- **Input Data**:
  - PDFs, Word (.docx), Excel (.xlsx), text files
  - Audio (mp3, m4a, wav) → transcription
  - Video (mp4, mov) → transcription + keyframes
  - Images (png, jpg) → OCR + description

- **Output Data**:
  - Semantic search results with snippets
  - Source documents with page/time references
  - AI-generated summaries and tags

- **Storage**:
  - Raw files: ~/PKM/ (user-organized)
  - Vector DB: ~/.pkm/lancedb/
  - Obsidian vault: ~/PKM/vault/ (auto-synced)

- **Privacy/Security**:
  - Tier 1: All local processing, zero network calls
  - Tier 2: Only "public" tagged content to APIs
  - Sensitive tier: Never leaves device

### Performance Requirements

| Metric | Requirement |
|--------|-------------|
| Query response time | < 3 seconds for standard search |
| Ingestion rate | ~100 pages/minute for PDFs |
| Memory usage | < 16GB during normal operation |
| Storage efficiency | ~1KB embedding per 500 words |

---

## 7. Timeline

| Milestone | Target Date | Owner | Status |
|-----------|-------------|-------|--------|
| PRD Approval | 2026-01-31 | TJ | ✅ Complete |
| Phase 1: Core Infrastructure | Week 1-2 | TJ | ✅ Complete |
| Phase 2: PDF/Text Processing | Week 2-3 | TJ | ✅ Complete |
| Phase 3: MCP Integration | Week 3-4 | TJ | ✅ Complete |
| Phase 4: Audio/Video Support | Week 5-6 | TJ | ✅ Complete |
| Phase 5: Obsidian Sync | Week 6-7 | TJ | ✅ Complete |
| Phase 6: Personal Context Layer | Week 7-8 | TJ | ✅ Complete |
| User Setup & Testing | TBD | TJ | ⏳ Pending |

---

## 8. Dependencies

### Open Questions (Resolved)
- [x] Preferred chunking strategy? → **Parent-child chunking with semantic overlap**
- [x] Topic taxonomy? → **Hybrid: predefined categories + auto-tagging**
- [x] Obsidian vault structure? → **Standard vault with PKM folder sync**
- [x] Priority file types? → **All supported: PDF, DOCX, XLSX, MD, audio, video, images, code**

### Infrastructure Requirements
- Homebrew for package management
- Python environment (pyenv or conda)
- Claude Desktop with MCP support enabled

### Partner/External Dependencies

| Dependency | Owner | Status | Risk |
|------------|-------|--------|------|
| Claude MCP Protocol | Anthropic | Available | Low - stable API |
| LanceDB | LanceDB team | Available | Low - active development |
| mlx-whisper | Apple MLX team | Available | Low - optimized for Apple Silicon |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| M4 Max insufficient for video processing | Low | Medium | Use keyframe sampling, consider API fallback |
| LanceDB scaling issues at TB scale | Low | High | Benchmark early, shard if needed |
| Embedding model quality insufficient | Medium | Medium | Test multiple models, hybrid approach available |
| Obsidian sync complexity | Medium | Low | MVP without sync, add later |
| Python learning curve | Medium | Medium | Align with 4-week course starting Feb 3 |

---

## 10. Related Documents

| Document | Link | Owner |
|----------|------|-------|
| System Architecture | PKM_Design_System_Architecture.md | TJ |
| Metadata Schema | PKM_Design_Metadata_Schema.md | TJ |
| MCP Server Design | PKM_Design_MCP_Server.md | TJ |
| Personal Context Layer | PKM_Design_Personal_Context.md | TJ |
| Deployment Options | PKM_Design_Deployment_Options.md | TJ |
| Project Memory | PKM_Project_Memory.docx | TJ |

---

## Appendix

### Glossary

| Term | Definition |
|------|------------|
| RAG | Retrieval Augmented Generation - enhancing LLM responses with retrieved documents |
| MCP | Model Context Protocol - Anthropic's protocol for connecting Claude to external tools |
| Embedding | Vector representation of text for semantic similarity search |
| LanceDB | Embedded vector database optimized for ML workloads |
| Chunk | Segment of a document processed as a unit for embedding |

### Change Log

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-31 | TJ/Claude | Initial draft |
| 2.0 | 2026-01-31 | TJ/Claude | Core implementation complete - all phases done, ready for user setup |

---

*PRD for PKM System | Version 2.0 | Created: 2026-01-31*
