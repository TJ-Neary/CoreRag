# PKM System - Project Memory

---

## Project Overview

**Project**: Personal Knowledge Management System with RAG
**Owner**: TJ
**Started**: 2026-01-31
**Status**: Phase 1 Complete - Comprehensive Blind Spot Fixes Implemented
**Workspace**: AntiGravity_PKM (Google Antigravity agents)

---

## Key Decisions Log

| Date | Decision | Rationale | Impact |
|------|----------|-----------|--------|
| 2026-01-31 | Use LanceDB for vector storage | Embedded, handles TB scale, no server needed | Core infrastructure |
| 2026-01-31 | Use FastMCP (Python) for MCP server | Aligns with Python learning, simpler than TypeScript | Development framework |
| 2026-01-31 | Local-first with hybrid option | Privacy priority, but allow API fallback for quality | Architecture design |
| 2026-01-31 | 3-tier deployment model | Support M4 Max now, future Mac Studio later | Scalability planning |
| 2026-01-31 | D.R.I.V.E. protocol for development | Structured methodology for project execution | Process framework |
| 2026-01-31 | A/B testing before model selection | Data-driven decisions on local vs API | Quality assurance |
| 2026-01-31 | Hardware safety monitoring required | Prevent overheating/memory exhaustion on M4 Max | System reliability |
| 2026-01-31 | SafeProcessor wrapper mandatory | Automatic throttling for all heavy workloads | Performance safety |
| 2026-01-31 | Checkpoint system for resumability | Long jobs can be interrupted and resumed | Reliability |
| 2026-01-31 | Multi-level deduplication | Prevent duplicate files/content/semantic matches | Storage efficiency |
| 2026-01-31 | Privacy scanning before ingestion | Detect and block sensitive data automatically | Data protection |

---

## Session History

### Session 1: 2026-01-31
**Focus**: Complete project setup for Antigravity agents

**Phase 1 - Discovery & Architecture**:
- ✅ User requirements gathered (M4 Max 48GB, local-first, terabyte scale)
- ✅ 4-layer system architecture designed
- ✅ 25+ metadata fields defined
- ✅ 9 MCP tools specified
- ✅ Personal context layer with 7 categories
- ✅ 3 deployment tiers documented

**Phase 2 - Templates**:
- ✅ PRD_Template.md + .docx
- ✅ Master_Prompt_Template.md + .docx
- ✅ PKM-specific PRD.md
- ✅ PKM-specific Master_Prompt.md

**Phase 3 - Antigravity Workspace**:
- ✅ AntiGravity_PKM folder structure created
- ✅ All architecture docs copied
- ✅ AGENT_INSTRUCTIONS.md (agents read first)
- ✅ CONVENTIONS.md (coding standards)
- ✅ requirements.txt + pyproject.toml
- ✅ .env.example

**Phase 4 - Performance & Safety**:
- ✅ PERFORMANCE_GUIDE.md (M4 Max optimization)
- ✅ HARDWARE_SAFETY.md (monitoring & throttling)
- ✅ TESTING_FRAMEWORK.md (A/B local vs API comparison)
- ✅ Working code: hardware_monitor.py, throttle_controller.py, safe_processor.py

**Phase 5 - Resilience & Recovery** (NEW):
- ✅ RESILIENCE.md (architecture documentation)
- ✅ checkpoint.py - Resumable processing with job tracking
- ✅ deduplication.py - Multi-level duplicate detection
- ✅ incremental.py - Changed file detection
- ✅ backup.py - Database backup and restore
- ✅ retry.py - Exponential backoff with circuit breaker
- ✅ queue_manager.py - Priority job queue with rate limiting
- ✅ privacy_audit.py - Sensitive data detection

**Phase 6 - Testing & Documentation**:
- ✅ tests/ directory with fixtures and unit tests
- ✅ Sample documents for testing
- ✅ USER_GUIDE.md - Comprehensive user documentation

