"""
Answer Synthesis with Citation Validation for CoreRag.

Generates cited answers from search results using a two-pass LLM pattern:
1. First pass: generate answer with inline citations
2. Validate: check citation sources exist, quotes are verbatim (strict mode)
3. Second pass (if needed): re-generate with validation error feedback
4. Return structured AnswerResult with claims, citations, and validation info

Supports STRICT mode (verbatim quotes required) and RELAXED mode (paraphrasing OK).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.exceptions import ProcessingError
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


# ── Data Classes ──────────────────────────────────────────────────────────────


class ValidationMode(str, Enum):
    STRICT = "strict"
    RELAXED = "relaxed"


@dataclass
class EvidenceChunk:
    source_path: str
    chunk_index: int
    content: str
    score: float


@dataclass
class Citation:
    source_path: str
    chunk_index: int
    quote: str
    confidence: float = 1.0


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class AnswerResult:
    query: str
    answer: str
    claims: list[Claim] = field(default_factory=list)
    validation_mode: ValidationMode = ValidationMode.RELAXED
    validation_errors: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    llm_calls: int = 0
    not_found: bool = False


# ── Prompts ───────────────────────────────────────────────────────────────────

_STRICT_SYSTEM = """You are a precise research assistant. Answer the user's question using ONLY the provided evidence. Every claim must include an exact verbatim quote from the evidence.

Rules:
- Only use information from the provided evidence chunks
- For each claim, cite the source using [source_path, Chunk N] format
- Include a verbatim quote from the evidence for each citation
- If the evidence does not contain enough information, say so clearly
- Do NOT make up or infer information beyond what is explicitly stated"""

_RELAXED_SYSTEM = """You are a helpful research assistant. Answer the user's question using the provided evidence. Cite your sources using [source_path, Chunk N] format.

Rules:
- Use information from the provided evidence chunks
- Cite sources for key claims using [source_path, Chunk N] format
- You may paraphrase the evidence in your own words
- If the evidence is insufficient, say so clearly
- Indicate your confidence level for each claim (high, medium, low)"""

_ANSWER_FORMAT = """

Respond with ONLY valid JSON in this format:
{
    "answer": "Your synthesized answer text here.",
    "claims": [
        {
            "text": "A specific claim from your answer.",
            "citations": [
                {
                    "source_path": "path/to/file.md",
                    "chunk_index": 0,
                    "quote": "exact verbatim quote from evidence"
                }
            ],
            "confidence": 1.0
        }
    ],
    "not_found": false
}

Set "not_found" to true if the evidence does not contain relevant information."""

_VERIFIER_SYSTEM = """You are a citation verifier. The previous answer had citation errors. Review the original evidence and fix the answer.

Errors found:
{errors}

