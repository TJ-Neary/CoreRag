"""
Deduplication system for CoreRag.

Detects and handles duplicate files and content at multiple levels:
- File hash: Exact byte-for-byte duplicates
- Content hash: Same text content, different files
- Semantic similarity: Conceptually similar content
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DuplicateInfo:
    """Information about a detected duplicate."""
    original_path: str
    original_doc_id: str
    duplicate_type: str  # "file_hash", "content_hash", "semantic"
    similarity_score: Optional[float] = None
    first_seen: Optional[str] = None


@dataclass
class DeduplicationResult:
    """Result of deduplication check."""
    is_duplicate: bool
    duplicate_type: Optional[str] = None
    original_doc_id: Optional[str] = None
    original_path: Optional[str] = None
    similarity_score: Optional[float] = None
    recommendation: str = "process"  # "process", "skip", "review"


class DeduplicationManager:
    """
    Manages deduplication across the knowledge base.

    Usage:
        dedup = DeduplicationManager()

        # Check before processing
        result = dedup.check_file(file_path)
        if result.is_duplicate:
            if result.recommendation == "skip":
                skip_file(file_path)
            elif result.recommendation == "review":
                queue_for_review(file_path)
        else:
            process_file(file_path)
            dedup.register_file(file_path, doc_id, content_hash)
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        semantic_threshold: float = 0.95
    ):
        """
        Initialize deduplication manager.

        Args:
            state_dir: Directory to store dedup state
            semantic_threshold: Similarity threshold for semantic duplicates
        """
        self.state_dir = state_dir or Path.home() / ".corerag" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.semantic_threshold = semantic_threshold

        # In-memory caches (loaded from disk)
        self._file_hashes: Dict[str, str] = {}  # hash -> first file path
        self._content_hashes: Dict[str, str] = {}  # hash -> doc_id
        self._file_to_doc: Dict[str, str] = {}  # file path -> doc_id

        self._load_state()

    def check_file(self, file_path: Path) -> DeduplicationResult:
        """
        Check if a file is a duplicate.

        Args:
            file_path: Path to file to check

        Returns:
            DeduplicationResult with duplicate info and recommendation
        """
        file_hash = self.compute_file_hash(file_path)

        # Level 1: Exact file hash match
        if file_hash in self._file_hashes:
            original_path = self._file_hashes[file_hash]
            original_doc_id = self._file_to_doc.get(original_path)

            logger.info(f"Exact duplicate found: {file_path} == {original_path}")

            return DeduplicationResult(
                is_duplicate=True,
                duplicate_type="file_hash",
                original_doc_id=original_doc_id,
                original_path=original_path,
                similarity_score=1.0,
                recommendation="skip"
            )

        return DeduplicationResult(
            is_duplicate=False,
            recommendation="process"
        )

    def check_content(
        self,
        content: str,
        file_path: Optional[Path] = None
    ) -> DeduplicationResult:
        """
        Check if content is a duplicate.

        Args:
            content: Text content to check
            file_path: Optional file path for logging

        Returns:
            DeduplicationResult with duplicate info
        """
        content_hash = self.compute_content_hash(content)

        # Level 2: Content hash match
        if content_hash in self._content_hashes:
            original_doc_id = self._content_hashes[content_hash]

            logger.info(f"Content duplicate found for {file_path}: doc {original_doc_id}")

            return DeduplicationResult(
                is_duplicate=True,
                duplicate_type="content_hash",
                original_doc_id=original_doc_id,
                similarity_score=1.0,
                recommendation="skip"
            )

        return DeduplicationResult(
            is_duplicate=False,
            recommendation="process"
        )

    def check_semantic(
        self,
        embedding: List[float],
        search_func,  # Function to search vector DB
        file_path: Optional[Path] = None
    ) -> DeduplicationResult:
        """
        Check for semantic duplicates using embeddings.

        Args:
            embedding: Vector embedding of content
            search_func: Function(embedding, limit) -> List[SearchResult]
            file_path: Optional file path for logging

        Returns:
            DeduplicationResult with similarity info
        """
        try:
            results = search_func(embedding, limit=1)

            if results and len(results) > 0:
                top_result = results[0]
                similarity = getattr(top_result, 'score', 0)

                if similarity >= self.semantic_threshold:
                    logger.info(
                        f"Semantic duplicate found for {file_path}: "
                        f"doc {top_result.document_id} (similarity: {similarity:.3f})"
                    )

                    return DeduplicationResult(
                        is_duplicate=True,
                        duplicate_type="semantic",
                        original_doc_id=top_result.document_id,
                        similarity_score=similarity,
                        recommendation="review"  # Semantic matches should be reviewed
                    )
                elif similarity >= 0.8:
                    # High similarity but not duplicate - flag as related
                    return DeduplicationResult(
                        is_duplicate=False,
                        duplicate_type="related",
                        original_doc_id=top_result.document_id,
                        similarity_score=similarity,
                        recommendation="process"  # Process but note relationship
                    )

        except Exception as e:
            logger.warning(f"Semantic check failed: {e}")

        return DeduplicationResult(
            is_duplicate=False,
            recommendation="process"
        )

    def register_file(
        self,
        file_path: Path,
        doc_id: str,
        content_hash: Optional[str] = None
    ) -> None:
        """
        Register a processed file for future deduplication.

        Args:
            file_path: Path to the processed file
            doc_id: Document ID assigned to this file
            content_hash: Optional pre-computed content hash
        """
        file_hash = self.compute_file_hash(file_path)

        self._file_hashes[file_hash] = str(file_path)
        self._file_to_doc[str(file_path)] = doc_id

        if content_hash:
            self._content_hashes[content_hash] = doc_id

        self._save_state()

    def register_content(self, content_hash: str, doc_id: str) -> None:
        """Register content hash for a document."""
        self._content_hashes[content_hash] = doc_id
        self._save_state()

    def unregister_file(self, file_path: Path) -> None:
        """Remove a file from deduplication tracking."""
        path_str = str(file_path)

        # Find and remove file hash
        file_hash = self.compute_file_hash(file_path) if file_path.exists() else None
        if file_hash and file_hash in self._file_hashes:
            del self._file_hashes[file_hash]

        # Remove path mapping
        if path_str in self._file_to_doc:
            del self._file_to_doc[path_str]

        self._save_state()

    def get_all_paths_for_content(self, doc_id: str) -> List[str]:
        """Get all file paths associated with a document ID."""
        return [path for path, did in self._file_to_doc.items() if did == doc_id]

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """
        Compute SHA-256 hash of file contents.

        Uses chunked reading for memory efficiency with large files.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """
        Compute hash of normalized text content.

        Normalizes text to catch near-identical content:
        - Lowercase
        - Remove extra whitespace
        - Remove common punctuation variations
        """
        # Normalize
        normalized = content.lower()
        normalized = re.sub(r'\s+', ' ', normalized)  # Collapse whitespace
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        normalized = normalized.strip()

        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    def get_stats(self) -> Dict:
        """Get deduplication statistics."""
        return {
            "unique_file_hashes": len(self._file_hashes),
            "unique_content_hashes": len(self._content_hashes),
            "tracked_files": len(self._file_to_doc),
        }

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_dir / "dedup_state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                self._file_hashes = state.get("file_hashes", {})
                self._content_hashes = state.get("content_hashes", {})
                self._file_to_doc = state.get("file_to_doc", {})
                logger.info(f"Loaded dedup state: {len(self._file_hashes)} file hashes")
            except Exception as e:
                logger.error(f"Failed to load dedup state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.state_dir / "dedup_state.json"
        state = {
            "file_hashes": self._file_hashes,
            "content_hashes": self._content_hashes,
            "file_to_doc": self._file_to_doc,
            "updated_at": datetime.now().isoformat()
        }
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)


class ContentNormalizer:
    """Utilities for normalizing content before hashing."""

    @staticmethod
    def normalize_for_comparison(text: str) -> str:
        """
        Normalize text for comparison/hashing.

        - Lowercase
        - Unicode normalization
        - Collapse whitespace
        - Remove punctuation
        """
        import unicodedata

        # Unicode normalize
        text = unicodedata.normalize("NFKC", text)

        # Lowercase
        text = text.lower()

        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text)

        # Remove punctuation (keep alphanumeric and spaces)
        text = re.sub(r'[^\w\s]', '', text)

        return text.strip()

    @staticmethod
    def extract_fingerprint(text: str, n_shingles: int = 100) -> Set[str]:
        """
        Extract MinHash-style fingerprint for fuzzy matching.

        Uses shingles (n-grams) for similarity detection.
        """
        # Normalize
        normalized = ContentNormalizer.normalize_for_comparison(text)

        # Create word-level shingles
        words = normalized.split()
        if len(words) < 3:
            return set(words)

        shingles = set()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i:i+3])
            shingles.add(shingle)

        # Return subset for efficiency
        return set(list(shingles)[:n_shingles])

    @staticmethod
    def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
        """Compute Jaccard similarity between two sets."""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
