"""Tests for Answer Synthesis with Citation Validation."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.search.answer_synthesis import (
    AnswerSynthesizer,
    EvidenceChunk,
    ValidationMode,
)


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.generate = AsyncMock()
    provider.provider_name = "test"
    provider.model_name = "test-model"
    return provider


@pytest.fixture
def synthesizer(mock_provider):
    return AnswerSynthesizer(
        llm_provider=mock_provider,
        max_evidence_chunks=5,
        default_validation_mode=ValidationMode.RELAXED,
    )


@pytest.fixture
def sample_results():
    return [
        {
            "source_path": "docs/auth.md",
            "chunk_index": 0,
            "content": "OAuth2 requires client credentials including a client ID and secret.",
            "score": 0.95,
        },
        {
            "source_path": "docs/auth.md",
            "chunk_index": 1,
            "content": "JWT tokens are signed with HMAC-SHA256 and expire after 24 hours.",
            "score": 0.88,
        },
        {
            "source_path": "docs/setup.md",
            "chunk_index": 0,
            "content": "Install the auth module with pip install auth-module>=2.0.",
            "score": 0.75,
        },
    ]


def _make_llm_response(answer, claims, not_found=False):
    return json.dumps({"answer": answer, "claims": claims, "not_found": not_found})


# ── Evidence Building ─────────────────────────────────────────────────────────


class TestBuildEvidence:
    def test_builds_from_search_results(self, synthesizer, sample_results):
        evidence = synthesizer._build_evidence(sample_results)
        assert len(evidence) == 3
        assert evidence[0].source_path == "docs/auth.md"
        assert evidence[0].chunk_index == 0
        assert "OAuth2" in evidence[0].content

    def test_respects_max_chunks(self, synthesizer, sample_results):
        synthesizer.max_evidence_chunks = 2
        evidence = synthesizer._build_evidence(sample_results)
        assert len(evidence) == 2

    def test_skips_empty_content(self, synthesizer):
        results = [
            {"source_path": "a.md", "chunk_index": 0, "content": "", "score": 0.9},
            {"source_path": "b.md", "chunk_index": 0, "content": "Real content", "score": 0.8},
        ]
        evidence = synthesizer._build_evidence(results)
        assert len(evidence) == 1
        assert evidence[0].source_path == "b.md"

    def test_handles_text_field_alias(self, synthesizer):
        results = [
            {"source_path": "a.md", "chunk_index": 0, "text": "Via text field", "score": 0.9}
        ]
        evidence = synthesizer._build_evidence(results)
        assert evidence[0].content == "Via text field"

    def test_handles_missing_fields_gracefully(self, synthesizer):
        results = [{"content": "Some content", "score": 0.5}]
        evidence = synthesizer._build_evidence(results)
        assert evidence[0].source_path == "unknown"
        assert evidence[0].chunk_index == 0


# ── Citation Validation ───────────────────────────────────────────────────────


class TestCitationValidation:
    def test_valid_strict_citation(self, synthesizer):
        evidence = [EvidenceChunk("docs/auth.md", 0, "OAuth2 requires client credentials.", 0.9)]
        parsed = {
            "claims": [
                {
                    "text": "Auth uses OAuth2.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "OAuth2 requires client credentials.",
                        }
                    ],
                }
            ]
        }
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.STRICT)
        assert errors == []

    def test_invalid_source_reference(self, synthesizer):
        evidence = [EvidenceChunk("docs/auth.md", 0, "OAuth2 requires client credentials.", 0.9)]
        parsed = {
            "claims": [
                {
                    "text": "Made up claim.",
                    "citations": [
                        {
                            "source_path": "docs/nonexistent.md",
                            "chunk_index": 0,
                            "quote": "fake quote",
                        }
                    ],
                }
            ]
        }
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.STRICT)
        assert len(errors) == 1
        assert "unknown source" in errors[0]

    def test_non_verbatim_quote_strict(self, synthesizer):
        evidence = [EvidenceChunk("docs/auth.md", 0, "OAuth2 requires client credentials.", 0.9)]
        parsed = {
            "claims": [
                {
                    "text": "Auth uses OAuth2.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "OAuth2 needs client credentials.",  # "needs" not "requires"
                        }
                    ],
                }
            ]
        }
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.STRICT)
        assert len(errors) == 1
        assert "not found verbatim" in errors[0].lower()

    def test_whitespace_normalization(self, synthesizer):
        evidence = [
            EvidenceChunk("docs/auth.md", 0, "OAuth2  requires   client\ncredentials.", 0.9)
        ]
        parsed = {
            "claims": [
                {
                    "text": "Auth.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "OAuth2 requires client credentials.",
                        }
                    ],
                }
            ]
        }
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.STRICT)
        assert errors == []

    def test_relaxed_mode_skips_quote_validation(self, synthesizer):
        evidence = [EvidenceChunk("docs/auth.md", 0, "OAuth2 requires client credentials.", 0.9)]
        parsed = {
            "claims": [
                {
                    "text": "Auth uses OAuth2.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "Totally different quote",
                        }
                    ],
                }
            ]
        }
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.RELAXED)
        assert errors == []

    def test_no_claims_no_errors(self, synthesizer):
        evidence = [EvidenceChunk("docs/auth.md", 0, "Content.", 0.9)]
        parsed = {"claims": []}
        errors = synthesizer._validate_citations(parsed, evidence, ValidationMode.STRICT)
        assert errors == []


# ── Synthesize Integration ────────────────────────────────────────────────────


class TestSynthesize:
    async def test_empty_results_returns_not_found(self, synthesizer):
        result = await synthesizer.synthesize("What is auth?", [])
        assert result.not_found is True
        assert result.llm_calls == 0

    async def test_single_pass_success(self, synthesizer, mock_provider, sample_results):
        mock_provider.generate.return_value = _make_llm_response(
            answer="OAuth2 uses client credentials.",
            claims=[
                {
                    "text": "OAuth2 uses client credentials.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "OAuth2 requires client credentials",
                        }
                    ],
                    "confidence": 1.0,
                }
            ],
        )

        result = await synthesizer.synthesize("What is auth?", sample_results)
        assert result.not_found is False
        assert result.llm_calls == 1
        assert "OAuth2" in result.answer
        assert len(result.claims) == 1
        assert result.claims[0].citations[0].source_path == "docs/auth.md"

    async def test_two_pass_on_validation_error(self, synthesizer, mock_provider, sample_results):
        # First pass: bad citation
        bad_response = _make_llm_response(
            answer="Auth uses tokens.",
            claims=[
                {
                    "text": "Auth uses tokens.",
                    "citations": [
                        {
                            "source_path": "docs/nonexistent.md",
                            "chunk_index": 0,
                            "quote": "fake",
                        }
                    ],
                    "confidence": 1.0,
                }
            ],
        )
        # Second pass: fixed citation
        good_response = _make_llm_response(
            answer="Auth uses OAuth2.",
            claims=[
                {
                    "text": "Auth uses OAuth2.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "OAuth2 requires client credentials",
                        }
                    ],
                    "confidence": 1.0,
                }
            ],
        )
        mock_provider.generate.side_effect = [bad_response, good_response]

        result = await synthesizer.synthesize("What is auth?", sample_results)
        assert result.llm_calls == 2
        assert result.not_found is False
        assert mock_provider.generate.call_count == 2

    async def test_strict_not_found_on_persistent_errors(self, mock_provider, sample_results):
        synth = AnswerSynthesizer(
            llm_provider=mock_provider,
            default_validation_mode=ValidationMode.STRICT,
        )
        bad_response = _make_llm_response(
            answer="Bad answer.",
            claims=[
                {
                    "text": "Bad claim.",
                    "citations": [
                        {
                            "source_path": "docs/nonexistent.md",
                            "chunk_index": 99,
                            "quote": "fake",
                        }
                    ],
                    "confidence": 1.0,
                }
            ],
        )
        mock_provider.generate.return_value = bad_response

        result = await synth.synthesize("What is auth?", sample_results)
        assert result.not_found is True
        assert result.llm_calls == 2
        assert len(result.validation_errors) > 0

    async def test_not_found_from_llm(self, synthesizer, mock_provider, sample_results):
        mock_provider.generate.return_value = _make_llm_response(
            answer="The evidence does not contain relevant information.",
            claims=[],
            not_found=True,
        )

        result = await synthesizer.synthesize("Unrelated question?", sample_results)
        assert result.not_found is True
        assert result.llm_calls == 1

    async def test_relaxed_mode_passes_with_paraphrase(
        self, synthesizer, mock_provider, sample_results
    ):
        mock_provider.generate.return_value = _make_llm_response(
            answer="You need client creds for OAuth2.",
            claims=[
                {
                    "text": "You need client creds for OAuth2.",
                    "citations": [
                        {
                            "source_path": "docs/auth.md",
                            "chunk_index": 0,
                            "quote": "Paraphrased — not verbatim",
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
        )

        result = await synthesizer.synthesize(
            "What is auth?", sample_results, validation_mode=ValidationMode.RELAXED
        )
        assert result.not_found is False
        assert result.validation_errors == []
        assert result.claims[0].confidence == 0.9

    async def test_sources_used_populated(self, synthesizer, mock_provider, sample_results):
        mock_provider.generate.return_value = _make_llm_response(
            answer="Answer.", claims=[], not_found=False
        )

        result = await synthesizer.synthesize("question?", sample_results)
        assert "docs/auth.md" in result.sources_used
        assert "docs/setup.md" in result.sources_used


# ── JSON Parsing ──────────────────────────────────────────────────────────────


class TestParseAnswer:
    def test_parses_clean_json(self, synthesizer):
        raw = '{"answer": "test", "claims": [], "not_found": false}'
        parsed = synthesizer._parse_answer(raw)
        assert parsed["answer"] == "test"

    def test_extracts_from_code_block(self, synthesizer):
        raw = '```json\n{"answer": "test", "claims": [], "not_found": false}\n```'
        parsed = synthesizer._parse_answer(raw)
        assert parsed["answer"] == "test"

    def test_repairs_truncated_json(self, synthesizer):
        raw = '{"answer": "test", "claims": ['
        parsed = synthesizer._parse_answer(raw)
        assert parsed["answer"] == "test"

    def test_falls_back_to_raw_on_failure(self, synthesizer):
        raw = "Not JSON at all, just plain text answer."
        parsed = synthesizer._parse_answer(raw)
        assert parsed["answer"] == raw
        assert parsed["claims"] == []