**Phase 7 - Comprehensive Gap Analysis & Completion** (FINAL):
- ✅ architecture/SEARCH_UX.md - Search result presentation, pagination, ranking
- ✅ architecture/MULTIMODAL_SEARCH.md - Unified vector space for all media types
- ✅ architecture/MIGRATION_STRATEGY.md - Embedding model upgrade path
- ✅ architecture/OBSIDIAN_SYNC.md - Conflict resolution strategies
- ✅ architecture/ACCESS_CONTROL.md - Privacy tiers, roles, permissions
- ✅ src/utils/citations.py - Source tracking with precise locations
- ✅ src/utils/feedback.py - User feedback loop for relevance tuning
- ✅ src/utils/health.py - System health checks and status dashboard
- ✅ src/utils/logging_config.py - Structured logging with multiple outputs
- ✅ src/utils/export.py - Multi-format export capabilities
- ✅ src/utils/versioning.py - Document version history with diffs
- ✅ src/utils/search_history.py - Search history and saved queries
- ✅ src/utils/collections.py - Document organization and smart collections
- ✅ src/utils/tagging.py - AI-powered tagging workflow
- ✅ .github/workflows/ci.yml - CI pipeline (lint, test, security, docs, build)
- ✅ .github/workflows/release.yml - Release automation
- ✅ requirements-dev.txt - Development dependencies
- ✅ pyproject.toml updated with full tooling config

**Workspace Status**: 60+ files ready for Antigravity agents - ALL CHECKLIST ITEMS COMPLETE

### Session 2: 2026-01-31 (Continued)
**Focus**: Comprehensive Blind Spot Analysis & Implementation

**P0 Critical Fixes**:
- ✅ Parent-Child Indexing - architecture/CHUNKING_STRATEGY.md + src/chunking/parent_child.py
- ✅ LanceDB FTS Index Enforcement - src/search/hybrid_search.py (with RRF scoring)
- ✅ Apple Vision.framework OCR - src/ocr/vision_ocr.py (15-20x faster than Tesseract)
- ✅ Cross-Encoder Re-ranking - src/search/reranker.py
- ✅ .pkmignore File & Parser - .pkmignore + src/utils/pkmignore.py
- ✅ Zombie Chunk Reconciliation - src/sync/reconciliation.py
- ✅ Debug Mode for MCP - src/mcp_server/tools.py (debug=True flag)
- ✅ Golden Dataset + Regression Tests - tests/golden_set.yaml + tests/test_golden_set.py

**P1 Important Fixes**:
- ✅ Lightweight GraphRAG - src/graph/knowledge_graph.py (SQLite triple store)
- ✅ VLM Captioning - src/multimodal/vlm_captioner.py (Moondream2/Qwen2.5-VL)
- ✅ Audio Topic Segmentation - src/audio/topic_segmentation.py
- ✅ Time-Weighted Scoring - src/search/decay_scoring.py
- ✅ AST-Based Code Chunking - src/chunking/code_chunker.py (Tree-sitter)
- ✅ Spreadsheet Summary Pattern - src/processors/spreadsheet_processor.py
- ✅ Metacognition Tools - src/mcp_server/tools.py (list_recent_files, get_folder_structure)
- ✅ Episodic Memory - src/memory/episodic_memory.py

**Verification & Upgrades**:
- ✅ MIGRATION_STRATEGY.md verified - Contains parallel indexes, atomic pointer switch, rollback
- ✅ safe_processor.py upgraded - >75% RAM pause, user query prioritization, IngestionController
- ✅ privacy_audit.py upgraded - Presidio hybrid (NER for PII, regex for technical secrets)

---

## Workspace Structure

