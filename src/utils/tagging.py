"""
Tagging workflow for PKM.

Manage document tags with both manual and AI-powered tagging.
"""

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Tag:
    """A tag definition."""
    name: str
    color: str = "#808080"
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    use_count: int = 0
    parent: Optional[str] = None  # For hierarchical tags
    aliases: List[str] = field(default_factory=list)  # Alternative names


@dataclass
class TagSuggestion:
    """A suggested tag for a document."""
    tag: str
    confidence: float  # 0.0 to 1.0
    source: str  # "content", "title", "similar_docs", "user_history"
    reason: str


class TagManager:
    """
    Manage tags across the knowledge base.

    Features:
    - Manual tagging
    - AI-powered tag suggestions
    - Tag hierarchy (parent/child)
    - Tag aliases and merging
    - Tag-based search
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize tag manager.

        Args:
            state_dir: Directory for tag storage
        """
        self.state_dir = state_dir or Path.home() / ".pkm" / "tags"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._tags: Dict[str, Tag] = {}
        self._doc_tags: Dict[str, Set[str]] = {}  # doc_id -> set of tags
        self._tag_docs: Dict[str, Set[str]] = {}  # tag -> set of doc_ids

        self._load_state()

    # Tag CRUD operations

    def create_tag(
        self,
        name: str,
        color: str = "#808080",
        description: str = "",
        parent: Optional[str] = None,
        aliases: Optional[List[str]] = None
    ) -> Tag:
        """
        Create a new tag.

        Args:
            name: Tag name (lowercase, no spaces)
            color: Display color
            description: Tag description
            parent: Parent tag for hierarchy
            aliases: Alternative names

        Returns:
            Created tag
        """
        # Normalize tag name
        name = self._normalize_tag(name)

        if name in self._tags:
            return self._tags[name]

        tag = Tag(
            name=name,
            color=color,
            description=description,
            parent=parent,
            aliases=aliases or []
        )

        self._tags[name] = tag
        self._tag_docs[name] = set()
        self._save_state()

        logger.info(f"Created tag: {name}")

        return tag

    def get_tag(self, name: str) -> Optional[Tag]:
        """Get a tag by name or alias."""
        name = self._normalize_tag(name)

        if name in self._tags:
            return self._tags[name]

        # Check aliases
        for tag in self._tags.values():
            if name in tag.aliases:
                return tag

        return None

    def get_all_tags(self) -> List[Tag]:
        """Get all tags sorted by use count."""
        return sorted(self._tags.values(), key=lambda t: t.use_count, reverse=True)

    def get_popular_tags(self, limit: int = 20) -> List[Tag]:
        """Get most used tags."""
        return self.get_all_tags()[:limit]

    def update_tag(
        self,
        name: str,
        color: Optional[str] = None,
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None
    ) -> bool:
        """Update tag properties."""
        if tag := self._tags.get(self._normalize_tag(name)):
            if color is not None:
                tag.color = color
            if description is not None:
                tag.description = description
            if aliases is not None:
                tag.aliases = aliases
            self._save_state()
            return True
        return False

    def delete_tag(self, name: str, reassign_to: Optional[str] = None) -> bool:
        """
        Delete a tag.

        Args:
            name: Tag to delete
            reassign_to: Optionally reassign docs to another tag

        Returns:
            True if deleted
        """
        name = self._normalize_tag(name)

        if name not in self._tags:
            return False

        # Reassign or remove from documents
        affected_docs = self._tag_docs.get(name, set()).copy()

        for doc_id in affected_docs:
            self._doc_tags[doc_id].discard(name)
            if reassign_to:
                self.add_tag(doc_id, reassign_to)

        del self._tags[name]
        del self._tag_docs[name]

        self._save_state()
        logger.info(f"Deleted tag: {name}")

        return True

    def merge_tags(self, source: str, target: str) -> int:
        """
        Merge source tag into target.

        Args:
            source: Tag to merge from
            target: Tag to merge into

        Returns:
            Number of documents affected
        """
        source = self._normalize_tag(source)
        target = self._normalize_tag(target)

        if source not in self._tags or target not in self._tags:
            return 0

        affected = 0
        source_docs = self._tag_docs.get(source, set()).copy()

        for doc_id in source_docs:
            self.remove_tag(doc_id, source)
            self.add_tag(doc_id, target)
            affected += 1

        # Add source as alias
        self._tags[target].aliases.append(source)

        # Delete source tag
        del self._tags[source]
        del self._tag_docs[source]

        self._save_state()
        logger.info(f"Merged {source} into {target}, {affected} docs affected")

        return affected

    # Document tagging

    def add_tag(self, document_id: str, tag_name: str) -> bool:
        """
        Add a tag to a document.

        Args:
            document_id: Document to tag
            tag_name: Tag to add

        Returns:
            True if added
        """
        tag_name = self._normalize_tag(tag_name)

        # Create tag if doesn't exist
        if tag_name not in self._tags:
            self.create_tag(tag_name)

        # Add to document
        if document_id not in self._doc_tags:
            self._doc_tags[document_id] = set()

        if tag_name not in self._doc_tags[document_id]:
            self._doc_tags[document_id].add(tag_name)
            self._tag_docs[tag_name].add(document_id)
            self._tags[tag_name].use_count += 1
            self._save_state()
            return True

        return False

    def remove_tag(self, document_id: str, tag_name: str) -> bool:
        """Remove a tag from a document."""
        tag_name = self._normalize_tag(tag_name)

        if document_id in self._doc_tags and tag_name in self._doc_tags[document_id]:
            self._doc_tags[document_id].discard(tag_name)
            self._tag_docs[tag_name].discard(document_id)
            self._tags[tag_name].use_count = max(0, self._tags[tag_name].use_count - 1)
            self._save_state()
            return True

        return False

    def set_tags(self, document_id: str, tags: List[str]) -> None:
        """Set all tags for a document (replaces existing)."""
        # Remove old tags
        old_tags = self._doc_tags.get(document_id, set()).copy()
        for tag in old_tags:
            self.remove_tag(document_id, tag)

        # Add new tags
        for tag in tags:
            self.add_tag(document_id, tag)

    def get_document_tags(self, document_id: str) -> List[Tag]:
        """Get all tags for a document."""
        tag_names = self._doc_tags.get(document_id, set())
        return [self._tags[t] for t in tag_names if t in self._tags]

    def get_documents_by_tag(self, tag_name: str) -> Set[str]:
        """Get all documents with a specific tag."""
        tag_name = self._normalize_tag(tag_name)
        return self._tag_docs.get(tag_name, set()).copy()

    def get_documents_by_tags(
        self,
        tags: List[str],
        match_all: bool = True
    ) -> Set[str]:
        """
        Get documents matching multiple tags.

        Args:
            tags: Tags to match
            match_all: If True, docs must have ALL tags. If False, ANY tag.

        Returns:
            Set of matching document IDs
        """
        tags = [self._normalize_tag(t) for t in tags]

        if not tags:
            return set()

        doc_sets = [self._tag_docs.get(t, set()) for t in tags]

        if match_all:
            return set.intersection(*doc_sets) if doc_sets else set()
        else:
            return set.union(*doc_sets) if doc_sets else set()

    # AI-powered suggestions

    def suggest_tags(
        self,
        content: str,
        title: str = "",
        existing_tags: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[TagSuggestion]:
        """
        Suggest tags for content.

        Args:
            content: Document content
            title: Document title
            existing_tags: Tags already applied
            limit: Maximum suggestions

        Returns:
            List of tag suggestions
        """
        suggestions = []
        existing = set(existing_tags or [])

        # Rule-based suggestions from content
        suggestions.extend(self._suggest_from_content(content, existing))

        # Suggestions from title
        suggestions.extend(self._suggest_from_title(title, existing))

        # Suggestions from existing tag usage patterns
        suggestions.extend(self._suggest_from_patterns(existing))

        # Deduplicate and sort by confidence
        seen = set()
        unique_suggestions = []
        for s in sorted(suggestions, key=lambda x: x.confidence, reverse=True):
            if s.tag not in seen and s.tag not in existing:
                seen.add(s.tag)
                unique_suggestions.append(s)

        return unique_suggestions[:limit]

    def _suggest_from_content(
        self,
        content: str,
        existing: Set[str]
    ) -> List[TagSuggestion]:
        """Suggest tags based on content keywords."""
        suggestions = []
        content_lower = content.lower()

        # Check existing tags for matches
        for tag in self._tags.values():
            if tag.name in existing:
                continue

            # Check tag name and aliases
            terms = [tag.name] + tag.aliases
            for term in terms:
                if term in content_lower:
                    # Count occurrences
                    count = content_lower.count(term)
                    confidence = min(0.9, 0.5 + (count * 0.1))

                    suggestions.append(TagSuggestion(
                        tag=tag.name,
                        confidence=confidence,
                        source="content",
                        reason=f"Found '{term}' {count} time(s)"
                    ))
                    break

        return suggestions

    def _suggest_from_title(
        self,
        title: str,
        existing: Set[str]
    ) -> List[TagSuggestion]:
        """Suggest tags based on title."""
        suggestions = []
        title_lower = title.lower()

        for tag in self._tags.values():
            if tag.name in existing:
                continue

            if tag.name in title_lower:
                suggestions.append(TagSuggestion(
                    tag=tag.name,
                    confidence=0.85,
                    source="title",
                    reason=f"Found in title"
                ))

        return suggestions

    def _suggest_from_patterns(
        self,
        existing: Set[str]
    ) -> List[TagSuggestion]:
        """Suggest tags that commonly appear with existing tags."""
        if not existing:
            return []

        suggestions = []
        co_occurrence = Counter()

        # Find tags that co-occur with existing tags
        for tag in existing:
            docs = self._tag_docs.get(tag, set())
            for doc_id in docs:
                doc_tags = self._doc_tags.get(doc_id, set())
                for other_tag in doc_tags:
                    if other_tag not in existing:
                        co_occurrence[other_tag] += 1

        # Suggest most common co-occurring tags
        for tag, count in co_occurrence.most_common(5):
            confidence = min(0.8, 0.3 + (count * 0.1))
            suggestions.append(TagSuggestion(
                tag=tag,
                confidence=confidence,
                source="similar_docs",
                reason=f"Often used with {', '.join(list(existing)[:3])}"
            ))

        return suggestions

    def auto_tag(
        self,
        document_id: str,
        content: str,
        title: str = "",
        min_confidence: float = 0.7
    ) -> List[str]:
        """
        Automatically tag a document.

        Args:
            document_id: Document to tag
            content: Document content
            title: Document title
            min_confidence: Minimum confidence to apply tag

        Returns:
            List of applied tags
        """
        existing = list(self._doc_tags.get(document_id, set()))
        suggestions = self.suggest_tags(content, title, existing)

        applied = []
        for suggestion in suggestions:
            if suggestion.confidence >= min_confidence:
                self.add_tag(document_id, suggestion.tag)
                applied.append(suggestion.tag)

        if applied:
            logger.info(f"Auto-tagged {document_id} with: {applied}")

        return applied

    # Tag hierarchy

    def get_tag_tree(self) -> List[Dict]:
        """Get hierarchical tag structure."""
        def build_tree(parent: Optional[str]) -> List[Dict]:
            children = [t for t in self._tags.values() if t.parent == parent]
            return [
                {
                    "name": t.name,
                    "color": t.color,
                    "use_count": t.use_count,
                    "children": build_tree(t.name)
                }
                for t in sorted(children, key=lambda x: x.use_count, reverse=True)
            ]

        return build_tree(None)

    def get_related_tags(self, tag_name: str, limit: int = 5) -> List[Tag]:
        """Get tags that frequently co-occur with this tag."""
        tag_name = self._normalize_tag(tag_name)

        if tag_name not in self._tags:
            return []

        co_occurrence = Counter()
        docs = self._tag_docs.get(tag_name, set())

        for doc_id in docs:
            for other_tag in self._doc_tags.get(doc_id, set()):
                if other_tag != tag_name:
                    co_occurrence[other_tag] += 1

        related = []
        for other_tag, _ in co_occurrence.most_common(limit):
            if other_tag in self._tags:
                related.append(self._tags[other_tag])

        return related

    @staticmethod
    def _normalize_tag(name: str) -> str:
        """Normalize a tag name."""
        # Lowercase, replace spaces with hyphens, remove special chars
        name = name.lower().strip()
        name = re.sub(r'\s+', '-', name)
        name = re.sub(r'[^a-z0-9\-_]', '', name)
        return name

    def _load_state(self) -> None:
        """Load state from disk."""
        tags_file = self.state_dir / "tags.json"
        docs_file = self.state_dir / "doc_tags.json"

        if tags_file.exists():
            try:
                with open(tags_file) as f:
                    data = json.load(f)

                for name, tdata in data.get("tags", {}).items():
                    self._tags[name] = Tag(**tdata)
                    self._tag_docs[name] = set()

            except Exception as e:
                logger.error(f"Failed to load tags: {e}")

        if docs_file.exists():
            try:
                with open(docs_file) as f:
                    data = json.load(f)

                for doc_id, tags in data.get("documents", {}).items():
                    self._doc_tags[doc_id] = set(tags)
                    for tag in tags:
                        if tag in self._tag_docs:
                            self._tag_docs[tag].add(doc_id)

            except Exception as e:
                logger.error(f"Failed to load doc tags: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        tags_file = self.state_dir / "tags.json"
        docs_file = self.state_dir / "doc_tags.json"

        # Save tags
        with open(tags_file, "w") as f:
            json.dump({
                "tags": {
                    name: {
                        "name": t.name,
                        "color": t.color,
                        "description": t.description,
                        "created_at": t.created_at,
                        "use_count": t.use_count,
                        "parent": t.parent,
                        "aliases": t.aliases
                    }
                    for name, t in self._tags.items()
                }
            }, f, indent=2)

        # Save doc-tag mappings
        with open(docs_file, "w") as f:
            json.dump({
                "documents": {
                    doc_id: list(tags)
                    for doc_id, tags in self._doc_tags.items()
                }
            }, f, indent=2)
