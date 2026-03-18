# Qwen3:32b Model Validation Plan

> **Status: COMPLETE** — qwen3:32b is the default Ollama model. `<think>` tag stripping implemented in OllamaProvider.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely validate qwen3:32b as a drop-in replacement for qwen2.5:32b in CoreRag's LLM pipeline, then switch the default model.

**Architecture:** Centralize `<think>` tag stripping in both Ollama provider classes (`OllamaProvider` in `src/llm/provider.py` and `OllamaLLM` in `src/utils/ollama_llm.py`) so ALL downstream callers are protected — intelligence.py, context_generator.py, summarizer.py, answer_synthesis.py, hyde.py, rag_evaluator.py, knowledge_graph.py, episodic_memory.py, and topic_segmentation.py. Update the default model from `qwen2.5:32b` to `qwen3:32b`. All changes are behind the existing `OLLAMA_MODEL` env var, so rollback = one env var change.

**Tech Stack:** Ollama (qwen3:32b Q4_K_M), pytest, httpx

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/llm/provider.py` | Modify | Add `_strip_thinking_tags()` post-processing in `OllamaProvider.generate()`, update `_PROVIDER_DEFAULTS["ollama"]` to `qwen3:32b` |
| `src/utils/ollama_llm.py` | Modify | Add same `_strip_thinking_tags()` post-processing in `OllamaLLM.generate()` |
| `tests/test_llm_provider.py` | Modify | Add thinking tag stripping tests, update fixture default model |
| `tests/test_ollama_llm.py` | Create | Tests for OllamaLLM thinking tag stripping |
| `.env.example` | Modify | Update example OLLAMA_MODEL comment |

**Call sites protected by centralizing in the two Ollama classes (10+ callers, zero individual patches):**

| Caller | File | Via |
|--------|------|-----|
| `analyze_document()` | `src/intelligence.py:80` | `OllamaProvider` |
| `suggest_folder_structure()` | `src/intelligence.py:185` | `OllamaProvider` |
| `generate_context()` | `src/chunking/context_generator.py:75` | `OllamaProvider` |
| `generate_summary()` | `src/chunking/summarizer.py:51` | `OllamaProvider` |
| `synthesize_answer()` | `src/search/answer_synthesis.py:187,213` | `OllamaProvider` |
| `expand_async()` | `src/search/hyde.py:421` | `OllamaProvider` |
| `evaluate()` | `src/quality/rag_evaluator.py:91,123,135` | `OllamaProvider` |
| Entity extraction | `src/graph/knowledge_graph.py:120` | `OllamaLLM` |
| Fact extraction | `src/memory/episodic_memory.py:151` | `OllamaLLM` |
| Topic segmentation | `src/audio/topic_segmentation.py:128` | `OllamaLLM` |

---

## Chunk 1: Thinking Tag Resilience + Model Default

### Task 1: Add Thinking Tag Stripping to OllamaProvider

**Files:**
- Modify: `src/llm/provider.py:98-125` (`OllamaProvider` class)
- Test: `tests/test_llm_provider.py`

- [ ] **Step 1: Write failing tests for thinking tag stripping**

In `tests/test_llm_provider.py`, add to the existing `TestOllamaProvider` class:

```python
async def test_generate_strips_thinking_tags(self, config):
    """OllamaProvider must strip <think> blocks from qwen3 output."""
    provider = OllamaProvider(config)
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": '<think>\nLet me analyze...\n</think>\n{"category": "Work"}'
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await provider.generate("System", "User prompt")

    assert "<think>" not in result
    assert '{"category": "Work"}' in result

async def test_generate_handles_empty_think_block(self, config):
    provider = OllamaProvider(config)
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "<think></think>clean output"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await provider.generate("", "prompt")

    assert result == "clean output"