```
AntiGravity_PKM/
├── AGENT_INSTRUCTIONS.md      ← Agents read FIRST
├── README.md
├── PRD.md                     ← Requirements (read-only)
├── Master_Prompt.md
├── CONVENTIONS.md
├── requirements.txt
├── requirements-dev.txt       ← Development dependencies
├── pyproject.toml             ← Full tooling config
├── .env.example
├── project_memory.md          ← This file
├── task_plan.md
├── progress.md
├── findings.md
│
├── .github/workflows/         ← CI/CD Pipelines
│   ├── ci.yml                 ← Lint, test, security, build
│   └── release.yml            ← Automated releases
│
├── architecture/              ← Design Documents (18 files)
│   ├── PERFORMANCE_GUIDE.md   ← M4 Max optimization
│   ├── HARDWARE_SAFETY.md     ← Safety monitoring
│   ├── TESTING_FRAMEWORK.md   ← A/B testing
│   ├── RESILIENCE.md          ← Recovery systems
│   ├── SEARCH_UX.md           ← Search result presentation
│   ├── MULTIMODAL_SEARCH.md   ← Unified vector space
│   ├── MIGRATION_STRATEGY.md  ← Embedding model upgrades
│   ├── OBSIDIAN_SYNC.md       ← Conflict resolution
│   ├── ACCESS_CONTROL.md      ← Privacy tiers & roles
│   ├── data_schema.md
│   └── PKM_Design_*.md        ← Core design documents
│
├── src/
│   ├── models/                ← ✅ Complete (Document, Chunk, SearchResult, Context)
│   ├── chunking/              ← ✅ NEW (parent_child.py, code_chunker.py)
│   ├── search/                ← ✅ NEW (hybrid_search.py, reranker.py, decay_scoring.py)
│   ├── ocr/                   ← ✅ NEW (vision_ocr.py - Apple Vision.framework)
│   ├── graph/                 ← ✅ NEW (knowledge_graph.py - Lightweight GraphRAG)
│   ├── audio/                 ← ✅ NEW (topic_segmentation.py)
│   ├── multimodal/            ← ✅ NEW (vlm_captioner.py)
│   ├── processors/            ← ✅ NEW (spreadsheet_processor.py)
│   ├── sync/                  ← ✅ NEW (reconciliation.py)
│   ├── memory/                ← ✅ NEW (episodic_memory.py)
│   ├── mcp_server/            ← ✅ NEW (tools.py with debug mode + metacognition)
│   └── utils/                 ← ✅ Upgraded (17+ modules)
│       ├── hardware_monitor.py
│       ├── throttle_controller.py
│       ├── safe_processor.py
│       ├── checkpoint.py
│       ├── deduplication.py
│       ├── incremental.py
│       ├── backup.py
│       ├── retry.py
│       ├── queue_manager.py
│       ├── privacy_audit.py
│       ├── citations.py       ← Source tracking
│       ├── feedback.py        ← User feedback loop
│       ├── health.py          ← System health checks
│       ├── logging_config.py  ← Structured logging
│       ├── export.py          ← Multi-format export
│       ├── versioning.py      ← Document versions
│       ├── search_history.py  ← Search history
│       ├── collections.py     ← Document organization
│       └── tagging.py         ← AI-powered tagging
│
├── tests/                     ← ✅ Complete
│   ├── __init__.py
│   ├── test_utils.py
│   └── fixtures/
│       └── sample_documents.py
│
└── docs/                      ← ✅ Complete
    └── USER_GUIDE.md
```

---

## Technology Stack

| Component | Choice | Status |
|-----------|--------|--------|
| Vector Database | LanceDB | Selected |
| Embeddings | nomic-embed-text-v1.5 | Selected |
| Audio Transcription | mlx-whisper | Selected |
| MCP Framework | FastMCP | Selected |
| File Processing | Unstructured | Selected |
| Safety Monitoring | src/utils/ | ✅ Implemented |
| Data Models | src/models/ | ✅ Implemented |
| Resilience Systems | src/utils/ | ✅ Implemented |
| Testing Framework | pytest | ✅ Configured |
| OCR | Apple Vision.framework | ✅ Implemented |
| Re-ranking | Cross-Encoder (ms-marco) | ✅ Implemented |
| PII Detection | Presidio (hybrid) | ✅ Implemented |
| Code Parsing | Tree-sitter | ✅ Implemented |
| Knowledge Graph | SQLite (Lightweight) | ✅ Implemented |
| VLM Captioning | Moondream2 / Qwen2.5-VL | ✅ Implemented |

