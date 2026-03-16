# P8 SP4: Redaction Editor UI — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-detection Keep/Redact toggles to the dashboard so users control exactly which PII findings get redacted at commit time.

**Architecture:** Extend the existing PII detection data model with `source`, `action`, `start_pos`, `end_pos` fields. Add an expandable redaction editor panel to each dashboard card. Modify the executor's `_redact_pii()` to respect per-detection overrides. Smart defaults: custom dict + SSN/CC → Redact, all other NER → Keep.

**Tech Stack:** Python 3.12+, FastAPI, Tailwind CSS, vanilla JavaScript

**Spec:** `docs/superpowers/specs/2026-03-16-p8-sp4-redaction-editor-spec.md`

**Context files to read before implementing:**
- `src/processor.py` — PII detection in `process_document()`, builds `pii_detections` list
- `src/executor.py` — `_redact_pii()` function, commit pipeline
- `src/ui/templates/dashboard.html` — card template, existing PII details section
- `src/utils/privacy_audit.py` — `PrivacyScanner`, match objects with `start_pos`, `end_pos`, `data_type`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/processor.py` | Modify | Add `source`, `action`, `start_pos`, `end_pos` to each pii_detection |
| `src/executor.py` | Modify | `_redact_pii()` respects per-detection action overrides |
| `src/ui/templates/dashboard.html` | Modify | Redaction editor toggle list UI |
| `tests/test_processor.py` | Modify | Test smart default actions on detections |
| `tests/test_executor.py` | Modify | Test selective redaction with overrides |

---

## Task 1: Extend PII Detection Data Model in Processor

**Files:**
- Modify: `src/processor.py`
- Modify: `tests/test_processor.py`

- [ ] **Step 1: Add helper function for smart defaults**

In `src/processor.py`, add a helper function before `process_document()`:

```python
_ALWAYS_REDACT_TYPES = {"ssn", "credit_card"}

def _default_redaction_action(match, custom_matches: list) -> str:
    """Determine default Keep/Redact action for a PII detection.

    Custom dictionary matches and universally-sensitive types (SSN, credit card)
    default to 'redact'. All other Presidio NER detections default to 'keep'.
    """
    if match in custom_matches:
        return "redact"
    if match.data_type.value.lower() in _ALWAYS_REDACT_TYPES:
        return "redact"
    return "keep"
```

- [ ] **Step 2: Extend pii_detections with new fields**

In `process_document()`, find the section that builds `pii_detections` (around line 139). Replace the current detection dict construction with:

```python
for m in high_confidence:
    pii_detections.append({
        "type": m.data_type.value,
        "confidence": round(m.confidence, 2),
        "context": m.context[:PII_CONTEXT_TRUNCATE],
        "source": "custom_dict" if m in custom_matches else "presidio",
        "action": _default_redaction_action(m, custom_matches),
        "start_pos": m.start_pos,
        "end_pos": m.end_pos,
    })
```

- [ ] **Step 3: Write tests for smart defaults**

Add to `tests/test_processor.py`:

```python
class TestRedactionDefaults:
    def test_custom_dict_defaults_to_redact(self):
        """Custom dictionary matches should default to 'redact'."""
        # Process a doc with custom PII terms
        # Verify pii_detections have action="redact" for custom matches

    def test_ssn_defaults_to_redact(self):
        """SSN patterns should default to 'redact' regardless of source."""
        # Verify SSN detection has action="redact"

    def test_ner_name_defaults_to_keep(self):
        """Generic NER name detections should default to 'keep'."""
        # Verify NAME detection has action="keep"

    def test_detection_has_source_field(self):
        """Each detection should have source='custom_dict' or 'presidio'."""
        # Verify source field exists

    def test_detection_has_position_fields(self):
        """Each detection should have start_pos and end_pos."""
        # Verify position fields exist
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_processor.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/processor.py tests/test_processor.py
git commit -m "feat: extend PII detections with source, action, and position fields"
```

---

## Task 2: Selective Redaction in Executor

**Files:**
- Modify: `src/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Modify _redact_pii() to accept overrides**

