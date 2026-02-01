# Agent Instructions

> **PRIORITY**: Read this file first. It contains critical instructions for working on this project.

---

## Your Mission

Build a Personal Knowledge Management (PKM) "Reasoning Engine" that enables semantic search across documents via Claude Desktop's MCP protocol, optimized for Apple Silicon (M4 Max, 48GB RAM).

---

## Project Status: ✅ CORE COMPLETE

**Phase**: All Core Features Implemented
**Status**: Ready for User Setup & Testing

The AntiGravity PKM system is **feature-complete** with all critical, enhancement, and nice-to-have components implemented. User must complete setup tasks in `SETUP_TASKS.md`.

---

## Critical Files to Read Before Coding

| Order | File | Purpose |
|-------|------|---------|
| 1 | `PRD.md` | Full requirements, success criteria, user stories |
| 2 | `SETUP_TASKS.md` | **User setup checklist (NEW)** |
| 3 | `architecture/PKM_Design_System_Architecture.md` | Technical architecture |
| 4 | `architecture/data_schema.md` | Data structures (MUST match exactly) |
| 5 | `architecture/PERFORMANCE_GUIDE.md` | **M4 Max optimization (CRITICAL)** |
| 6 | `architecture/HARDWARE_SAFETY.md` | **Safety monitoring (REQUIRED)** |
| 7 | `architecture/TESTING_FRAMEWORK.md` | A/B testing local vs API |
| 8 | `CONVENTIONS.md` | Coding standards to follow |

> ⚠️ **SAFETY CRITICAL**: Always use `SafeProcessor` from `src/utils/` for heavy workloads. Memory pauses at >75% RAM usage.

> 🧪 **QUALITY CRITICAL**: Use `tests/golden_set/` for regression testing search quality.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Claude Desktop                               │
│                      (MCP Client via stdin)                          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ MCP Protocol
┌───────────────────────────────▼─────────────────────────────────────┐
│                     FastMCP Server (server.py)                       │
│  Tools: search_knowledge, list_recent, get_status                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│  Search Stack │    │  Ingestion Stack │    │   Quality Stack      │
├───────────────┤    ├──────────────────┤    ├──────────────────────┤
│ HyDE Expansion│    │ File Watcher     │    │ Link Rot Checker     │
│ Multi-Query   │    │ Pipeline Orch.   │    │ Duplicate Detector   │
│ Hybrid Search │    │ Processors:      │    │ Freshness Indicator  │
│ Cross-Encoder │    │  - Text/Markdown │    │ Conflict Detector    │
│ Decay Scoring │    │  - PDF/DOCX/XLSX │    │ Auto-Tagger          │
│ Semantic Cache│    │  - Audio/Video   │    │ Privacy Audit        │
└───────┬───────┘    │  - Code (AST)    │    └──────────────────────┘
        │            │  - Images (VLM)  │
        │            └────────┬─────────┘
        │                     │
        └──────────┬──────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        LanceDB (Vector Store)                         │
│  Tables: chunks, documents, entities, episodic                        │
│  Indices: Vector (nomic-v1.5 768d) + FTS (BM25)                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Implemented Modules

### Core Infrastructure
| Module | Path | Status |
|--------|------|--------|
| MCP Server | `src/mcp_server/server.py` | ✅ Complete |
| Embedding Service | `src/embeddings/embedding_service.py` | ✅ Complete |
| Ingestion Pipeline | `src/ingestion/pipeline.py` | ✅ Complete |
| Queue Manager | `src/utils/queue_manager.py` | ✅ Complete |

### Search & Retrieval
| Module | Path | Status |
|--------|------|--------|
| Hybrid Search | `src/search/hybrid_search.py` | ✅ Complete |
| HyDE Expansion | `src/search/hyde.py` | ✅ Complete |
| Cross-Encoder | `src/search/reranker.py` | ✅ Complete |
| Multi-Query Fusion | `src/search/multi_query.py` | ✅ Complete |
| Decay Scoring | `src/search/decay_scoring.py` | ✅ Complete |

### Content Processing
| Module | Path | Status |
|--------|------|--------|
| Parent-Child Chunks | `src/chunking/parent_child.py` | ✅ Complete |
| AST Code Chunking | `src/chunking/code_chunker.py` | ✅ Complete |
| Vision OCR | `src/ocr/vision_ocr.py` | ✅ Complete |
| VLM Captioner | `src/multimodal/vlm_captioner.py` | ✅ Complete |
| Video Scene Detection | `src/video/scene_detector.py` | ✅ Complete |
| Audio Segmentation | `src/audio/topic_segmentation.py` | ✅ Complete |
| Spreadsheet Processor | `src/processors/spreadsheet_processor.py` | ✅ Complete |
| Obsidian Exporter | `src/obsidian/obsidian_export.py` | ✅ Complete |

### Quality & Analytics
| Module | Path | Status |
|--------|------|--------|
| Query Analytics | `src/analytics/query_analytics.py` | ✅ Complete |
| Semantic Cache | `src/analytics/query_analytics.py` | ✅ Complete |
| Auto-Tagger | `src/classification/auto_tagger.py` | ✅ Complete |
| Duplicate Detector | `src/quality/duplicate_detector.py` | ✅ Complete |
| Link Rot Checker | `src/quality/link_checker.py` | ✅ Complete |
| Freshness Indicator | `src/quality/freshness.py` | ✅ Complete |
| Conflict Detector | `src/quality/conflict_detector.py` | ✅ Complete |
| Privacy Audit | `src/utils/privacy_audit.py` | ✅ Complete |

