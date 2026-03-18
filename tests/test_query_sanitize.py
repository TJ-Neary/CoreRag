"""
Tests for LanceDB query sanitization utilities.

Covers: sanitize_string_value, validate_identifier, safe_identifier,
build_eq_clause, build_like_clause, build_tag_clause, build_tag_clauses,
build_filter_clause.

Run with: pytest tests/test_query_sanitize.py -v
"""

import pytest

from src.utils.query_sanitize import (
    build_eq_clause,
    build_filter_clause,
    build_like_clause,
    build_tag_clause,
    build_tag_clauses,
    safe_identifier,
    sanitize_string_value,
    validate_identifier,
)

# ---------------------------------------------------------------------------
# sanitize_string_value
# ---------------------------------------------------------------------------


class TestSanitizeStringValue:
    """Tests for sanitize_string_value()."""

    def test_plain_string_unchanged(self) -> None:
        assert sanitize_string_value("hello") == "hello"

    def test_single_quote_doubled(self) -> None:
        assert sanitize_string_value("O'Brien") == "O''Brien"

    def test_multiple_quotes_doubled(self) -> None:
        result = sanitize_string_value("it's a it's")
        assert result == "it''s a it''s"

    def test_sql_injection_drop_table(self) -> None:
        payload = "'; DROP TABLE chunks; --"
        result = sanitize_string_value(payload)
        # Single quote must be escaped; DROP TABLE still present as text is fine
        # — the critical part is the quote is doubled
        assert "'" not in result.replace("''", "")

    def test_sql_injection_or_true(self) -> None:
        payload = '" OR 1=1'
        result = sanitize_string_value(payload)
        # Double quotes are not special for LanceDB but we confirm no crash
        assert isinstance(result, str)

    def test_null_byte_removed(self) -> None:
        result = sanitize_string_value("file\x00.txt")
        assert "\x00" not in result
        assert result == "file.txt"

    def test_null_byte_only_removed(self) -> None:
        result = sanitize_string_value("\x00\x00")
        assert result == ""

    def test_non_string_converted(self) -> None:
        result = sanitize_string_value(42)  # type: ignore[arg-type]
        assert result == "42"

    def test_empty_string_unchanged(self) -> None:
        assert sanitize_string_value("") == ""

    def test_unicode_string_unchanged(self) -> None:
        result = sanitize_string_value("résumé café")
        assert result == "résumé café"


# ---------------------------------------------------------------------------
# validate_identifier
# ---------------------------------------------------------------------------


class TestValidateIdentifier:
    """Tests for validate_identifier()."""

    def test_simple_name_valid(self) -> None:
        assert validate_identifier("document_id") is True

    def test_leading_underscore_valid(self) -> None:
        assert validate_identifier("_private") is True

    def test_alphanumeric_valid(self) -> None:
        assert validate_identifier("col1") is True

    def test_empty_string_invalid(self) -> None:
        assert validate_identifier("") is False

    def test_none_invalid(self) -> None:
        assert validate_identifier(None) is False  # type: ignore[arg-type]

    def test_space_in_name_invalid(self) -> None:
        assert validate_identifier("my column") is False

    def test_leading_digit_invalid(self) -> None:
        assert validate_identifier("1col") is False

    def test_hyphen_invalid(self) -> None:
        assert validate_identifier("col-name") is False

    def test_semicolon_invalid(self) -> None:
        assert validate_identifier("col;DROP") is False

    def test_single_quote_invalid(self) -> None:
        assert validate_identifier("col'name") is False

    def test_dot_invalid(self) -> None:
        assert validate_identifier("table.column") is False

    def test_all_uppercase_valid(self) -> None:
        assert validate_identifier("COLUMN_NAME") is True


# ---------------------------------------------------------------------------
# safe_identifier
# ---------------------------------------------------------------------------


class TestSafeIdentifier:
    """Tests for safe_identifier()."""

    def test_valid_name_returned(self) -> None:
        result = safe_identifier("document_id")
        assert result == "document_id"

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid identifier"):
            safe_identifier("'; DROP TABLE--")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            safe_identifier("")

    def test_space_raises(self) -> None:
        with pytest.raises(ValueError):
            safe_identifier("my column")


# ---------------------------------------------------------------------------
# build_eq_clause
# ---------------------------------------------------------------------------


