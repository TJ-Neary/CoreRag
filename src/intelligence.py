import json
import logging
import re

from src.correction_log import get_recent_examples
from src.exceptions import ProcessingError
from src.llm.provider import get_default_provider

logger = logging.getLogger(__name__)


# ── Text Sampling ─────────────────────────────────────────────────────────────


def _sample_text(text: str, max_chars: int = 12000) -> str:
    """Build a representative sample of the document for LLM classification.

    For short documents (≤ max_chars), returns the full text.
    For long documents, returns the first 9000 chars + last 3000 chars
    with a separator, giving the LLM both the opening context and ending.
    """
    if len(text) <= max_chars:
        return text

    head = max_chars - 3000
    tail = 3000
    return text[:head] + "\n\n[... middle of document omitted for brevity ...]\n\n" + text[-tail:]


# ── Core Analysis Prompt ──────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """<document>
{text}
</document>

Analyze the document above and respond with ONLY a valid JSON object. No markdown, no explanation.

Instructions:
1. Classify the document:
   - category: one of Medical, Financial, Legal, Personal, Work, Education, Technical, Unsorted
   - year: the most relevant year as "YYYY" (or "Unknown")
   - type: one of Statement, Receipt, Contract, Prescription, Report, Guide, Manual, Policy, Certification, Correspondence, Unsorted
2. Suggest a concise descriptive filename (no extension, no year, use underscores).
3. Write a 1-2 sentence summary of what this document is about.
4. If you notice any specific personal information (real names of private individuals, mailing addresses, account numbers, dates of birth, etc.), briefly describe what you found in pii_observations. If none, set to empty string. Do NOT mention topic words like "salary", "medical", "hospital" — only actual personal data.

JSON format:
{{"category": "Work", "year": "2024", "type": "Guide", "suggested_name": "descriptive_filename", "summary": "A concise summary of the document content.", "pii_observations": ""}}"""


async def analyze_document(text: str) -> tuple[dict, str]:
    """Analyzes text to extract metadata.

    Uses the configured LLM provider (Ollama, Gemini, or Anthropic).

    The LLM handles classification, summarization, and advisory PII observations.
    Actual PII detection is done by Presidio + custom dictionary in processor.py.
    PII redaction is done by Presidio at commit time in executor.py.

    Returns: (metadata_dict, original_text_str)
        - metadata_dict: category, year, type, summary, suggested_name, pii_observations
        - original_text_str: the full extracted text (unmodified — redaction happens later)
    """
    if not text.strip():
        return {
            "category": "Unsorted",
            "year": "Unknown",
            "type": "Document",
            "summary": "No text to analyze.",
            "suggested_name": "empty_document",
            "pii_observations": "",
        }, text

    sample = _sample_text(text)
    correction_examples = get_recent_examples()
    prompt = _ANALYSIS_PROMPT.format(text=sample) + correction_examples

    provider = get_default_provider()
    try:
        raw = await provider.generate("", prompt)

        cleaned = _clean_json_markdown(raw)
        repaired = _repair_json(cleaned)
        metadata = json.loads(repaired)

        # The LLM may wrap in {"metadata": {...}} or return flat — handle both
        if "metadata" in metadata and isinstance(metadata["metadata"], dict):
            metadata = metadata["metadata"]

        # Ensure all expected fields exist with defaults
        metadata.setdefault("category", "Unsorted")
        metadata.setdefault("year", "Unknown")
        metadata.setdefault("type", "Document")
        metadata.setdefault("summary", "")
        metadata.setdefault("suggested_name", "")
        metadata.setdefault("pii_observations", "")
        # Remove is_sensitive if the LLM included it (no longer its responsibility)
        metadata.pop("is_sensitive", None)

        # Apply learned rules from user correction patterns
        try:
            from src.classification.learned_rules import LearnedRulesManager

            rules_mgr = LearnedRulesManager()
            category = metadata.get("category", "")
            folder_hint = rules_mgr.get_folder_suggestion("", category)
            if folder_hint:
                metadata["_learned_folder"] = folder_hint
            sens_hint = rules_mgr.should_mark_sensitive(category, metadata.get("type", ""))
            if sens_hint is not None:
                metadata["_learned_sensitivity"] = sens_hint
        except Exception as e:
            logger.debug(f"Learned rules lookup skipped: {e}")

        logger.info(
            f"Analysis complete: category={metadata['category']}, "
            f"year={metadata['year']}, type={metadata['type']}, "
            f"summary={metadata['summary'][:80]}..."
        )

        # Return the original text — PII redaction is done at commit time by Presidio
        return metadata, text

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"Intelligence analysis failed ({provider.provider_name}): {e}")
        raise ProcessingError(
            f"Intelligence analysis failed ({provider.provider_name}): {e}"
        ) from e


# ── Folder Suggestion ─────────────────────────────────────────────────────────


async def suggest_folder_structure(
    documents: list[dict], existing_structure: dict | None = None
) -> dict:
    """Suggests a folder taxonomy and per-document folder assignments."""
    if not documents:
        return {"folders": {}, "assignments": {}}

    doc_summaries = "\n".join(
        f"- ID: {d['id']} | File: {d['filename']} | Category: {d.get('category', 'Unknown')} "
        f"| Summary: {d.get('summary', 'N/A')}"
        for d in documents
    )

    existing_ctx = ""
    if existing_structure and existing_structure.get("folders"):
        import yaml

        existing_ctx = (
            f"\nExisting folder structure (fit new files in or suggest additions):\n"
            f"```yaml\n{yaml.dump(existing_structure['folders'], default_flow_style=False)}```\n"
        )

    prompt = f"""You are a file organization assistant. Given these documents, suggest a coherent
folder taxonomy and assign each document to the best folder.
{existing_ctx}
Documents:
{doc_summaries}

Output ONLY valid JSON:
{{
    "folders": {{
        "CategoryName": ["Subcategory1", "Subcategory2"],
        ...
    }},
    "assignments": {{
        "document_id": "CategoryName/Subcategory",
        ...
    }}
}}

Rules:
- Keep top-level categories broad (Medical, Financial, Legal, Personal, Work, etc.)
- Use subcategories for specificity
- Each assignment value should be a path like "Category" or "Category/Subcategory"
- Prefer fitting into existing structure when provided
"""

    provider = get_default_provider()
    try:
        raw = await provider.generate("", prompt)

        cleaned = _clean_json_markdown(raw)
        return json.loads(cleaned)

    except ProcessingError:
        raise
    except Exception as e:
        logger.error(f"Folder suggestion failed ({provider.provider_name}): {e}")
        raise ProcessingError(f"Folder suggestion failed ({provider.provider_name}): {e}") from e


def _clean_json_markdown(text: str) -> str:
    """Removes markdown code block formatting to extract raw JSON."""
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def _repair_json(text: str) -> str:
    """Attempt to fix truncated JSON from local LLMs."""
    s = text.strip()
    # Try parsing as-is first
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass

    # Close unterminated strings and braces
    # Count unmatched quotes
    in_string = False
    escaped = False
    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string

    if in_string:
        s += '..."'

    # Close unmatched braces/brackets
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    s += "]" * max(0, open_brackets)
    s += "}" * max(0, open_braces)

    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        raise ValueError(f"Could not repair JSON: {text[:200]}...")