Update `_redact_pii()` signature to accept optional detection overrides:

```python
def _redact_pii(text: str, file_name: str, detection_overrides: list[dict] | None = None) -> str:
```

When `detection_overrides` is provided:
1. Build a set of (start_pos, end_pos, type) tuples marked as "keep"
2. After running Presidio + custom dict (same as now), filter the matches:
   - If a match overlaps with a "keep" override, skip it
   - If a match overlaps with a "redact" override, keep it in the redaction list
   - Matches not in any override follow the existing behavior (redact all)

```python
# Build keep set from overrides
keep_ranges = set()
if detection_overrides:
    for det in detection_overrides:
        if det.get("action") == "keep":
            keep_ranges.add((det.get("start_pos", -1), det.get("end_pos", -1), det.get("type", "")))

# In the match filtering loop, skip matches that overlap with keep ranges:
for match in filtered:
    match_key = (match.start_pos, match.end_pos, match.data_type.value)
    if match_key in keep_ranges:
        continue  # User chose to keep this detection
    # ... apply redaction ...
```

- [ ] **Step 2: Update executor to pass overrides**

In `execute_approved_item()`, where `_redact_pii()` is called (~line 235), pass the detection overrides from the staging manifest:

```python
if is_sensitive:
    detection_overrides = item.get("metadata", {}).get("pii_detections", [])
    export_text = _redact_pii(export_text, current_path.name, detection_overrides=detection_overrides)
```

- [ ] **Step 3: Write tests**

Add to `tests/test_executor.py`:

```python
class TestSelectiveRedaction:
    def test_redact_pii_respects_keep_override(self):
        """Detections marked 'keep' should not be redacted."""
        # Create text with known PII
        # Pass overrides with action="keep" for one detection
        # Verify that detection remains in output

    def test_redact_pii_respects_redact_override(self):
        """Detections marked 'redact' should be replaced."""
        # Pass overrides with action="redact"
        # Verify detection is replaced with [REDACTED-TYPE]

    def test_redact_pii_no_overrides_redacts_all(self):
        """Without overrides, all detections are redacted (legacy behavior)."""
        # Call without detection_overrides
        # Verify all PII is redacted

    def test_redact_pii_mixed_overrides(self):
        """Mix of keep and redact overrides applied correctly."""
        # Some keep, some redact
        # Verify each applied correctly
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_executor.py --no-cov -v --tb=short`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/executor.py tests/test_executor.py
git commit -m "feat: selective PII redaction — _redact_pii() respects per-detection overrides"
```

---

## Task 3: Dashboard Redaction Editor UI

**Files:**
- Modify: `src/ui/templates/dashboard.html`

- [ ] **Step 1: Add "Edit Redactions" button to card template**

Find the existing PII details section in the card template (search for `renderPiiDetails` or the PII detections display). After it, add:

```html
<button onclick="toggleRedactionEditor('${id}')"
    id="redaction-btn-${id}"
    class="${pii_detections.length > 0 ? '' : 'hidden'} text-blue-400 hover:text-blue-300 text-sm mt-2">
    Edit Redactions (${pii_detections.length} detections)
</button>
<div id="redaction-editor-${id}" class="hidden mt-3 space-y-2 border-t border-gray-700 pt-3">
</div>
```

Where `pii_detections` is extracted from `item.metadata.pii_detections`.

- [ ] **Step 2: Add toggle/editor JavaScript**

```javascript
function toggleRedactionEditor(itemId) {
    const editor = document.getElementById('redaction-editor-' + itemId);
    if (editor.classList.contains('hidden')) {
        editor.classList.remove('hidden');
        renderRedactionEditor(itemId);
    } else {
        editor.classList.add('hidden');
    }
}