class TestBuildEqClause:
    """Tests for build_eq_clause()."""

    def test_simple_clause(self) -> None:
        result = build_eq_clause("document_id", "abc-123")
        assert result == "document_id = 'abc-123'"

    def test_name_with_apostrophe(self) -> None:
        result = build_eq_clause("name", "O'Brien")
        assert result == "name = 'O''Brien'"

    def test_integer_value_stringified(self) -> None:
        result = build_eq_clause("year", 2024)
        assert result == "year = '2024'"

    def test_invalid_column_raises(self) -> None:
        with pytest.raises(ValueError):
            build_eq_clause("bad column!", "value")

    def test_sql_injection_in_value_escaped(self) -> None:
        result = build_eq_clause("category", "'; DROP TABLE chunks; --")
        # Single quotes in the value are doubled (SQL standard escaping)
        # The injected quote becomes '', so SQL parser treats it as literal, not terminator
        assert result == "category = '''; DROP TABLE chunks; --'"

    def test_null_byte_in_value_removed(self) -> None:
        result = build_eq_clause("col", "val\x00ue")
        assert "\x00" not in result


# ---------------------------------------------------------------------------
# build_like_clause
# ---------------------------------------------------------------------------


class TestBuildLikeClause:
    """Tests for build_like_clause()."""

    def test_simple_pattern(self) -> None:
        result = build_like_clause("tags", "%,python,%")
        assert result == "tags LIKE '%,python,%'"

    def test_leading_wildcard(self) -> None:
        result = build_like_clause("title", "%report%")
        assert result == "title LIKE '%report%'"

    def test_invalid_column_raises(self) -> None:
        with pytest.raises(ValueError):
            build_like_clause("bad col", "%value%")

    def test_quote_in_pattern_escaped(self) -> None:
        result = build_like_clause("name", "%O'Brien%")
        assert "O''Brien" in result


# ---------------------------------------------------------------------------
# build_tag_clause
# ---------------------------------------------------------------------------


class TestBuildTagClause:
    """Tests for build_tag_clause()."""

    def test_simple_tag(self) -> None:
        result = build_tag_clause("python")
        assert result == "tags LIKE '%,python,%'"

    def test_tag_with_hyphen(self) -> None:
        result = build_tag_clause("sphr-study")
        assert result == "tags LIKE '%,sphr-study,%'"

    def test_tag_with_apostrophe_escaped(self) -> None:
        result = build_tag_clause("it's-tag")
        assert "it''s-tag" in result

    def test_injection_attempt_in_tag(self) -> None:
        result = build_tag_clause("'; DROP TABLE--")
        # The apostrophe must be escaped
        assert "''" in result or "'; DROP" not in result


# ---------------------------------------------------------------------------
# build_tag_clauses
# ---------------------------------------------------------------------------


class TestBuildTagClauses:
    """Tests for build_tag_clauses()."""

    def test_single_tag_as_string(self) -> None:
        result = build_tag_clauses("python")
        assert result == "tags LIKE '%,python,%'"

    def test_single_tag_as_list(self) -> None:
        result = build_tag_clauses(["python"])
        assert result == "tags LIKE '%,python,%'"

    def test_multiple_tags_joined_with_and(self) -> None:
        result = build_tag_clauses(["python", "ml"])
        assert result == "tags LIKE '%,python,%' AND tags LIKE '%,ml,%'"

    def test_three_tags(self) -> None:
        result = build_tag_clauses(["a", "b", "c"])
        assert result.count(" AND ") == 2


# ---------------------------------------------------------------------------
# build_filter_clause
# ---------------------------------------------------------------------------


class TestBuildFilterClause:
    """Tests for build_filter_clause()."""

    def test_single_equality_filter(self) -> None:
        result = build_filter_clause({"category": "work"})
        assert result == "category = 'work'"

    def test_tag_filter_uses_like(self) -> None:
        result = build_filter_clause({"tags": ["python"]})
        assert "LIKE" in result
        assert "python" in result

    def test_combined_category_and_tag(self) -> None:
        result = build_filter_clause({"category": "work", "tags": ["python"]})
        assert "category = 'work'" in result
        assert "tags LIKE '%,python,%'" in result
        assert " AND " in result

    def test_multi_tag_list_in_filter(self) -> None:
        result = build_filter_clause({"tags": ["ml", "python"]})
        assert "ml" in result
        assert "python" in result
        assert " AND " in result

    def test_empty_filter_returns_empty_string(self) -> None:
        result = build_filter_clause({})
        assert result == ""

    def test_injection_in_filter_value_escaped(self) -> None:
        result = build_filter_clause({"category": "'; DROP TABLE--"})
        # Quotes doubled: injected ' becomes '' (SQL standard escaping)
        assert result == "category = '''; DROP TABLE--'"

    def test_invalid_column_raises(self) -> None:
        with pytest.raises(ValueError):
            build_filter_clause({"bad col!": "value"})