---

## Implemented Features (All 26 Checklist Items)

### Resilience & Recovery
| Feature | File | Status |
|---------|------|--------|
| Checkpoints/Resumable Jobs | checkpoint.py | ✅ Complete |
| File-level Deduplication | deduplication.py | ✅ Complete |
| Content-level Deduplication | deduplication.py | ✅ Complete |
| Semantic Deduplication | deduplication.py | ✅ Complete |
| Incremental Updates | incremental.py | ✅ Complete |
| File Watcher | incremental.py | ✅ Complete |
| Database Backup | backup.py | ✅ Complete |
| Auto-backup Scheduler | backup.py | ✅ Complete |
| Backup Verification | backup.py | ✅ Complete |
| Exponential Backoff | retry.py | ✅ Complete |
| Circuit Breaker | retry.py | ✅ Complete |
| Priority Job Queue | queue_manager.py | ✅ Complete |
| Rate Limiting | queue_manager.py | ✅ Complete |

### Privacy & Security
| Feature | File | Status |
|---------|------|--------|
| Privacy Scanning | privacy_audit.py | ✅ Complete |
| Sensitive Data Detection | privacy_audit.py | ✅ Complete |
| Access Control Design | ACCESS_CONTROL.md | ✅ Complete |
| Privacy Tiers | ACCESS_CONTROL.md | ✅ Complete |

### Search & UX
| Feature | File | Status |
|---------|------|--------|
| Search UI/UX Design | SEARCH_UX.md | ✅ Complete |
| Multi-modal Search | MULTIMODAL_SEARCH.md | ✅ Complete |
| Citation Tracking | citations.py | ✅ Complete |
| Search History | search_history.py | ✅ Complete |
| Saved Queries | search_history.py | ✅ Complete |

### User Feedback & Analytics
| Feature | File | Status |
|---------|------|--------|
| Click-through Tracking | feedback.py | ✅ Complete |
| Relevance Boosting | feedback.py | ✅ Complete |
| Explicit Feedback | feedback.py | ✅ Complete |

### Organization & Content
| Feature | File | Status |
|---------|------|--------|
| Collections | collections.py | ✅ Complete |
| Smart Collections | collections.py | ✅ Complete |
| AI-powered Tagging | tagging.py | ✅ Complete |
| Version History | versioning.py | ✅ Complete |
| Document Diffs | versioning.py | ✅ Complete |

### Operations & DevOps
| Feature | File | Status |
|---------|------|--------|
| Health Checks | health.py | ✅ Complete |
| Status Dashboard | health.py | ✅ Complete |
| Structured Logging | logging_config.py | ✅ Complete |
| Export (Markdown/JSON/ZIP) | export.py | ✅ Complete |
| CI Pipeline | ci.yml | ✅ Complete |
| Release Pipeline | release.yml | ✅ Complete |

### Integration & Migration
| Feature | File | Status |
|---------|------|--------|
| Obsidian Sync | OBSIDIAN_SYNC.md | ✅ Complete |
| Conflict Resolution | OBSIDIAN_SYNC.md | ✅ Complete |
| Embedding Migration | MIGRATION_STRATEGY.md | ✅ Complete |

### Retrieval Quality (P0 Fixes)
| Feature | File | Status |
|---------|------|--------|
| Parent-Child Indexing | chunking/parent_child.py | ✅ Complete |
| Hybrid Search (FTS+Vector) | search/hybrid_search.py | ✅ Complete |
| Cross-Encoder Re-ranking | search/reranker.py | ✅ Complete |
| Time-Weighted Decay | search/decay_scoring.py | ✅ Complete |
| Golden Dataset Tests | tests/golden_set.yaml | ✅ Complete |

