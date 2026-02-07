"""Vault-wide backlink generation for Obsidian exports.

Scans existing vault files to find linkable terms in content,
and queries the knowledge graph for entity-based related documents.
"""

import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum term length to avoid noise from short words
MIN_TERM_LENGTH = 3

# Cache TTL in seconds (5 minutes)
CACHE_TTL = 300


class BacklinkGenerator:
    """Generates Obsidian [[wikilinks]] from vault file index and knowledge graph."""

    def __init__(self, vault_path: Path, graph_db_path: Optional[Path] = None):
        self.vault_path = vault_path
        self.graph_db_path = graph_db_path
        self._vault_index: dict[str, str] = {}  # lowercase stem -> original stem
        self._cache_time: float = 0

    def _refresh_vault_index(self) -> None:
        """Scan vault for markdown files and build stem index."""
        now = time.time()
        if self._vault_index and (now - self._cache_time) < CACHE_TTL:
            return

        self._vault_index = {}
        if not self.vault_path.exists():
            return

        for md_file in self.vault_path.rglob("*.md"):
            stem = md_file.stem
            if len(stem) >= MIN_TERM_LENGTH:
                self._vault_index[stem.lower()] = stem

        self._cache_time = now
        logger.debug(f"Vault index refreshed: {len(self._vault_index)} files")

    def find_linkable_terms(self, content: str, exclude_stem: str = "") -> dict[str, str]:
        """Find terms in content that match existing vault filenames.

        Returns dict mapping original term in content -> wikilink format.
        Skips matches inside existing [[wikilinks]] and code blocks.
        """
        self._refresh_vault_index()
        linkable: dict[str, str] = {}
        exclude_lower = exclude_stem.lower()

        # Extract regions to skip: existing wikilinks, code blocks, YAML frontmatter
        skip_regions = self._get_skip_regions(content)

        for stem_lower, stem_original in self._vault_index.items():
            if stem_lower == exclude_lower:
                continue

            # Word boundary match, case-insensitive
            pattern = re.compile(rf"\b({re.escape(stem_original)})\b", re.IGNORECASE)
            for match in pattern.finditer(content):
                start = match.start()
                # Skip if inside a protected region
                if any(s <= start < e for s, e in skip_regions):
                    continue
                original_text = match.group(1)
                if original_text not in linkable:
                    linkable[original_text] = f"[[{stem_original}|{original_text}]]"
                break  # Only first occurrence per term

        return linkable

    def apply_inline_links(self, content: str, exclude_stem: str = "") -> str:
        """Apply inline wikilinks to content, replacing first occurrence of each term."""
        linkable = self.find_linkable_terms(content, exclude_stem)
        if not linkable:
            return content

        result = content
        for original, wikilink in linkable.items():
            # Replace only first occurrence, avoiding existing wikilinks
            result = self._safe_replace_first(result, original, wikilink)

        return result

    def get_related_from_graph(self, document_id: str, limit: int = 10) -> list[str]:
        """Get related document links from knowledge graph entities.

        Returns list of wikilinks like ["[[SomeNote]]", ...].
        """
        if not self.graph_db_path or not self.graph_db_path.exists():
            return []

        self._refresh_vault_index()

        try:
            conn = sqlite3.connect(self.graph_db_path)
            cursor = conn.cursor()

            # Find documents sharing entities with this one
            cursor.execute(
                """
                SELECT e2.document_id, GROUP_CONCAT(DISTINCT e2.name)
                FROM entities e1
                JOIN entities e2 ON LOWER(e1.name) = LOWER(e2.name)
                    AND e1.document_id != e2.document_id
                WHERE e1.document_id = ?
                GROUP BY e2.document_id
                ORDER BY COUNT(DISTINCT e2.name) DESC
                LIMIT ?
                """,
                (document_id, limit * 2),
            )

            rows = cursor.fetchall()
            conn.close()

            # Match shared entities against vault files
            links: list[str] = []
            for _doc_id, entity_names in rows:
                entities = entity_names.split(",") if entity_names else []
                for entity in entities:
                    entity_lower = entity.strip().lower()
                    if entity_lower in self._vault_index:
                        stem = self._vault_index[entity_lower]
                        link = f"[[{stem}]]"
                        if link not in links:
                            links.append(link)

            return links[:limit]

        except Exception as e:
            logger.debug(f"Graph backlink lookup failed: {e}")
            return []

    def generate_related_section(self, document_id: str, limit: int = 10) -> str:
        """Generate a '## Related Notes' section from graph data."""
        links = self.get_related_from_graph(document_id, limit)
        if not links:
            return ""

        section = "\n\n---\n\n## Related Notes\n"
        section += "\n".join(f"- {link}" for link in links)
        return section

    @staticmethod
    def _get_skip_regions(content: str) -> list[tuple[int, int]]:
        """Find regions to skip: YAML frontmatter, wikilinks, code blocks."""
        regions: list[tuple[int, int]] = []

        # YAML frontmatter (at start of content)
        fm_match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
        if fm_match:
            regions.append((fm_match.start(), fm_match.end()))

        # Existing wikilinks [[...]]
        for match in re.finditer(r"\[\[.*?\]\]", content):
            regions.append((match.start(), match.end()))

        # Fenced code blocks ```...```
        for match in re.finditer(r"```.*?```", content, re.DOTALL):
            regions.append((match.start(), match.end()))

        # Inline code `...`
        for match in re.finditer(r"`[^`]+`", content):
            regions.append((match.start(), match.end()))

        return regions

    @staticmethod
    def _safe_replace_first(content: str, old: str, new: str) -> str:
        """Replace first occurrence of old with new, skipping wikilinks and code."""
        # Find all skip regions in current content
        skip_regions = BacklinkGenerator._get_skip_regions(content)

        pattern = re.compile(re.escape(old))
        for match in pattern.finditer(content):
            start = match.start()
            if any(s <= start < e for s, e in skip_regions):
                continue
            # Found a valid replacement point
            return content[:start] + new + content[start + len(old) :]

        return content

    @staticmethod
    def compute_document_id(text: str) -> str:
        """Compute document_id hash the same way executor.py does."""
        return hashlib.sha256(text[:5000].encode()).hexdigest()[:16]
