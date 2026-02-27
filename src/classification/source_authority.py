"""
Source Authority Classifier

Classifies documents by reliability level based on file metadata,
category, and explicit user tags. Used to boost/filter search results
by trustworthiness.
"""

import re
from enum import Enum


class SourceAuthority(str, Enum):
    """Reliability classification for source documents."""

    OFFICIAL = "official"  # Government, legal, regulatory
    PROFESSIONAL = "professional"  # Corporate, certified, peer-reviewed
    EDUCATIONAL = "educational"  # Textbooks, courses, tutorials
    PERSONAL = "personal"  # Notes, journals, drafts
    UNKNOWN = "unknown"  # Default when classification fails


# Category → authority mapping
_CATEGORY_MAP: dict[str, SourceAuthority] = {
    "legal": SourceAuthority.OFFICIAL,
    "government": SourceAuthority.OFFICIAL,
    "tax": SourceAuthority.OFFICIAL,
    "regulatory": SourceAuthority.OFFICIAL,
    "compliance": SourceAuthority.OFFICIAL,
    "medical": SourceAuthority.PROFESSIONAL,
    "financial": SourceAuthority.PROFESSIONAL,
    "professional": SourceAuthority.PROFESSIONAL,
    "certification": SourceAuthority.PROFESSIONAL,
    "work": SourceAuthority.PROFESSIONAL,
    "hr": SourceAuthority.PROFESSIONAL,
    "education": SourceAuthority.EDUCATIONAL,
    "study": SourceAuthority.EDUCATIONAL,
    "course": SourceAuthority.EDUCATIONAL,
    "textbook": SourceAuthority.EDUCATIONAL,
    "tutorial": SourceAuthority.EDUCATIONAL,
    "reference": SourceAuthority.EDUCATIONAL,
    "notes": SourceAuthority.PERSONAL,
    "journal": SourceAuthority.PERSONAL,
    "draft": SourceAuthority.PERSONAL,
    "personal": SourceAuthority.PERSONAL,
}

# Tag keywords → authority
_TAG_MAP: dict[str, SourceAuthority] = {
    "official": SourceAuthority.OFFICIAL,
    "gov": SourceAuthority.OFFICIAL,
    "legal": SourceAuthority.OFFICIAL,
    "cert": SourceAuthority.PROFESSIONAL,
    "peer-reviewed": SourceAuthority.PROFESSIONAL,
    "published": SourceAuthority.PROFESSIONAL,
    "textbook": SourceAuthority.EDUCATIONAL,
    "study": SourceAuthority.EDUCATIONAL,
    "course": SourceAuthority.EDUCATIONAL,
    "draft": SourceAuthority.PERSONAL,
    "notes": SourceAuthority.PERSONAL,
}

# File extension patterns
_EXTENSION_MAP: dict[str, SourceAuthority] = {
    ".pdf": SourceAuthority.PROFESSIONAL,  # Often formal documents
    ".docx": SourceAuthority.PROFESSIONAL,
    ".txt": SourceAuthority.PERSONAL,
    ".md": SourceAuthority.PERSONAL,
}


class SourceAuthorityClassifier:
    """Classifies document source authority based on metadata signals."""

    def classify(self, metadata: dict) -> SourceAuthority:
        """Classify source authority from document metadata.

        Priority: explicit tags > category > file extension > default.

        Args:
            metadata: Document metadata dict with optional keys:
                - tags (list[str]): collection tags
                - category (str): AI-classified category
                - source_path (str): file path or name
                - file_type (str): file extension or type

        Returns:
            SourceAuthority enum value.
        """
        # 1. Check explicit tags (highest priority)
        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.strip(",").split(",") if t.strip()]

        for tag in tags:
            tag_lower = tag.lower()
            for keyword, authority in _TAG_MAP.items():
                if keyword in tag_lower:
                    return authority

        # 2. Check category
        category = (metadata.get("category") or "").lower()
        if category in _CATEGORY_MAP:
            return _CATEGORY_MAP[category]
        # Partial match
        for cat_key, authority in _CATEGORY_MAP.items():
            if cat_key in category:
                return authority

        # 3. Check file extension
        source_path = metadata.get("source_path") or metadata.get("file_name", "")
        ext_match = re.search(r"\.\w+$", source_path)
        if ext_match:
            ext = ext_match.group().lower()
            if ext in _EXTENSION_MAP:
                return _EXTENSION_MAP[ext]

        return SourceAuthority.UNKNOWN
