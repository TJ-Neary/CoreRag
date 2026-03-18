# P8 Sub-project 4: Redaction Editor UI — Full Spec

**Date:** 2026-03-16
**Author:** Claude Opus 4.6 (Session 32)
**Status:** Complete — implemented (Session 32, P8 SP4)
**North Star:** Per-detection control over what gets redacted — your PII is protected by default, other people's data stays readable.

---

## 1. Redaction Editor UI

**What:** An expandable "Edit Redactions" section on each dashboard card showing every PII detection with a Keep/Redact toggle.

**Location:** Below the existing PII details summary on sensitive file cards. Collapsed by default — click "Edit Redactions (N detections)" button to expand.

**Each detection row displays:**
- **PII type badge** — colored pill (e.g., "SSN" in red, "NAME" in gray, "CUSTOM" in orange)
- **Confidence** — percentage (e.g., "95%")
- **Context snippet** — truncated text showing where the detection was found (already in `pii_detections`)
- **Source indicator** — "Custom Dict" or "Presidio NER" (so user knows why it was flagged)
- **Keep/Redact toggle** — pill-style toggle. Red = Redact (will be replaced with `[REDACTED-TYPE]`). Green = Keep (left in text as-is).

**Smart defaults (set during analysis, overridable by user):**

| Detection Source | Default Action | Reason |
|-----------------|---------------|--------|
| Custom dictionary match | Redact | YOUR PII — always protect by default |
| SSN pattern | Redact | Universally sensitive |
| Credit card pattern | Redact | Universally sensitive |
| Presidio NER: names | Keep | Other people's names are useful data |
| Presidio NER: emails | Keep | Publisher/author emails are useful |
| Presidio NER: phones | Keep | Contact info from documents |
| Presidio NER: addresses | Keep | Business addresses are useful |
| Presidio NER: dates | Keep | Document dates are useful |
| Presidio NER: organizations | Keep | Company names are useful |

**User can override any toggle.** Toggling a detection saves immediately via the existing `/api/update/{item_id}` endpoint.

---

## 2. Data Model Changes

### pii_detections list (in staging manifest)

Currently each detection is:
```json
{"type": "SSN", "confidence": 0.95, "context": "...xxx-xx-1234..."}
```

Extended to:
```json
{
    "type": "SSN",
    "confidence": 0.95,
    "context": "...xxx-xx-1234...",
    "source": "presidio",
    "action": "redact",
    "start_pos": 1234,
    "end_pos": 1245
}
```

New fields:
- `source: "custom_dict" | "presidio"` — which detection layer found it
- `action: "redact" | "keep"` — current redaction decision (smart default, user-overridable)
- `start_pos: int` — character offset start in the scanned text
- `end_pos: int` — character offset end in the scanned text

The `start_pos`/`end_pos` fields are needed so the executor can precisely match detections at commit time — without positions, it would have to re-run detection and hope the results match.

### processor.py changes

In the PII detection section of `process_document()`, when building `pii_detections`:

```python
for m in high_confidence:
    detection = {
        "type": m.data_type.value,
        "confidence": round(m.confidence, 2),
        "context": m.context[:PII_CONTEXT_TRUNCATE],
        "source": "custom_dict" if m in custom_matches else "presidio",
        "start_pos": m.start_pos,
        "end_pos": m.end_pos,
        "action": _default_action(m, custom_matches),
    }
    pii_detections.append(detection)
```

Where `_default_action()` returns:
- `"redact"` for custom_dict matches, SSN, credit_card
- `"keep"` for everything else

---

## 3. Executor Redaction Changes

**Current behavior:** `_redact_pii()` in `executor.py` re-runs Presidio + custom dict at commit time and redacts ALL matches above confidence threshold.

**New behavior:** `_redact_pii()` accepts an optional `redaction_overrides` parameter — the list of `pii_detections` with their `action` fields from the staging manifest.

When overrides are provided:
1. Re-run Presidio + custom dict (same as now — this is the safety net)
2. For each match found, check if it overlaps with a detection in the overrides list
3. If a matching override has `action == "keep"`, skip the redaction for that match
4. If a matching override has `action == "redact"`, apply the redaction
5. Matches NOT in the override list follow the smart defaults (same as analysis time)

**Matching logic:** Match by `(start_pos, end_pos, type)` — if the commit-time detection has the same position range and type as an override, apply the override's action. Position matching handles the case where the text hasn't changed between analysis and commit.

**Fallback:** If no overrides provided (legacy path, CLI ingest, API ingest), use the current behavior — redact everything above threshold.

---

## 4. Dashboard Frontend Changes

### "Edit Redactions" button

On each card, after the existing PII details section, add a button:

```html
<button onclick="toggleRedactionEditor('${id}')"
    class="text-blue-400 hover:text-blue-300 text-sm mt-2">
    Edit Redactions (${detectionCount} detections)
</button>
```

### Redaction editor panel (collapsible)

When expanded, shows a list of detection rows. Each row built with safe DOM methods:

```
[SSN]  95%  Custom Dict  ...xxx-xx-1234...  [REDACT ●○ KEEP]
[NAME] 87%  Presidio     ...John Smith...   [REDACT ○● KEEP]
[EMAIL] 91% Presidio     ...john@acme...    [REDACT ○● KEEP]
```

Toggle is a pill-style button:
- Red state (Redact): red background, "Redact" text
- Green state (Keep): green background, "Keep" text
- Click toggles between states and immediately saves via API

### Saving overrides

When a toggle changes, POST to `/api/update/{item_id}` with the updated `pii_detections` list (same endpoint used for all card updates). The full detection list with updated `action` fields is sent.

---

## 5. File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/processor.py` | Modify | Add `source`, `action`, `start_pos`, `end_pos` to pii_detections |
| `src/executor.py` | Modify | `_redact_pii()` respects per-detection action overrides |
| `src/ui/templates/dashboard.html` | Modify | Redaction editor UI (toggle list, save) |
| `tests/test_processor.py` | Modify | Test smart defaults on detection action |
| `tests/test_executor.py` | Modify | Test selective redaction with overrides |

---

## 6. Success Criteria

1. Sensitive file cards show "Edit Redactions (N detections)" button
2. Expanding shows each detection with type, confidence, source, context, and Keep/Redact toggle
3. Custom dict matches and SSN/CC default to Redact (red)
4. Other NER detections default to Keep (green)
5. User can toggle any detection and the change persists in the manifest
6. At commit time, only "Redact" detections are replaced with [REDACTED-TYPE]
7. "Keep" detections remain in the exported text (main RAG, Obsidian)
8. Legacy code paths (no overrides) still redact everything above threshold
9. Existing tests pass unchanged

---

## 7. Future Enhancement: Inline Highlighted Preview

> Not in SP4 scope. Documented for future consideration.

Replace the toggle list with an inline text view where PII detections are highlighted in the document text. Red highlights = will be redacted, green = will be kept. Click a highlight to toggle it. This provides better context than a truncated snippet but requires mapping character offsets to HTML highlights and handling overlapping detections. Consider for a future UI polish pass.
