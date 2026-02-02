"""
Auto-Tagging Module for CoreRag.

Automatically classify and tag documents during ingestion:
- Keyword-based classification
- Embedding similarity to tag exemplars
- Multi-label classification
- Hierarchical taxonomy support
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)


@dataclass
class Tag:
    """A classification tag."""
    name: str
    category: Optional[str] = None  # Hierarchical parent
    description: Optional[str] = None
    color: Optional[str] = None  # For UI display
    keywords: List[str] = field(default_factory=list)
    exemplar_texts: List[str] = field(default_factory=list)
    exemplar_embeddings: Optional[List[List[float]]] = None
    threshold: float = 0.5  # Confidence threshold for assignment

    def __hash__(self):
        return hash(self.name)


@dataclass
class TaggingResult:
    """Result of auto-tagging a document."""
    file_path: str
    assigned_tags: List[str]
    tag_scores: Dict[str, float]  # tag -> confidence score
    suggested_tags: List[str]  # Tags below threshold but close
    processing_time_ms: float
    method: str  # "keyword", "embedding", "hybrid"


@dataclass
class TaxonomyCategory:
    """A category in the taxonomy."""
    name: str
    description: Optional[str] = None
    tags: List[Tag] = field(default_factory=list)
    subcategories: List["TaxonomyCategory"] = field(default_factory=list)


class Taxonomy:
    """
    Hierarchical taxonomy for document classification.

    Supports:
    - Multi-level categories
    - Tag inheritance
    - Keyword and semantic matching
    """

    def __init__(self, taxonomy_file: Optional[Path] = None):
        """
        Initialize taxonomy.

        Args:
            taxonomy_file: JSON file with taxonomy definition
        """
        self.categories: List[TaxonomyCategory] = []
        self.tags: Dict[str, Tag] = {}  # flat lookup
        self._tag_keywords: Dict[str, Set[str]] = {}

        if taxonomy_file and taxonomy_file.exists():
            self._load_taxonomy(taxonomy_file)
        else:
            self._create_default_taxonomy()

    def add_tag(self, tag: Tag) -> None:
        """Add a tag to the taxonomy."""
        self.tags[tag.name.lower()] = tag
        if tag.keywords:
            self._tag_keywords[tag.name.lower()] = set(k.lower() for k in tag.keywords)

    def get_tag(self, name: str) -> Optional[Tag]:
        """Get tag by name."""
        return self.tags.get(name.lower())

    def get_all_tags(self) -> List[Tag]:
        """Get all tags."""
        return list(self.tags.values())

    def _load_taxonomy(self, file_path: Path) -> None:
        """Load taxonomy from JSON file."""
        try:
            with open(file_path) as f:
                data = json.load(f)

            for tag_data in data.get("tags", []):
                tag = Tag(
                    name=tag_data["name"],
                    category=tag_data.get("category"),
                    description=tag_data.get("description"),
                    color=tag_data.get("color"),
                    keywords=tag_data.get("keywords", []),
                    exemplar_texts=tag_data.get("exemplar_texts", []),
                    threshold=tag_data.get("threshold", 0.5),
                )
                self.add_tag(tag)

            logger.info(f"Loaded taxonomy with {len(self.tags)} tags")

        except Exception as e:
            logger.error(f"Failed to load taxonomy: {e}")
            self._create_default_taxonomy()

    def _create_default_taxonomy(self) -> None:
        """Create a default taxonomy for common document types."""
        default_tags = [
            # Document types
            Tag(
                name="meeting-notes",
                category="document-type",
                keywords=["meeting", "agenda", "minutes", "attendees", "action items"],
                threshold=0.4,
            ),
            Tag(
                name="technical-doc",
                category="document-type",
                keywords=["api", "documentation", "specification", "implementation", "architecture"],
                threshold=0.4,
            ),
            Tag(
                name="tutorial",
                category="document-type",
                keywords=["tutorial", "guide", "how to", "step by step", "learn"],
                threshold=0.4,
            ),
            Tag(
                name="research",
                category="document-type",
                keywords=["research", "study", "analysis", "findings", "hypothesis"],
                threshold=0.4,
            ),
            Tag(
                name="personal",
                category="document-type",
                keywords=["journal", "diary", "reflection", "thoughts", "personal"],
                threshold=0.6,
            ),

            # Topics
            Tag(
                name="python",
                category="technology",
                keywords=["python", "pip", "pytest", "django", "flask", "pandas", "numpy"],
                threshold=0.2,
            ),
            Tag(
                name="javascript",
                category="technology",
                keywords=["javascript", "js", "node", "npm", "react", "vue", "typescript"],
                threshold=0.2,
            ),
            Tag(
                name="machine-learning",
                category="technology",
                keywords=["machine learning", "ml", "deep learning", "neural network", "model", "training"],
                threshold=0.4,
            ),
            Tag(
                name="devops",
                category="technology",
                keywords=["docker", "kubernetes", "ci/cd", "deployment", "infrastructure", "aws", "cloud"],
                threshold=0.4,
            ),
            Tag(
                name="database",
                category="technology",
                keywords=["database", "sql", "postgresql", "mongodb", "redis", "query"],
                threshold=0.4,
            ),

            # Priority/Status
            Tag(
                name="todo",
                category="status",
                keywords=["todo", "task", "action", "pending", "backlog"],
                threshold=0.3,
            ),
            Tag(
                name="important",
                category="priority",
                keywords=["important", "critical", "urgent", "priority", "must"],
                threshold=0.4,
            ),
            Tag(
                name="archived",
                category="status",
                keywords=["archived", "deprecated", "old", "legacy", "outdated"],
                threshold=0.4,
            ),

            # Content type
            Tag(
                name="code-snippet",
                category="content-type",
                keywords=["```", "function", "class", "def ", "const ", "import "],
                threshold=0.3,
            ),
            Tag(
                name="reference",
                category="content-type",
                keywords=["reference", "cheatsheet", "quick reference", "lookup"],
                threshold=0.4,
            ),

            # Domain-specific
            Tag(
                name="human-resources",
                category="domain",
                keywords=["hr", "human resources", "phr", "sphr", "shrm", "employee",
                          "hiring", "onboarding", "performance review", "compensation",
                          "benefits", "talent", "workforce", "labor"],
                threshold=0.3,
            ),
            Tag(
                name="compliance",
                category="domain",
                keywords=["compliance", "regulation", "policy", "osha", "eeoc",
                          "ada", "fmla", "flsa", "hipaa", "gdpr", "audit",
                          "labor law", "employment law"],
                threshold=0.3,
            ),
            Tag(
                name="finance",
                category="domain",
                keywords=["finance", "budget", "revenue", "expense", "roi",
                          "accounting", "financial", "tax", "payroll", "invoice",
                          "profit", "cost"],
                threshold=0.3,
            ),
        ]

        for tag in default_tags:
            self.add_tag(tag)

        logger.info(f"Created default taxonomy with {len(self.tags)} tags")

    def save_taxonomy(self, file_path: Path) -> None:
        """Save taxonomy to JSON file."""
        data = {
            "tags": [
                {
                    "name": tag.name,
                    "category": tag.category,
                    "description": tag.description,
                    "color": tag.color,
                    "keywords": tag.keywords,
                    "exemplar_texts": tag.exemplar_texts,
                    "threshold": tag.threshold,
                }
                for tag in self.tags.values()
            ]
        }

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)


class KeywordTagger:
    """Tag documents based on keyword matching."""

    def __init__(self, taxonomy: Taxonomy):
        """
        Initialize keyword tagger.

        Args:
            taxonomy: Taxonomy with tags and keywords
        """
        self.taxonomy = taxonomy

    def tag(self, content: str, file_path: Optional[str] = None) -> TaggingResult:
        """
        Tag content based on keywords.

        Args:
            content: Document content
            file_path: Optional file path

        Returns:
            TaggingResult
        """
        import time
        start = time.time()

        content_lower = content.lower()
        word_count = len(content.split())

        scores: Dict[str, float] = {}

        for tag in self.taxonomy.get_all_tags():
            if not tag.keywords:
                continue

            # Count keyword matches
            matches = 0
            for keyword in tag.keywords:
                # Use word boundary matching for single words
                if " " not in keyword:
                    pattern = rf"\b{re.escape(keyword)}\b"
                    matches += len(re.findall(pattern, content_lower, re.IGNORECASE))
                else:
                    # Phrase matching
                    matches += content_lower.count(keyword.lower())

            if matches > 0:
                # Normalize by document length
                normalized_score = min(1.0, matches / (word_count / 100 + 1))
                # Apply keyword count factor
                keyword_factor = min(1.0, matches / len(tag.keywords))
                scores[tag.name] = (normalized_score + keyword_factor) / 2

        # Determine assigned vs suggested tags
        assigned = []
        suggested = []

        for tag_name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            tag = self.taxonomy.get_tag(tag_name)
            if tag and score >= tag.threshold:
                assigned.append(tag_name)
            elif tag and score >= tag.threshold * 0.7:
                suggested.append(tag_name)

        elapsed = (time.time() - start) * 1000

        return TaggingResult(
            file_path=file_path or "",
            assigned_tags=assigned,
            tag_scores=scores,
            suggested_tags=suggested[:5],
            processing_time_ms=elapsed,
            method="keyword",
        )


class EmbeddingTagger:
    """Tag documents using embedding similarity."""

    def __init__(
        self,
        taxonomy: Taxonomy,
        embedder: Callable[[str], List[float]],
        similarity_threshold: float = 0.7,
    ):
        """
        Initialize embedding tagger.

        Args:
            taxonomy: Taxonomy with tags
            embedder: Function to generate embeddings
            similarity_threshold: Min similarity for tag assignment
        """
        self.taxonomy = taxonomy
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self._tag_embeddings: Dict[str, List[List[float]]] = {}
        self._prepare_embeddings()

    def _prepare_embeddings(self) -> None:
        """Pre-compute embeddings for tag exemplars."""
        for tag in self.taxonomy.get_all_tags():
            if tag.exemplar_texts:
                embeddings = [self.embedder(text) for text in tag.exemplar_texts]
                self._tag_embeddings[tag.name] = embeddings

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def tag(self, content: str, file_path: Optional[str] = None) -> TaggingResult:
        """
        Tag content using embedding similarity.

        Args:
            content: Document content
            file_path: Optional file path

        Returns:
            TaggingResult
        """
        import time
        start = time.time()

        # Truncate content for embedding
        content_truncated = content[:8000]
        content_embedding = self.embedder(content_truncated)

        scores: Dict[str, float] = {}

        for tag_name, exemplar_embeddings in self._tag_embeddings.items():
            # Max similarity to any exemplar
            max_sim = 0.0
            for exemplar_emb in exemplar_embeddings:
                sim = self._cosine_similarity(content_embedding, exemplar_emb)
                max_sim = max(max_sim, sim)
            scores[tag_name] = max_sim

        # Determine assigned vs suggested
        assigned = []
        suggested = []

        for tag_name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            tag = self.taxonomy.get_tag(tag_name)
            if score >= self.similarity_threshold:
                assigned.append(tag_name)
            elif score >= self.similarity_threshold * 0.8:
                suggested.append(tag_name)

        elapsed = (time.time() - start) * 1000

        return TaggingResult(
            file_path=file_path or "",
            assigned_tags=assigned,
            tag_scores=scores,
            suggested_tags=suggested[:5],
            processing_time_ms=elapsed,
            method="embedding",
        )


class AutoTagger:
    """
    Main auto-tagger combining multiple strategies.

    Features:
    - Hybrid keyword + embedding tagging
    - Confidence-based assignment
    - Taxonomy management
    - Tag suggestions
    """

    def __init__(
        self,
        taxonomy: Optional[Taxonomy] = None,
        embedder: Optional[Callable[[str], List[float]]] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize auto-tagger.

        Args:
            taxonomy: Tag taxonomy (default taxonomy created if not provided)
            embedder: Embedding function for semantic tagging
            state_dir: Directory for state persistence
        """
        self.taxonomy = taxonomy or Taxonomy()
        self.embedder = embedder
        self.state_dir = state_dir or Path.home() / ".corerag" / "tagging"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Initialize taggers
        self.keyword_tagger = KeywordTagger(self.taxonomy)
        self.embedding_tagger = (
            EmbeddingTagger(self.taxonomy, embedder) if embedder else None
        )

        # Tag history for learning
        self._tag_history: List[Dict] = []
        self._load_history()

    def tag(
        self,
        content: str,
        file_path: Optional[str] = None,
        use_keywords: bool = True,
        use_embeddings: bool = True,
    ) -> TaggingResult:
        """
        Auto-tag content.

        Args:
            content: Document content
            file_path: Optional file path
            use_keywords: Use keyword matching
            use_embeddings: Use embedding similarity

        Returns:
            TaggingResult
        """
        import time
        start = time.time()

        all_scores: Dict[str, float] = {}
        methods_used = []

        # Keyword tagging
        if use_keywords:
            keyword_result = self.keyword_tagger.tag(content, file_path)
            for tag, score in keyword_result.tag_scores.items():
                all_scores[tag] = score
            methods_used.append("keyword")

        # Embedding tagging
        if use_embeddings and self.embedding_tagger:
            embedding_result = self.embedding_tagger.tag(content, file_path)
            for tag, score in embedding_result.tag_scores.items():
                # Combine scores (weighted average)
                if tag in all_scores:
                    all_scores[tag] = (all_scores[tag] * 0.4 + score * 0.6)
                else:
                    all_scores[tag] = score
            methods_used.append("embedding")

        # Determine final assignments
        assigned = []
        suggested = []

        for tag_name, score in sorted(all_scores.items(), key=lambda x: x[1], reverse=True):
            tag = self.taxonomy.get_tag(tag_name)
            if tag:
                if score >= tag.threshold:
                    assigned.append(tag_name)
                elif score >= tag.threshold * 0.7:
                    suggested.append(tag_name)

        elapsed = (time.time() - start) * 1000
        method = "+".join(methods_used) if methods_used else "none"

        result = TaggingResult(
            file_path=file_path or "",
            assigned_tags=assigned,
            tag_scores=all_scores,
            suggested_tags=suggested[:5],
            processing_time_ms=elapsed,
            method=method,
        )

        # Log for learning
        self._log_tagging(result)

        return result

    def tag_file(self, file_path: Path) -> TaggingResult:
        """
        Tag a file.

        Args:
            file_path: Path to file

        Returns:
            TaggingResult
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            return self.tag(content, str(file_path))
        except Exception as e:
            logger.error(f"Failed to tag file {file_path}: {e}")
            return TaggingResult(
                file_path=str(file_path),
                assigned_tags=[],
                tag_scores={},
                suggested_tags=[],
                processing_time_ms=0,
                method="error",
            )

    def tag_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_types: Optional[List[str]] = None,
    ) -> Dict[str, TaggingResult]:
        """
        Tag all files in a directory.

        Args:
            directory: Directory to scan
            recursive: Scan recursively
            file_types: File extensions to process

        Returns:
            Dict mapping file path to result
        """
        if file_types is None:
            file_types = ["md", "txt"]

        results: Dict[str, TaggingResult] = {}

        pattern = "**/*" if recursive else "*"
        for file_path in Path(directory).glob(pattern):
            if file_path.is_file():
                ext = file_path.suffix.lower().lstrip(".")
                if ext in file_types:
                    result = self.tag_file(file_path)
                    results[str(file_path)] = result

        return results

    def learn_from_feedback(
        self,
        file_path: str,
        correct_tags: List[str],
        incorrect_tags: Optional[List[str]] = None,
    ) -> None:
        """
        Learn from user feedback on tagging.

        Args:
            file_path: File that was tagged
            correct_tags: Tags that were correctly assigned
            incorrect_tags: Tags that were incorrectly assigned
        """
        feedback = {
            "file_path": file_path,
            "correct_tags": correct_tags,
            "incorrect_tags": incorrect_tags or [],
            "timestamp": datetime.now().isoformat(),
        }

        self._tag_history.append(feedback)
        self._save_history()

        # TODO: Use feedback to adjust thresholds or train classifier

    def get_tag_stats(self) -> Dict[str, Any]:
        """Get tagging statistics."""
        tag_counts: Dict[str, int] = {}

        for entry in self._tag_history:
            for tag in entry.get("correct_tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {
            "total_tagged": len(self._tag_history),
            "tag_distribution": tag_counts,
            "available_tags": len(self.taxonomy.get_all_tags()),
        }

    def _log_tagging(self, result: TaggingResult) -> None:
        """Log tagging result for analysis."""
        if result.assigned_tags:
            entry = {
                "file_path": result.file_path,
                "tags": result.assigned_tags,
                "scores": {k: round(v, 3) for k, v in result.tag_scores.items() if v > 0.1},
                "method": result.method,
                "timestamp": datetime.now().isoformat(),
            }
            self._tag_history.append(entry)

            # Periodic save
            if len(self._tag_history) % 10 == 0:
                self._save_history()

    def _load_history(self) -> None:
        """Load tag history from disk."""
        history_file = self.state_dir / "tag_history.json"
        if history_file.exists():
            try:
                with open(history_file) as f:
                    self._tag_history = json.load(f)
                logger.info(f"Loaded {len(self._tag_history)} tag history entries")
            except Exception as e:
                logger.warning(f"Failed to load tag history: {e}")

    def _save_history(self) -> None:
        """Save tag history to disk."""
        history_file = self.state_dir / "tag_history.json"
        try:
            # Keep last 1000 entries
            to_save = self._tag_history[-1000:]
            with open(history_file, "w") as f:
                json.dump(to_save, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save tag history: {e}")


# Convenience function
def auto_tag(content: str, taxonomy_file: Optional[Path] = None) -> List[str]:
    """
    Quick auto-tag for content.

    Args:
        content: Document content
        taxonomy_file: Optional taxonomy file

    Returns:
        List of assigned tags
    """
    taxonomy = Taxonomy(taxonomy_file) if taxonomy_file else Taxonomy()
    tagger = AutoTagger(taxonomy)
    result = tagger.tag(content)
    return result.assigned_tags