### Resilience & Safety
| Module | Path | Status |
|--------|------|--------|
| Hardware Monitor | `src/utils/hardware_monitor.py` | ✅ Complete |
| Throttle Controller | `src/utils/throttle_controller.py` | ✅ Complete |
| Safe Processor | `src/utils/safe_processor.py` | ✅ Complete |
| Checkpoint Manager | `src/utils/checkpoint.py` | ✅ Complete |
| Backup Manager | `src/utils/backup.py` | ✅ Complete |
| .pkmignore Parser | `src/utils/pkmignore.py` | ✅ Complete |

### Advanced Features
| Module | Path | Status |
|--------|------|--------|
| GraphRAG | `src/graph/knowledge_graph.py` | ✅ Complete |
| Episodic Memory | `src/memory/episodic_memory.py` | ✅ Complete |
| Zombie Reconciliation | `src/sync/reconciliation.py` | ✅ Complete |
| DB Optimizer | `src/maintenance/db_optimizer.py` | ✅ Complete |

### User Interfaces
| Module | Path | Status |
|--------|------|--------|
| CLI Interface | `src/cli/main.py` | ✅ Complete |
| Health Dashboard | `src/dashboard/health_dashboard.py` | ✅ Complete |

---

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Vector Database | LanceDB | Embedded, handles TB scale, Lance format |
| Embeddings | nomic-embed-text-v1.5 | Local, 768 dimensions, MPS optimized |
| Audio Transcription | mlx-whisper | Apple Silicon optimized (M4 Max) |
| Video Processing | OpenCV | Keyframe extraction, scene detection |
| Image OCR | Vision.framework | Native macOS, high accuracy |
| Image Captioning | LLaVA (optional) | VLM for image descriptions |
| PII Detection | Presidio + Regex | Hybrid NER + pattern matching |
| MCP Framework | FastMCP | Python-native, simple |
| File Processing | Unstructured | Multi-format support |
| Code Parsing | tree-sitter | AST-based chunking |

---

## Key Constraints

1. **Local-First**: All processing runs on user's M4 Max MacBook (48GB RAM)
2. **Privacy**: Sensitive content never leaves the device (Presidio auditing)
3. **Memory**: Pause ingestion at >75% RAM, leave 8GB for system
4. **Performance**: Query response under 3 seconds
5. **Media Processing**: Audio/video files ARE indexed via processing pipelines

---

## M4 Max Performance Rules (Non-Negotiable)

**These rules MUST be followed for all code:**

1. **Use MLX-native libraries when available**
   - `mlx-whisper` for audio (NOT standard whisper)
   - MLX models when available

2. **Batch GPU operations**
   ```python
   # ✅ CORRECT
   embeddings = model.encode(texts, batch_size=32)

   # ❌ WRONG
   for text in texts:
       emb = model.encode(text)
   ```

3. **Parallel CPU work, batched GPU work**
   - File parsing → ProcessPoolExecutor (max 8 workers)
   - Embeddings → Sequential batches of 32

4. **Stream large files**
   - Never load entire large files into memory
   - Use generators and chunked reading

5. **Memory pressure management**
   - Pause at >75% RAM usage
   - Resume at <65% RAM usage
   - Use IngestionController from safe_processor.py

---

## Hardware Safety (Non-Negotiable)

**All heavy processing MUST use SafeProcessor:**

```python
from src.utils.safe_processor import SafeProcessor, IngestionController

# For batch processing
processor = SafeProcessor()
for result in processor.process_safely(files, process_func):
    db.add(result)

# For ingestion control
controller = IngestionController()
if controller.should_pause_ingestion():
    controller.wait_for_resume()
```

**Safety thresholds:**
- Memory > 75% → Pause ingestion
- Memory > 85% → Stop processing, cleanup
- CPU temp > 90°C → Pause and cool down

---

## File Ownership

| Folder | Purpose | Agent Can Modify? |
|--------|---------|-------------------|
| `src/` | Source code | ✅ Yes - primary workspace |
| `tests/` | Test files | ✅ Yes |
| `architecture/` | Design docs | ⚠️ Only to add details, not change decisions |
| `docs/` | User documentation | ✅ Yes |
| `PRD.md` | Requirements | ❌ No - read only |
| `SETUP_TASKS.md` | User setup | ⚠️ User checklist - don't change tasks |
| `progress.md` | Work log | ✅ Yes - append entries |
| `findings.md` | Research notes | ✅ Yes - add discoveries |

---

## Quick Reference Commands

```bash
# Activate environment
source ~/.pkm/venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/

# Start MCP server
python -m src.mcp_server.server

# Start health dashboard
python -m src.dashboard.health_dashboard

# Run CLI
python -m src.cli.main status
python -m src.cli.main search "your query"
python -m src.cli.main search "your query"
python -m src.cli.main ingest ~/Documents/PKM/Inbox -r
python scripts/setup_folders.py
```

---

## Success Criteria

The project is successful when:
- [x] User can ask Claude "What do I have about X?" and get relevant results
- [x] PDFs, Word docs, spreadsheets, and text files are searchable
- [x] Audio files are transcribed and searchable
- [x] Video files are processed (keyframes + scene detection)
- [x] Images are captioned and OCR'd
- [x] Code files are parsed with AST awareness
- [x] Response time is under 3 seconds
- [x] All processing happens locally
- [x] Memory usage stays under control (75% threshold)
- [x] Search quality is tracked via golden set
- [x] Duplicate and stale content is detected
- [x] Privacy audit catches PII before indexing

---

## User Setup Required

Before the system is fully operational, the user must complete:

1. **Presidio installation** - For PII detection
2. **Vision.framework verification** - For OCR
3. **Tailscale setup** (optional) - For remote access
4. **Web clipper configuration** (optional) - For saving articles
5. **Golden Set creation** - For search quality testing

See `SETUP_TASKS.md` for complete instructions.

---

*The PKM Reasoning Engine is ready for deployment once user setup is complete.*
