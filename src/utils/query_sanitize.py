"""
LanceDB Query Sanitization

Prevents SQL injection in LanceDB where clauses by:
1. Escaping single quotes in string values
2. Validating column/table identifiers
3. Providing safe clause builders

LanceDB uses SQL-like syntax for filtering, so standard SQL injection
defenses apply.
"""

import re
from typing import Any, List, Union

# Pattern for valid SQL identifiers (column names, table names)
# Only allows alphanumeric characters and underscores
VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def sanitize_string_value(value: str) -> str:
    """
    Escape a string value for use in LanceDB SQL-like queries.

    Escapes single quotes by doubling them (SQL standard).
    Also removes null bytes which could cause issues.

    Args:
        value: The string value to sanitize

    Returns:
        Sanitized string safe for use in SQL-like queries

    Example:
        >>> sanitize_string_value("O'Brien")
        "O''Brien"
    """
    if not isinstance(value, str):
        value = str(value)

    # Remove null bytes
    value = value.replace("\x00", "")

    # Escape single quotes by doubling them
    value = value.replace("'", "''")

    return value


def validate_identifier(name: str) -> bool:
    """
    Validate that a string is a safe SQL identifier.

    Only allows alphanumeric characters and underscores,
    must start with letter or underscore.

    Args:
        name: The identifier to validate

    Returns:
        True if valid, False otherwise
    """
    if not name or not isinstance(name, str):
        return False
    return bool(VALID_IDENTIFIER_PATTERN.match(name))


def safe_identifier(name: str) -> str:
    """
    Validate and return a safe identifier, raising ValueError if invalid.

    Args:
        name: The identifier to validate

    Returns:
        The identifier if valid

    Raises:
        ValueError: If the identifier is invalid
    """
    if not validate_identifier(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def build_eq_clause(column: str, value: Any) -> str:
    """
    Build a safe equality clause: column = 'value'

    Args:
        column: Column name (must be valid identifier)
        value: Value to compare (will be sanitized)

    Returns:
        Safe SQL clause string

    Raises:
        ValueError: If column name is invalid

    Example:
        >>> build_eq_clause("document_id", "abc-123")
        "document_id = 'abc-123'"
        >>> build_eq_clause("name", "O'Brien")
        "name = 'O''Brien'"
    """
    safe_col = safe_identifier(column)
    safe_val = sanitize_string_value(str(value))
    return f"{safe_col} = '{safe_val}'"


def build_like_clause(column: str, pattern: str) -> str:
    """
    Build a safe LIKE clause: column LIKE 'pattern'

    Note: The pattern should include % wildcards as needed.
    Single quotes in the pattern will be escaped.

    Args:
        column: Column name (must be valid identifier)
        pattern: LIKE pattern (with % wildcards)

    Returns:
        Safe SQL LIKE clause string

    Raises:
        ValueError: If column name is invalid

    Example:
        >>> build_like_clause("tags", "%,python,%")
        "tags LIKE '%,python,%'"
    """
    safe_col = safe_identifier(column)
    safe_pattern = sanitize_string_value(pattern)
    return f"{safe_col} LIKE '{safe_pattern}'"


def build_tag_clause(tag: str) -> str:
    """
    Build a safe tag filter clause.

    Tags are stored as ",tag1,tag2," so we use LIKE '%,tag,%'

    Args:
        tag: Tag name to filter by

    Returns:
        Safe SQL LIKE clause for tag matching

    Example:
        >>> build_tag_clause("python")
        "tags LIKE '%,python,%'"
    """
    safe_tag = sanitize_string_value(tag)
    return f"tags LIKE '%,{safe_tag},%'"


def build_tag_clauses(tags: Union[str, List[str]]) -> str:
    """
    Build combined tag filter clauses (AND).

    Args:
        tags: Single tag or list of tags

    Returns:
        Combined AND clause for all tags

    Example:
        >>> build_tag_clauses(["python", "ml"])
        "tags LIKE '%,python,%' AND tags LIKE '%,ml,%'"
    """
    if isinstance(tags, str):
        tags = [tags]

    clauses = [build_tag_clause(tag) for tag in tags]
    return " AND ".join(clauses)


def build_filter_clause(filters: dict) -> str:
    """
    Build a complete filter clause from a dictionary.

    Handles special cases:
    - 'tags' key: Uses LIKE pattern matching
    - All other keys: Uses equality matching

    Args:
        filters: Dictionary of column -> value mappings

    Returns:
        Combined AND clause for all filters

    Raises:
        ValueError: If any column name is invalid

    Example:
        >>> build_filter_clause({"category": "work", "tags": ["python"]})
        "category = 'work' AND tags LIKE '%,python,%'"
    """
    clauses = []

    for key, value in filters.items():
        if key == "tags":
            # Tags stored as ",tag1,tag2," — match with LIKE '%,tag,%'
            tag_list = value if isinstance(value, list) else [value]
            for tag in tag_list:
                clauses.append(build_tag_clause(tag))
        else:
            clauses.append(build_eq_clause(key, value))

    return " AND ".join(clauses)
