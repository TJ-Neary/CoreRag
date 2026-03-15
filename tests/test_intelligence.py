"""Tests for src/intelligence.py — JSON repair, text sampling, document analysis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.intelligence import _clean_json_markdown, _repair_json, _sample_text


class TestSampleText:
    def test_short_text_returned_unchanged(self):
        assert _sample_text("hello", max_chars=100) == "hello"

    def test_exactly_max_chars(self):
        text = "x" * 12000
        assert _sample_text(text) == text

    def test_long_text_truncated_with_head_and_tail(self):
        text = "H" * 10000 + "T" * 5000  # 15000 chars
        result = _sample_text(text, max_chars=12000)
        assert result.startswith("H" * 100)  # Head preserved
        assert result.endswith("T" * 100)  # Tail preserved
        assert len(result) <= 12200  # Head + separator + tail
        assert "[... middle of document omitted for brevity ...]" in result

    def test_empty_string(self):
        assert _sample_text("") == ""


class TestCleanJsonMarkdown:
    def test_strips_json_fences(self):
        assert _clean_json_markdown('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_no_fences_strips_whitespace(self):
        assert _clean_json_markdown('  {"a": 1}  ') == '{"a": 1}'

    def test_non_json_fences_not_matched(self):
        raw = '```\n{"a": 1}\n```'
        result = _clean_json_markdown(raw)
        assert result == raw.strip()

    def test_multiline_json(self):
        raw = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
        result = _clean_json_markdown(raw)
        assert '"a": 1' in result
        assert '"b": 2' in result


class TestRepairJson:
    def test_valid_json_unchanged(self):
        assert _repair_json('{"a": 1}') == '{"a": 1}'

    def test_truncated_string_closed(self):
        import json

        result = _repair_json('{"a": "hel')
        parsed = json.loads(result)
        assert "a" in parsed

    def test_unclosed_brace(self):
        import json

        result = _repair_json('{"a": 1')
        parsed = json.loads(result)
        assert parsed["a"] == 1

    def test_unclosed_bracket(self):
        import json

        result = _repair_json('{"a": [1, 2')
        parsed = json.loads(result)
        assert parsed["a"] == [1, 2]

    def test_irreparable_raises_valueerror(self):
        with pytest.raises(ValueError, match="Could not repair"):
            _repair_json("not json at all {{{")

    def test_valid_array(self):
        assert _repair_json("[1, 2, 3]") == "[1, 2, 3]"


@pytest.fixture(autouse=True)
def _mock_context_helpers():
    """Patch context helpers so tests don't hit real catalog/filesystem."""
    with (
        patch("src.intelligence._get_existing_tags", return_value="none yet"),
        patch("src.intelligence._get_archive_folder_tree", return_value="No archive folders yet."),
    ):
        yield


class TestAnalyzeDocument:
    @pytest.mark.asyncio
    async def test_empty_text_returns_defaults(self):
        from src.intelligence import analyze_document

        metadata, text = await analyze_document("")
        assert metadata["category"] == "Unsorted"
        assert metadata["year"] == "Unknown"
        assert text == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_defaults(self):
        from src.intelligence import analyze_document

        metadata, text = await analyze_document("   \n\t  ")
        assert metadata["category"] == "Unsorted"

    @pytest.mark.asyncio
    async def test_llm_returns_valid_json(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "HR", "year": "2024", "type": "policy", '
            '"summary": "Test doc", "suggested_name": "test", '
            '"pii_observations": "none"}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, text = await analyze_document("Some document content here.")

        assert metadata["category"] == "HR"
        assert metadata["year"] == "2024"
        assert metadata["tags"] == []  # LLM didn't return tags, should default to []
        assert text == "Some document content here."

    @pytest.mark.asyncio
    async def test_llm_returns_tags(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "Work", "year": "2024", "type": "Guide", '
            '"summary": "Test", "suggested_name": "test", '
            '"pii_observations": "", "tags": ["fitness", "nutrition"]}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Fitness guide content.")

        assert metadata["tags"] == ["fitness", "nutrition"]

    @pytest.mark.asyncio
    async def test_llm_returns_markdown_wrapped_json(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='```json\n{"category": "Finance", "year": "2023", "type": "report", '
            '"summary": "Q4", "suggested_name": "q4", '
            '"pii_observations": ""}\n```'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Financial report content.")

        assert metadata["category"] == "Finance"

    @pytest.mark.asyncio
    async def test_llm_is_sensitive_stripped(self):
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(
            return_value='{"category": "HR", "year": "2024", "type": "doc", '
            '"summary": "s", "suggested_name": "f", '
            '"pii_observations": "n", "is_sensitive": true}'
        )

        with patch("src.intelligence.get_default_provider", return_value=mock_provider):
            metadata, _ = await analyze_document("Content")

        assert "is_sensitive" not in metadata

    @pytest.mark.asyncio
    async def test_provider_failure_raises_processing_error(self):
        from src.exceptions import ProcessingError
        from src.intelligence import analyze_document

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=Exception("Connection refused"))

        with (
            patch("src.intelligence.get_default_provider", return_value=mock_provider),
            pytest.raises(ProcessingError),
        ):
            await analyze_document("Some content")