### Content Processing (P1 Fixes)
| Feature | File | Status |
|---------|------|--------|
| Apple Vision OCR | ocr/vision_ocr.py | ✅ Complete |
| VLM Image Captioning | multimodal/vlm_captioner.py | ✅ Complete |
| AST Code Chunking | chunking/code_chunker.py | ✅ Complete |
| Audio Topic Segmentation | audio/topic_segmentation.py | ✅ Complete |
| Spreadsheet Processing | processors/spreadsheet_processor.py | ✅ Complete |

### Knowledge & Memory (P1 Fixes)
| Feature | File | Status |
|---------|------|--------|
| Lightweight GraphRAG | graph/knowledge_graph.py | ✅ Complete |
| Episodic Memory | memory/episodic_memory.py | ✅ Complete |
| Zombie Reconciliation | sync/reconciliation.py | ✅ Complete |

### Observability & Safety
| Feature | File | Status |
|---------|------|--------|
| Debug Mode (MCP) | mcp_server/tools.py | ✅ Complete |
| Metacognition Tools | mcp_server/tools.py | ✅ Complete |
| >75% RAM Pause | utils/safe_processor.py | ✅ Complete |
| Query Prioritization | utils/safe_processor.py | ✅ Complete |
| Presidio PII Detection | utils/privacy_audit.py | ✅ Complete |
| .pkmignore Parser | utils/pkmignore.py | ✅ Complete |

---

## Critical Rules for Agents

1. **Read AGENT_INSTRUCTIONS.md first**
2. **Use SafeProcessor for all heavy workloads** - Now with >75% RAM auto-pause
3. **Run A/B tests before choosing local vs API**
4. **Stay under 40GB memory (leave 8GB for system)** - IngestionController enforces this
5. **Match data structures to architecture/data_schema.md exactly**
6. **Use CheckpointManager for long-running jobs**
7. **Run privacy audit before ingesting sensitive files** - Uses Presidio hybrid
8. **Use retry decorators for all API/network calls**
9. **Use parent-child chunking** - Small chunks for search, large for LLM context
10. **Apply cross-encoder re-ranking** - Always for top-k results before returning to user
11. **Respect .pkmignore** - Check before processing any file
12. **Run golden set tests after search changes** - Prevent retrieval regressions

---

## Context for Future Sessions

### User
- TJ, learning Python (course starts Feb 3, 2026)
- Prefers local-first for privacy
- Uses Obsidian for visual exploration
- M4 Max 48GB RAM, terabyte-scale files

### Approach
- Google Antigravity agents implement the code
- Agents have full read/write access to workspace
- Safety monitoring is mandatory

---

## Open Questions (Updated)

- [x] Chunking strategy (semantic vs fixed-size)? ✅ RESOLVED - Parent-Child (Small-to-Big) pattern
- [ ] Topic taxonomy (predefined vs AI-generated)?
- [ ] Obsidian vault structure?
- [ ] Priority file types for initial ingestion?
- [x] Backup/restore for vector database? ✅ RESOLVED - backup.py
- [x] Source file update handling? ✅ RESOLVED - incremental.py
- [x] How to handle orphaned chunks? ✅ RESOLVED - Zombie reconciliation
- [x] PII detection approach? ✅ RESOLVED - Presidio hybrid (NER + regex)

---

## External Resources

- LanceDB: https://lancedb.github.io/lancedb/
- FastMCP: https://github.com/jlowin/fastmcp
- Unstructured: https://unstructured.io/
- mlx-whisper: https://github.com/ml-explore/mlx-examples

---

*Last Updated: 2026-01-31 | Session Count: 3 | Status: P0+P1 BLIND SPOTS FIXED - 80+ files ready for Antigravity*
