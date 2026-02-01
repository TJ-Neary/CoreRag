"""
.pkmignore File Parser

Parses gitignore-style patterns to determine which files should be excluded
from indexing. Supports nested .pkmignore files (like .gitignore).
"""

import fnmatch
import re
from pathlib import Path
from typing import List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class IgnorePattern:
    """A single ignore pattern with metadata."""

    def __init__(self, pattern: str, negation: bool = False, directory_only: bool = False):
        self.original = pattern
        self.negation = negation
        self.directory_only = directory_only

        # Convert gitignore pattern to regex
        self.regex = self._pattern_to_regex(pattern)

    def _pattern_to_regex(self, pattern: str) -> re.Pattern:
        """Convert gitignore pattern to compiled regex."""
        # Handle leading/trailing slashes
        anchored = pattern.startswith("/")
        if anchored:
            pattern = pattern[1:]

        if pattern.endswith("/"):
            pattern = pattern[:-1]
            self.directory_only = True

        # Escape special regex chars except * and ?
        pattern = re.escape(pattern)

        # Convert gitignore wildcards to regex
        pattern = pattern.replace(r"\*\*", "<<<DOUBLESTAR>>>")
        pattern = pattern.replace(r"\*", "[^/]*")
        pattern = pattern.replace(r"\?", "[^/]")
        pattern = pattern.replace("<<<DOUBLESTAR>>>", ".*")

        # Anchor pattern
        if anchored:
            pattern = "^" + pattern
        else:
            pattern = "(^|/)" + pattern

        pattern = pattern + "(/|$)"

        return re.compile(pattern)

    def matches(self, path: str, is_dir: bool = False) -> bool:
        """Check if path matches this pattern."""
        if self.directory_only and not is_dir:
            return False
        return bool(self.regex.search(path))


class PKMIgnore:
    """
    Parser for .pkmignore files.

    Supports:
    - Standard gitignore patterns
    - Negation with !
    - Directory-only patterns with trailing /
    - Comments with #
    - Nested .pkmignore files
    """

    IGNORE_FILENAME = ".pkmignore"

    def __init__(self, root_path: Optional[Path] = None):
        """
        Initialize ignore parser.

        Args:
            root_path: Root directory to search for .pkmignore files
        """
        self.root_path = Path(root_path) if root_path else Path.cwd()
        self.patterns: List[IgnorePattern] = []
        self._load_patterns()

    def _load_patterns(self):
        """Load patterns from root .pkmignore and any nested ones."""
        # Load root .pkmignore
        root_ignore = self.root_path / self.IGNORE_FILENAME
        if root_ignore.exists():
            self._load_file(root_ignore, "")
            logger.info(f"Loaded {len(self.patterns)} patterns from {root_ignore}")

    def _load_file(self, path: Path, prefix: str):
        """Load patterns from a single .pkmignore file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n\r")

                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue

                    # Skip whitespace-only lines
                    if not line.strip():
                        continue

                    # Check for negation
                    negation = line.startswith("!")
                    if negation:
                        line = line[1:]

                    # Add prefix for nested .pkmignore
                    if prefix and not line.startswith("/"):
                        line = prefix + "/" + line

                    self.patterns.append(IgnorePattern(
                        pattern=line,
                        negation=negation
                    ))
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")

    def add_nested_ignore(self, ignore_path: Path):
        """Add patterns from a nested .pkmignore file."""
        if ignore_path.exists():
            prefix = str(ignore_path.parent.relative_to(self.root_path))
            self._load_file(ignore_path, prefix)

    def is_ignored(self, path: Path, is_dir: Optional[bool] = None) -> bool:
        """
        Check if a path should be ignored.

        Args:
            path: Path to check (absolute or relative to root)
            is_dir: Whether path is a directory (auto-detected if None)

        Returns:
            True if path should be ignored
        """
        # Make path relative to root
        try:
            if path.is_absolute():
                rel_path = path.relative_to(self.root_path)
            else:
                rel_path = path
        except ValueError:
            # Path is outside root, don't ignore
            return False

        path_str = str(rel_path)

        # Auto-detect if directory
        if is_dir is None:
            full_path = self.root_path / rel_path
            is_dir = full_path.is_dir() if full_path.exists() else False

        # Check patterns (last match wins, like gitignore)
        ignored = False
        for pattern in self.patterns:
            if pattern.matches(path_str, is_dir):
                ignored = not pattern.negation

        return ignored

    def filter_paths(self, paths: List[Path]) -> List[Path]:
        """
        Filter a list of paths, removing ignored ones.

        Args:
            paths: List of paths to filter

        Returns:
            Paths that are NOT ignored
        """
        return [p for p in paths if not self.is_ignored(p)]

    def get_ignored_count(self, directory: Path) -> int:
        """Count how many files would be ignored in a directory."""
        count = 0
        for path in directory.rglob("*"):
            if self.is_ignored(path):
                count += 1
        return count


class IgnoreChecker:
    """
    Efficient ignore checking with caching.

    Caches directory-level decisions to avoid redundant pattern matching.
    """

    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.pkmignore = PKMIgnore(root_path)
        self._cache: dict = {}

    def should_process(self, path: Path) -> bool:
        """
        Check if a file should be processed (not ignored).

        Uses caching for performance on large directories.
        """
        # Check cache
        path_str = str(path)
        if path_str in self._cache:
            return self._cache[path_str]

        # Check if any parent directory is ignored
        try:
            rel_path = path.relative_to(self.root_path)
            parts = rel_path.parts

            for i in range(len(parts)):
                partial = Path(*parts[:i + 1])
                partial_str = str(partial)

                if partial_str in self._cache:
                    if not self._cache[partial_str]:
                        self._cache[path_str] = False
                        return False
                else:
                    is_ignored = self.pkmignore.is_ignored(partial)
                    self._cache[partial_str] = not is_ignored
                    if is_ignored:
                        self._cache[path_str] = False
                        return False

        except ValueError:
            pass

        # Check the file itself
        result = not self.pkmignore.is_ignored(path)
        self._cache[path_str] = result
        return result

    def clear_cache(self):
        """Clear the decision cache."""
        self._cache.clear()


def should_ignore(path: Path, root: Path) -> bool:
    """
    Convenience function to check if a file should be ignored.

    Args:
        path: Path to check
        root: Root directory containing .pkmignore

    Returns:
        True if file should be ignored
    """
    return PKMIgnore(root).is_ignored(path)
