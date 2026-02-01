# PKM System - Findings & Research

---

## Integration Findings (Feb 2026)

These findings emerged during actual integration work, not theoretical planning.

### 1. LLM Can't Reliably Produce Both JSON + Full Text in One Call
**Problem**: Single Ollama call asked to return JSON metadata AND full redacted document text. The model would truncate text, omit JSON fields, or produce malformed output.

**Solution**: Split-brain workflow in `intelligence.py`:
- Call 1: Structured JSON only (category, year, type, summary, filename, pii_observations)
- Call 2: Full redacted text with clear `===START===` / `===END===` delimiters

**Result**: 0/41 → 41/41 summaries (100% metadata quality).

### 2. LLM PII Detection Produces False Positives on Topic Words
**Problem**: LLM flagged 6/41 files as containing PII because they were HR guides mentioning "salary", "medical leave", "hospital" — topic words, not actual PII.

**Solution**: Three-layer PII detection — Presidio (pattern-based) is source of truth, LLM provides advisory observations only, custom dictionary for user-specific terms.

**Result**: 0 false positives on re-run.

### 3. No Need for Paid API (Gemini) — Local Ollama Sufficient
**Analysis**: Evaluated Gemini API free tier (2 RPM, 32K TPM). Ollama with qwen2.5:32b achieved 100% metadata quality across all 41 files. No quality benefit from external API, plus sending document text to Google is a privacy concern.

### 4. Embedding Model Mismatch
**Original plan**: nomic-embed-text-v1.5 (768d). **Actual**: all-MiniLM-L6-v2 (384d) was already wired when we started integration. Kept it since it's working well — migration can happen later if needed.

### 5. HyDE Expander Bug
**Bug**: `tools.py` passed the `HyDEResult` dataclass object as the search query string instead of extracting `.hypothetical_document`. This meant HyDE was silently broken — embedding a string representation of a Python object.

**Fix**: `hyde_result = self._hyde_expander.expand(query)` then use `hyde_result.hypothetical_document`.

### 6. RAG Verification Shows 95%+ Coverage
After ingesting 41 documents: avg char ratio 0.9533, word coverage 0.9535. Two "bad" entries (Approved_Doc.txt, CUI_Patient_Record.txt) are test artifacts from integration tests, not real failures.

### 7. Batch Processing Memory Safety
Batch processor pauses at 92% RAM, resumes at 88%. SafeProcessor (for background indexing) pauses at 75%, resumes at 65%. `gc.collect()` between files prevents extraction buffer accumulation. 41-file batch ran in ~19 minutes with no memory issues.

---

## Technology Decisions (Validated)

| Component | Planned | Actual | Status |
|-----------|---------|--------|--------|
| Vector DB | LanceDB | LanceDB | Working — 4702 child chunks, 52 parent chunks |
| Embeddings | nomic-embed-text-v1.5 (768d) | all-MiniLM-L6-v2 (384d) | Working — migration possible later |
| LLM | Gemini or local | Ollama qwen2.5:32b | Working — 100% metadata quality |
| MCP | FastMCP | FastMCP (stdio) | Working — Claude Desktop connected |
| PII | Presidio | Presidio + custom dictionary + LLM advisory | Working — 0 false positives |
| Reranker | cross-encoder | ms-marco-MiniLM-L-6-v2 | Working |
| HyDE | Ollama-backed | Ollama qwen2.5:32b | Wired (fixed bug) |
| Audio | mlx-whisper | mlx-whisper | Created, not wired |
| OCR | Vision.framework | Vision.framework | Created, not wired |

---

## Architecture Findings

### What Works Well
- **Parent-child chunking**: Small chunks (512 tokens) for precise search, parent chunks (2048 tokens) for LLM context
- **Hybrid search**: Vector + BM25 with RRF fusion provides good recall
- **Human-in-the-loop dashboard**: Critical for catching LLM errors and PII false positives
- **Two-phase staging**: Files appear as "processing" immediately, update to "pending" when AI finishes

### What Needed Fixing
- **MCP server**: Original scaffold used HTTP transport, Claude Desktop needs stdio
- **Intelligence pipeline**: Single LLM call was unreliable for complex output
- **PII detection**: LLM binary flag was the wrong abstraction — pattern matching is more reliable
- **Test suite**: Original tests didn't match actual module interfaces

---

## Performance Observations

| Operation | Measurement | Notes |
|-----------|-------------|-------|
| 41-file batch analysis | ~19 minutes | Ollama qwen2.5:32b, 2 calls per file |
| RAG indexing (41 files) | ~15 minutes | 4702 child chunks + 52 parent chunks |
| Single file processing | ~25-30 seconds | Extraction + AI analysis + staging |
| Dashboard load | <1 second | FastAPI + Jinja2 templates |
| Peak RAM during batch | ~85% | Paused once, resumed automatically |

---

*Research findings for PKM System | Last Updated: 2026-02-01*