async def test_generate_no_think_tags_passes_through(self, config):
    """Output without <think> tags is unchanged."""
    provider = OllamaProvider(config)
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "Hello from Ollama"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await provider.generate("System", "User prompt")

    assert result == "Hello from Ollama"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_provider.py::TestOllamaProvider::test_generate_strips_thinking_tags -v`
Expected: FAIL — `<think>` tags still in output

- [ ] **Step 3: Add `_strip_thinking_tags` to provider.py and wire into OllamaProvider**

In `src/llm/provider.py`, add the utility function at module level (before the `OllamaProvider` class, around line 96):

```python
def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from qwen3-style reasoning output.

    No-op for models that don't emit thinking tags (e.g., qwen2.5).
    """
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
```

Then in `OllamaProvider.generate()`, change line 125:

```python
# Before:
            return resp.json().get("response", "")

# After:
            raw = resp.json().get("response", "")
            return _strip_thinking_tags(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_provider.py::TestOllamaProvider -v`
Expected: All tests PASS including the 3 new ones and the existing `test_generate_returns_response_text` and `test_generate_combines_system_and_user`

- [ ] **Step 5: Commit**

```bash
git add src/llm/provider.py tests/test_llm_provider.py
git commit -m "feat: add thinking tag stripping to OllamaProvider for qwen3 compat"
```

---

### Task 2: Add Thinking Tag Stripping to OllamaLLM

**Files:**
- Modify: `src/utils/ollama_llm.py:29-44`
- Create: `tests/test_ollama_llm.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ollama_llm.py`:

```python
"""Tests for OllamaLLM thinking tag stripping."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.ollama_llm import OllamaLLM