function renderRedactionEditor(itemId) {
    const editor = document.getElementById('redaction-editor-' + itemId);
    editor.textContent = '';
    // Get item data from the queue
    const item = queueData?.[itemId];
    const detections = item?.metadata?.pii_detections || [];

    for (let i = 0; i < detections.length; i++) {
        const det = detections[i];
        const row = document.createElement('div');
        row.className = 'flex items-center gap-2 py-1.5 px-2 rounded bg-gray-900';

        // Type badge
        const badge = document.createElement('span');
        const isRedact = det.action === 'redact';
        badge.className = 'text-xs px-1.5 py-0.5 rounded font-mono ' +
            (isRedact ? 'bg-red-900 text-red-200' : 'bg-gray-700 text-gray-300');
        badge.textContent = det.type;
        row.appendChild(badge);

        // Confidence
        const conf = document.createElement('span');
        conf.className = 'text-xs text-gray-500 w-10';
        conf.textContent = Math.round(det.confidence * 100) + '%';
        row.appendChild(conf);

        // Source
        const src = document.createElement('span');
        src.className = 'text-xs text-gray-500 w-20';
        src.textContent = det.source === 'custom_dict' ? 'Custom Dict' : 'Presidio';
        row.appendChild(src);

        // Context
        const ctx = document.createElement('span');
        ctx.className = 'text-xs text-gray-400 flex-1 truncate';
        ctx.textContent = det.context || '';
        row.appendChild(ctx);

        // Toggle button
        const toggle = document.createElement('button');
        toggle.className = isRedact
            ? 'text-xs px-3 py-1 rounded bg-red-800 text-red-200 hover:bg-red-700'
            : 'text-xs px-3 py-1 rounded bg-green-800 text-green-200 hover:bg-green-700';
        toggle.textContent = isRedact ? 'Redact' : 'Keep';
        toggle.onclick = function() {
            det.action = det.action === 'redact' ? 'keep' : 'redact';
            saveRedactionOverride(itemId, detections);
            renderRedactionEditor(itemId);  // Re-render
        };
        row.appendChild(toggle);

        editor.appendChild(row);
    }
}

async function saveRedactionOverride(itemId, detections) {
    try {
        await fetch('/api/update/' + itemId, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                metadata: { pii_detections: detections }
            })
        });
    } catch (e) {
        console.error('Failed to save redaction override:', e);
    }
}
```

All user-provided data (type, context, source) rendered via `textContent` — no HTML injection risk.

- [ ] **Step 3: Store queueData for editor access**

The card rendering function fetches queue data from `/api/queue`. Store it in a global variable so the redaction editor can access detection data:

```javascript
let queueData = {};
// In the queue loading function, after parsing response:
queueData = data.items || data;
```

- [ ] **Step 4: Test manually**

Start server, process a file with PII, verify:
1. "Edit Redactions" button appears on sensitive cards
2. Expanding shows detection list with toggles
3. Toggling changes red/green state
4. Changes persist after page refresh

- [ ] **Step 5: Commit**

```bash
git add src/ui/templates/dashboard.html
git commit -m "feat: redaction editor UI — per-detection Keep/Redact toggles on dashboard cards"
```

---

## Verification

After all tasks complete:

- [ ] **Run full test suite**

Run: `pytest --no-cov --tb=short -q`
Expected: 678+ pass, no regressions.

- [ ] **Manual verification**

1. Process a sensitive document (one with custom PII terms)
2. Expand "Edit Redactions" — verify custom dict matches show as Redact (red)
3. Verify NER names/emails show as Keep (green)
4. Toggle a "Redact" detection to "Keep"
5. Commit the file
6. Check the exported text (Obsidian vault or RAG search) — verify the toggled detection was NOT redacted
7. Check that other "Redact" detections WERE redacted

---

## Summary

| Task | What | Files | Effort |
|------|------|-------|--------|
| 1 | PII detection data model + smart defaults | processor.py, tests | ~40 lines |
| 2 | Selective redaction in executor | executor.py, tests | ~30 lines |
| 3 | Dashboard redaction editor UI | dashboard.html | ~80 lines |

**Total: 3 tasks, ~150 lines. Smallest SP in P8.**
