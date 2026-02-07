"""
TDD Example: Red-Green-Refactor cycle for CoreRag.

This file demonstrates the test-driven development pattern required by
standards/TDD.md. Each test class walks through a complete TDD cycle.

Delete or replace this file once real TDD tests are in place.
"""

import pytest

# =============================================================================
# Example 1: TDD for a New Feature
# =============================================================================
# Scenario: We need a function that validates email addresses.
# We write the tests FIRST, run them (RED), then implement (GREEN).


class TestEmailValidation:
    """TDD cycle for email validation feature.

    Step 1 (RED):   Write these tests. Run them. They fail because
                    validate_email() doesn't exist yet.
    Step 2 (GREEN): Implement validate_email() with minimum code
                    to make each test pass.
    Step 3 (REFACTOR): Clean up the implementation, keep tests green.
    """

    def test_valid_email_returns_true(self):
        """RED: This will fail until validate_email is implemented."""
        # from src.utils.validation import validate_email
        # assert validate_email("user@example.com") is True
        pass  # Replace with real assertion when implementing

    def test_missing_at_sign_returns_false(self):
        """RED: Catches emails without @ symbol."""
        # from src.utils.validation import validate_email
        # assert validate_email("userexample.com") is False
        pass

    def test_empty_string_returns_false(self):
        """RED: Edge case for empty input."""
        # from src.utils.validation import validate_email
        # assert validate_email("") is False
        pass


# =============================================================================
# Example 2: TDD for a Bug Fix
# =============================================================================
# Scenario: A parser fails when input contains special characters.
# We write a test that reproduces the bug, confirm it fails, then fix.


class TestBugFixRegression:
    """TDD cycle for bug fix.

    The strongest TDD use case: the test PROVES the bug exists,
    then PROVES the fix works, then PREVENTS regression forever.

    Step 1 (RED):   Write test reproducing the bug. Run it. It fails.
    Step 2 (GREEN): Fix the bug. Run test. It passes.
    Step 3:         This test now lives permanently as a regression guard.
    """

    @pytest.mark.tdd
    def test_parser_handles_special_characters(self):
        """Regression: parser crashed on '&' in input.

        BUG: parse_name("Smith & Associates") raised ValueError
        FIX: Escape special characters before regex matching
        """
        # from src.parser import parse_name
        # result = parse_name("Smith & Associates")
        # assert result == "Smith & Associates"
        pass  # Replace with real reproduction of the bug


# =============================================================================
# Example 3: Parametrized TDD
# =============================================================================
# Scenario: Multiple input/output pairs defined upfront.
# Write ALL test cases first (RED), then implement to satisfy them all (GREEN).


class TestDataTransformation:
    """TDD with parametrize: define all expected behaviors first.

    Write the full parametrize table before any implementation.
    Run all cases (RED). Implement until all pass (GREEN).
    """

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("hello world", "Hello World"),  # basic title case
            ("ALREADY UPPER", "Already Upper"),  # handles all-caps
            ("multiple   spaces", "Multiple Spaces"),  # normalizes whitespace
            ("", ""),  # empty string edge case
        ],
    )
    def test_normalize_title(self, input_val, expected):
        """RED: All cases fail until normalize_title is implemented."""
        # from src.utils.text import normalize_title
        # assert normalize_title(input_val) == expected
        pass


# =============================================================================
# TDD Checklist (copy into your test files as a reminder)
# =============================================================================
#
# Before marking a test as done:
#   [ ] Saw it fail (RED phase completed)
#   [ ] Failed for the right reason (not a setup/import error)
#   [ ] Wrote minimum code to pass (GREEN phase)
#   [ ] Refactored while keeping tests green (REFACTOR phase)
#   [ ] Test name follows: test_<function>_<scenario>_<expected>
#   [ ] Test verifies ONE specific behavior
#   [ ] No shared mutable state between tests