class TestOllamaLLM:
    @pytest.fixture
    def llm(self):
        with patch("src.utils.ollama_llm.OllamaLLM.__init__", return_value=None):
            obj = OllamaLLM.__new__(OllamaLLM)
            obj.model = "qwen3:32b"
            obj.host = "http://localhost:11434"
            obj.timeout = 60.0
            return obj

    async def test_generate_strips_thinking_tags(self, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '<think>\nanalyzing...\n</think>\n{"entities": []}'
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await llm.generate("Extract entities from: test doc")

        assert "<think>" not in result
        assert '{"entities": []}' in result

    async def test_generate_passthrough_without_tags(self, llm):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "clean response"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await llm.generate("prompt")

        assert result == "clean response"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ollama_llm.py::TestOllamaLLM::test_generate_strips_thinking_tags -v`
Expected: FAIL — `<think>` tags still in output

- [ ] **Step 3: Add stripping to OllamaLLM.generate()**

In `src/utils/ollama_llm.py`, add `import re` at top, then change line 44:

```python
# Before:
            return resp.json().get("response", "")

# After:
            raw = resp.json().get("response", "")
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ollama_llm.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest -x`
Expected: All 603+ tests pass

- [ ] **Step 6: Commit**

```bash
git add src/utils/ollama_llm.py tests/test_ollama_llm.py
git commit -m "feat: add thinking tag stripping to OllamaLLM for qwen3 compat"
```

---

### Task 3: Update Default Ollama Model

**Files:**
- Modify: `src/llm/provider.py:34`
- Modify: `tests/test_llm_provider.py:29`
- Modify: `.env.example`

- [ ] **Step 1: Pull qwen3:32b via Ollama**

Run: `ollama pull qwen3:32b`
Expected: Downloads ~20GB Q4_K_M quantization. Verify: `ollama list | grep qwen3`

Keep qwen2.5:32b installed for rollback. Both fit in 48GB.

- [ ] **Step 2: Update provider default**

In `src/llm/provider.py` line 34:

```python
# Before:
    "ollama": "qwen2.5:32b",

# After:
    "ollama": "qwen3:32b",
```

- [ ] **Step 3: Update test fixture**

In `tests/test_llm_provider.py` line 29:

```python
# Before:
        return LLMConfig(provider="ollama", model="qwen2.5:32b")

# After:
        return LLMConfig(provider="ollama", model="qwen3:32b")
```

- [ ] **Step 4: Update .env.example**

Change the OLLAMA_MODEL line:

```bash
OLLAMA_MODEL=qwen3:32b                  # Ollama model for analysis (default)
```

- [ ] **Step 5: Run full test suite**

Run: `pytest -x`
Expected: All tests pass. No test depends on the model name string for correctness.

- [ ] **Step 6: Commit**

```bash
git add src/llm/provider.py tests/test_llm_provider.py .env.example
git commit -m "feat: upgrade default Ollama model from qwen2.5:32b to qwen3:32b"
```

---

## Chunk 2: Live Validation

Manual validation steps using real documents. These confirm the new model produces equivalent or better output before updating documentation and the model registry.

### Task 4: Validate Classification Pipeline (Manual)

**Prerequisites:** Ollama running, qwen3:32b pulled, `.env` has `OLLAMA_MODEL=qwen3:32b` (or unset to use the new default)

- [ ] **Step 1: Verify Ollama serves qwen3:32b with clean JSON**

```bash
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:32b","prompt":"Return only valid JSON, nothing else: {\"test\": true}","stream":false,"options":{"temperature":0.1}}' \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('response','')[:500])"
```

Expected: `{"test": true}` — possibly with `<think>` wrapper pre-stripping (stripping is in the provider, not at the curl level, so raw output may contain tags). This confirms the model is loaded and responding.

- [ ] **Step 2: Run classification on a sample document**

```bash
source venv/bin/activate
python3 -c "
import asyncio
from src.intelligence import analyze_document

text = '''
SPHR Study Guide - Chapter 4: Employee Relations
This chapter covers workplace investigations, dispute resolution, and employee engagement strategies.
Key topics: progressive discipline, alternative dispute resolution, employee surveys.
Published: 2024 by HRCI.
'''

async def main():
    meta, _ = await analyze_document(text)
    import json
    print(json.dumps(meta, indent=2))

asyncio.run(main())
"
```

Expected:
- `category`: "Education" or "Work"
- `year`: "2024"
- `type`: "Guide" or "Manual"
- `pii_observations`: "" (no PII)
- **No JSON parse errors** (thinking tags stripped by OllamaProvider)

- [ ] **Step 3: Compare with qwen2.5 baseline**

```bash
OLLAMA_MODEL=qwen2.5:32b python3 -c "
import asyncio
from src.llm.provider import reset_default_provider
reset_default_provider()
from src.intelligence import analyze_document

text = '''
SPHR Study Guide - Chapter 4: Employee Relations
This chapter covers workplace investigations, dispute resolution, and employee engagement strategies.
Key topics: progressive discipline, alternative dispute resolution, employee surveys.
Published: 2024 by HRCI.
'''

async def main():
    meta, _ = await analyze_document(text)
    import json
    print(json.dumps(meta, indent=2))

asyncio.run(main())
"
```

Compare outputs. Should agree on category, year, type. Minor summary/filename differences OK.

- [ ] **Step 4: Test JSON robustness with a PII-heavy document**

```bash
source venv/bin/activate
python3 -c "
import asyncio
from src.intelligence import analyze_document

text = '''
From: Jane Smith <jsmith@company.com>
To: HR Department
Date: March 15, 2025
Subject: Annual Performance Review - John Doe (Employee ID: 12345)

This is to confirm that the annual performance review for John Doe has been completed.
Rating: Exceeds Expectations. Recommended for promotion to Senior Engineer.
Current salary: \$125,000. Recommended increase: 8%.
'''

async def main():
    meta, _ = await analyze_document(text)
    import json
    print(json.dumps(meta, indent=2))
    print(f'\nJSON parsing: OK')
    print(f'PII advisory: {bool(meta.get(\"pii_observations\"))}')

asyncio.run(main())
"
```

Expected: Valid JSON, category "Work", year "2025", pii_observations non-empty.

- [ ] **Step 5: Test contextual retrieval prefix generation**

This validates the enrichment backfill pipeline (7,228 pending prefixes):

```bash
source venv/bin/activate
python3 -c "
import asyncio
from src.chunking.context_generator import ContextGenerator

gen = ContextGenerator()
doc = 'This is a comprehensive guide to Python testing with pytest. It covers fixtures, parameterization, mocking, and test organization.'
chunk = 'Fixtures provide a way to set up test preconditions. Use @pytest.fixture decorator.'

async def main():
    prefix = await gen.generate_context(doc, chunk)
    print(f'Prefix ({len(prefix)} chars):')
    print(prefix)
    has_think = '<think>' in prefix
    print(f'\nThinking tags leaked: {has_think}')
    if has_think:
        print('ERROR: Tags should have been stripped by OllamaProvider')
    elif prefix and len(prefix) > 10:
        print('Context generation: OK')

asyncio.run(main())
"
```

Expected: Clean 2-3 sentence prefix, no `<think>` tags (stripped by OllamaProvider before reaching ContextGenerator).

- [ ] **Step 6: Test knowledge graph entity extraction (OllamaLLM path)**

```bash
source venv/bin/activate
python3 -c "
import asyncio
from src.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
text = 'Python is a programming language created by Guido van Rossum at CWI in the Netherlands.'

async def main():
    entities = await kg.extract_entities(text)
    print(f'Entities found: {len(entities)}')
    for e in entities[:5]:
        print(f'  {e}')
    raw_check = str(entities)
    if '<think>' in raw_check:
        print('ERROR: Thinking tags leaked through OllamaLLM')
    else:
        print('Entity extraction: OK')

asyncio.run(main())
"
```

Expected: Entities extracted cleanly. No `<think>` tags in results.

- [ ] **Step 7: Decision point**

| Outcome | Action |
|---------|--------|
| All outputs valid, quality >= qwen2.5 | Proceed to Task 5 (update docs) |
| JSON parsing fails despite stripping | Check Ollama version; try `/no_think` prompt prefix |
| Classification quality worse | Roll back: `OLLAMA_MODEL=qwen2.5:32b` in `.env` |
| `<think>` tags leak through | Bug in stripping — debug the provider-level regex |

---

### Task 5: Update Documentation and Registry

**Files:**
- Modify: `CLAUDE.md` (Local Models table, Intelligence Provider section)
- Modify: `_DEV/TECH_DEBT.md` (TD-001 note)
- Modify: `~/Tech_Projects/_HQ/config/local_model_registry.yaml`

- [ ] **Step 1: Update CLAUDE.md**

In the Local Models table, change:

```markdown
| qwen3:32b | Ollama | Primary LLM | Classification, summarization, PII advisory, folder suggestions |
```

In the Intelligence Provider section, change:

```markdown
- **Ollama** (default): uses `qwen3:32b` locally at `localhost:11434`. Fully private.
```

- [ ] **Step 2: Update TD-001 in TECH_DEBT.md**

Add note: "Validated qwen3:32b on [date]. Backfill can use `--provider ollama` with qwen3 for improved context prefix quality."

- [ ] **Step 3: Update local model registry**

In `~/Tech_Projects/_HQ/config/local_model_registry.yaml`, update CoreRag's entry from `qwen2.5:32b` to `qwen3:32b`.

- [ ] **Step 4: Commit**

```bash
git add .env.example
git commit -m "docs: update model references for qwen3:32b upgrade"
```

Note: CLAUDE.md and TECH_DEBT.md are gitignored — no git add needed for those.

---

## Rollback Procedure

If qwen3:32b causes issues after deployment:

1. **Immediate:** Set `OLLAMA_MODEL=qwen2.5:32b` in `.env` — no code changes needed
2. **The `_strip_thinking_tags()` code is harmless with qwen2.5** — it's a no-op on clean output, so leave it in place
3. **Optional:** Revert `_PROVIDER_DEFAULTS["ollama"]` in `provider.py` to match

The env var override always takes priority over `_PROVIDER_DEFAULTS`, so the code default only affects fresh installs without a `.env` file.