Fix these errors by:
- Replacing invalid citations with correct ones from the evidence
- Ensuring all quotes are verbatim (exact matches from the evidence text)
- Removing claims that cannot be supported by the evidence
- If a claim cannot be properly cited, remove it"""


# ── Answer Synthesizer ────────────────────────────────────────────────────────


class AnswerSynthesizer:
    """Generates cited answers from search results with validation."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        max_evidence_chunks: int = 10,
        default_validation_mode: ValidationMode = ValidationMode.RELAXED,
    ):
        self.llm_provider = llm_provider
        self.max_evidence_chunks = max_evidence_chunks
        self.default_validation_mode = default_validation_mode

    async def synthesize(
        self,
        query: str,
        search_results: list[dict],
        validation_mode: Optional[ValidationMode] = None,
    ) -> AnswerResult:
        """Synthesize an answer from search results with citation validation.

        Args:
            query: The user's question
            search_results: List of search result dicts with source_path, chunk_index,
                           content/text, and score fields
            validation_mode: STRICT or RELAXED (defaults to instance default)

        Returns:
            AnswerResult with answer, claims, citations, and validation info
        """
        mode = validation_mode or self.default_validation_mode

        # Empty results → not_found
        if not search_results:
            return AnswerResult(
                query=query,
                answer="No relevant information found in the knowledge base.",
                validation_mode=mode,
                not_found=True,
            )

        # Build evidence map
        evidence = self._build_evidence(search_results)

        if not evidence:
            return AnswerResult(
                query=query,
                answer="No relevant information found in the knowledge base.",
                validation_mode=mode,
                not_found=True,
            )

        # Format evidence for LLM
        evidence_text = self._format_evidence(evidence)
        user_prompt = f"Evidence:\n{evidence_text}\n\nQuestion: {query}{_ANSWER_FORMAT}"

        system_prompt = _STRICT_SYSTEM if mode == ValidationMode.STRICT else _RELAXED_SYSTEM

        # First pass
        try:
            raw = await self.llm_provider.generate(system_prompt, user_prompt)
            llm_calls = 1
        except Exception as e:
            logger.error(f"Answer synthesis LLM call failed: {e}")
            raise ProcessingError(f"Answer synthesis failed: {e}") from e

        parsed = self._parse_answer(raw)
        if parsed.get("not_found"):
            return AnswerResult(
                query=query,
                answer=parsed.get("answer", "Information not found in evidence."),
                validation_mode=mode,
                not_found=True,
                llm_calls=llm_calls,
            )

        # Validate citations
        errors = self._validate_citations(parsed, evidence, mode)

        # Second pass if validation failed
        if errors:
            logger.info(f"Citation validation found {len(errors)} errors, running verifier pass")
            verifier_system = _VERIFIER_SYSTEM.format(errors="\n".join(f"- {e}" for e in errors))
            verifier_prompt = f"{verifier_system}\n\n{user_prompt}"

            try:
                raw = await self.llm_provider.generate(
                    "Fix the citation errors in the answer.", verifier_prompt
                )
                llm_calls += 1
            except Exception as e:
                logger.warning(f"Verifier pass failed: {e}")
                # Fall through with original errors

            parsed = self._parse_answer(raw)
            errors = self._validate_citations(parsed, evidence, mode)

        # If still errors in strict mode, mark as not_found
        if errors and mode == ValidationMode.STRICT:
            return AnswerResult(
                query=query,
                answer=parsed.get("answer", ""),
                validation_mode=mode,
                validation_errors=errors,
                not_found=True,
                llm_calls=llm_calls,
                sources_used=list({e.source_path for e in evidence}),
            )

        # Build result
        claims = self._build_claims(parsed)
        sources = list({e.source_path for e in evidence})

        return AnswerResult(
            query=query,
            answer=parsed.get("answer", ""),
            claims=claims,
            validation_mode=mode,
            validation_errors=errors,
            sources_used=sources,
            llm_calls=llm_calls,
            not_found=False,
        )

    def _build_evidence(self, search_results: list[dict]) -> list[EvidenceChunk]:
        """Build evidence chunks from search results."""
        evidence = []
        for r in search_results[: self.max_evidence_chunks]:
            content = r.get("content") or r.get("text") or ""
            if not content.strip():
                continue
            evidence.append(
                EvidenceChunk(
                    source_path=r.get("source_path", r.get("source", "unknown")),
                    chunk_index=r.get("chunk_index", r.get("chunk_id", 0)),
                    content=content.strip(),
                    score=float(r.get("score", r.get("_distance", 0.0))),
                )
            )
        return evidence

    def _format_evidence(self, evidence: list[EvidenceChunk]) -> str:
        """Format evidence chunks for the LLM prompt."""
        parts = []
        for e in evidence:
            parts.append(f"[{e.source_path}, Chunk {e.chunk_index}]:\n{e.content}\n")
        return "\n".join(parts)

    def _validate_citations(
        self, parsed: dict, evidence: list[EvidenceChunk], mode: ValidationMode
    ) -> list[str]:
        """Validate citations against evidence. Returns list of error strings."""
        errors = []
        evidence_map: dict[tuple[str, int], str] = {
            (e.source_path, e.chunk_index): e.content for e in evidence
        }

        for claim_data in parsed.get("claims", []):
            for cit in claim_data.get("citations", []):
                source = cit.get("source_path", "")
                chunk_idx = cit.get("chunk_index", -1)
                key = (source, chunk_idx)

                # Check source exists
                if key not in evidence_map:
                    errors.append(
                        f"Citation references unknown source: [{source}, Chunk {chunk_idx}]"
                    )
                    continue

                # Strict mode: check verbatim quote
                if mode == ValidationMode.STRICT:
                    quote = cit.get("quote", "")
                    if quote:
                        normalized_quote = self._normalize_whitespace(quote)
                        normalized_content = self._normalize_whitespace(evidence_map[key])
                        if normalized_quote not in normalized_content:
                            errors.append(
                                f"Quote not found verbatim in [{source}, Chunk {chunk_idx}]: "
                                f'"{quote[:80]}..."'
                            )

        return errors

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Normalize whitespace for quote comparison."""
        return re.sub(r"\s+", " ", text).strip().lower()

    def _parse_answer(self, raw: str) -> dict:
        """Parse LLM response JSON with cleanup."""
        # Try to extract JSON from markdown code block
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        text = match.group(1) if match else raw.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Attempt repair: close unterminated strings and braces
        repaired = self._repair_json(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse answer JSON: {text[:200]}...")
            return {"answer": raw.strip(), "claims": [], "not_found": False}

    @staticmethod
    def _repair_json(text: str) -> str:
        """Attempt to fix truncated JSON."""
        s = text.strip()
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

        open_braces = s.count("{") - s.count("}")
        open_brackets = s.count("[") - s.count("]")
        s += "]" * max(0, open_brackets)
        s += "}" * max(0, open_braces)
        return s

    def _build_claims(self, parsed: dict) -> list[Claim]:
        """Build Claim objects from parsed LLM output."""
        claims = []
        for claim_data in parsed.get("claims", []):
            citations = []
            for cit in claim_data.get("citations", []):
                citations.append(
                    Citation(
                        source_path=cit.get("source_path", ""),
                        chunk_index=cit.get("chunk_index", 0),
                        quote=cit.get("quote", ""),
                        confidence=float(cit.get("confidence", 1.0)),
                    )
                )
            claims.append(
                Claim(
                    text=claim_data.get("text", ""),
                    citations=citations,
                    confidence=float(claim_data.get("confidence", 1.0)),
                )
            )
        return claims
