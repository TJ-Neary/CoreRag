"""
Duplicate Detection for CoreRag.

Identifies near-duplicate and exact-duplicate documents to:
- Prevent index bloat
- Identify redundant content
- Suggest consolidation opportunities

Uses multiple techniques:
- Content hashing (exact duplicates)
- MinHash/LSH (near duplicates)
- Semantic similarity (conceptual duplicates)
"""

import hashlib
import json
import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class DuplicateMatch:
    """A detected duplicate pair."""

    file1: str
    file2: str
    similarity: float
    match_type: str  # "exact", "near", "semantic"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DuplicateReport:
    """Report of duplicate detection."""

    timestamp: str
    total_files: int
    exact_duplicates: int
    near_duplicates: int
    semantic_duplicates: int
    matches: List[DuplicateMatch]
    space_reclaimable_bytes: int = 0


class ContentHasher:
    """
    Hash content for exact duplicate detection.

    Uses multiple hash algorithms for robustness.
    """

    def __init__(self, normalize: bool = True):
        """
        Initialize hasher.

        Args:
            normalize: Whether to normalize content before hashing
        """
        self.normalize = normalize

    def hash_content(self, content: str) -> str:
        """
        Generate content hash.

        Returns a normalized hash suitable for duplicate detection.
        """
        if self.normalize:
            content = self._normalize(content)

        return hashlib.sha256(content.encode()).hexdigest()

    def hash_file(self, file_path: Path) -> str:
        """Hash a file's content."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.hash_content(content)
        except Exception as e:
            logger.warning(f"Could not hash file {file_path}: {e}")
            return ""

    def _normalize(self, content: str) -> str:
        """Normalize content for hashing."""
        # Remove extra whitespace
        content = re.sub(r"\s+", " ", content)
        # Lowercase
        content = content.lower()
        # Remove punctuation at boundaries
        content = re.sub(r"^\W+|\W+$", "", content)
        return content.strip()


class MinHasher:
    """
    MinHash for near-duplicate detection.

    Efficiently estimates Jaccard similarity between documents.
    """

    def __init__(self, num_hashes: int = 128, shingle_size: int = 3):
        """
        Initialize MinHasher.

        Args:
            num_hashes: Number of hash functions
            shingle_size: Size of shingles (word n-grams)
        """
        self.num_hashes = num_hashes
        self.shingle_size = shingle_size

        # Generate hash coefficients
        import random

        random.seed(42)
        self._a = [random.randint(1, 2**31 - 1) for _ in range(num_hashes)]
        self._b = [random.randint(0, 2**31 - 1) for _ in range(num_hashes)]
        self._prime = 2**31 - 1

    def compute_signature(self, text: str) -> list[float]:
        """Compute MinHash signature for text."""
        shingles = self._get_shingles(text)

        if not shingles:
            return [0] * self.num_hashes

        # Compute signature
        signature = []
        for i in range(self.num_hashes):
            min_hash = float("inf")
            for shingle in shingles:
                h = (self._a[i] * hash(shingle) + self._b[i]) % self._prime
                min_hash = min(min_hash, h)
            signature.append(min_hash)

        return signature

    def estimate_similarity(self, sig1: list[float], sig2: list[float]) -> float:
        """Estimate Jaccard similarity from signatures."""
        if len(sig1) != len(sig2):
            return 0.0

        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)

    def _get_shingles(self, text: str) -> Set[str]:
        """Extract word shingles from text."""
        words = text.lower().split()
        shingles = set()

        for i in range(len(words) - self.shingle_size + 1):
            shingle = " ".join(words[i : i + self.shingle_size])
            shingles.add(shingle)

        return shingles


class DuplicateDetector:
    """
    Comprehensive duplicate detection for the knowledge base.

    Combines multiple techniques for thorough detection.
    """

    # Thresholds
    NEAR_DUPLICATE_THRESHOLD = 0.8
    SEMANTIC_DUPLICATE_THRESHOLD = 0.9

    def __init__(
        self,
        embedding_service: Optional[Any] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize detector.

        Args:
            embedding_service: For semantic duplicate detection
            state_dir: Directory for state persistence
        """
        self.embedding_service = embedding_service
        from src.config import STATE_DIR

        self.state_dir = state_dir or STATE_DIR / "duplicates"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._hasher = ContentHasher()
        self._minhasher = MinHasher()

        # Caches
        self._content_hashes: Dict[str, str] = {}  # file_path -> hash
        self._minhash_sigs: Dict[str, list[float]] = {}  # file_path -> signature
        self._lock = threading.Lock()

        self._load_state()

    def scan_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_types: Optional[List[str]] = None,
    ) -> DuplicateReport:
        """
        Scan a directory for duplicates.

        Args:
            directory: Directory to scan
            recursive: Scan recursively
            file_types: File extensions to check (e.g., [".md", ".txt"])

        Returns:
            DuplicateReport with all matches
        """
        directory = Path(directory)
        matches: List[DuplicateMatch] = []

        # Collect files
        pattern = "**/*" if recursive else "*"
        files = [
            f
            for f in directory.glob(pattern)
            if f.is_file() and (file_types is None or f.suffix.lower() in file_types)
        ]

        logger.info(f"Scanning {len(files)} files for duplicates...")

        # Phase 1: Exact duplicates (content hashing)
        exact_matches = self._find_exact_duplicates(files)
        matches.extend(exact_matches)

        # Phase 2: Near duplicates (MinHash)
        near_matches = self._find_near_duplicates(files)
        matches.extend(near_matches)

        # Phase 3: Semantic duplicates (embeddings)
        if self.embedding_service:
            semantic_matches = self._find_semantic_duplicates(files)
            matches.extend(semantic_matches)

        # Calculate space savings
        space_reclaimable = sum(
            Path(m.file2).stat().st_size
            for m in matches
            if m.match_type == "exact" and Path(m.file2).exists()
        )

        # Save state
        self._save_state()

        report = DuplicateReport(
            timestamp=datetime.now().isoformat(),
            total_files=len(files),
            exact_duplicates=len([m for m in matches if m.match_type == "exact"]),
            near_duplicates=len([m for m in matches if m.match_type == "near"]),
            semantic_duplicates=len([m for m in matches if m.match_type == "semantic"]),
            matches=matches,
            space_reclaimable_bytes=space_reclaimable,
        )

        logger.info(
            f"Found {len(matches)} duplicates: "
            f"{report.exact_duplicates} exact, "
            f"{report.near_duplicates} near, "
            f"{report.semantic_duplicates} semantic"
        )

        return report

    def check_file(self, file_path: Path) -> List[DuplicateMatch]:
        """
        Check if a file is a duplicate of existing files.

        Useful for checking before ingestion.
        """
        file_path = Path(file_path)
        matches = []

        # Hash the file
        content_hash = self._hasher.hash_file(file_path)

        with self._lock:
            # Check for exact match
            for existing_path, existing_hash in self._content_hashes.items():
                if existing_hash == content_hash and existing_path != str(file_path):
                    matches.append(
                        DuplicateMatch(
                            file1=existing_path,
                            file2=str(file_path),
                            similarity=1.0,
                            match_type="exact",
                        )
                    )
                    return matches  # Exact match found, no need for more

            # Check for near match
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                sig = self._minhasher.compute_signature(content)

                for existing_path, existing_sig in self._minhash_sigs.items():
                    if existing_path != str(file_path):
                        similarity = self._minhasher.estimate_similarity(sig, existing_sig)
                        if similarity >= self.NEAR_DUPLICATE_THRESHOLD:
                            matches.append(
                                DuplicateMatch(
                                    file1=existing_path,
                                    file2=str(file_path),
                                    similarity=similarity,
                                    match_type="near",
                                )
                            )

            except Exception as e:
                logger.warning(f"Error checking file {file_path}: {e}")

        return matches

    def add_file(self, file_path: Path) -> None:
        """Add a file to the duplicate index."""
        file_path = Path(file_path)

        try:
            # Hash content
            content_hash = self._hasher.hash_file(file_path)

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # MinHash signature
            sig = self._minhasher.compute_signature(content)

            with self._lock:
                self._content_hashes[str(file_path)] = content_hash
                self._minhash_sigs[str(file_path)] = sig

        except Exception as e:
            logger.warning(f"Error adding file {file_path}: {e}")

    def remove_file(self, file_path: Path) -> None:
        """Remove a file from the duplicate index."""
        with self._lock:
            self._content_hashes.pop(str(file_path), None)
            self._minhash_sigs.pop(str(file_path), None)

    def _find_exact_duplicates(self, files: List[Path]) -> List[DuplicateMatch]:
        """Find exact duplicates using content hashing."""
        matches = []
        hash_to_files: Dict[str, List[str]] = defaultdict(list)

        for file_path in files:
            content_hash = self._hasher.hash_file(file_path)
            if content_hash:
                hash_to_files[content_hash].append(str(file_path))

                with self._lock:
                    self._content_hashes[str(file_path)] = content_hash

        # Find groups with multiple files
        for content_hash, file_list in hash_to_files.items():
            if len(file_list) > 1:
                # First file is the "original", rest are duplicates
                original = file_list[0]
                for duplicate in file_list[1:]:
                    matches.append(
                        DuplicateMatch(
                            file1=original,
                            file2=duplicate,
                            similarity=1.0,
                            match_type="exact",
                            details={"hash": content_hash},
                        )
                    )

        return matches

    def _find_near_duplicates(self, files: List[Path]) -> List[DuplicateMatch]:
        """Find near-duplicates using MinHash."""
        matches = []
        signatures = {}

        # Compute signatures
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                sig = self._minhasher.compute_signature(content)
                signatures[str(file_path)] = sig

                with self._lock:
                    self._minhash_sigs[str(file_path)] = sig

            except Exception as e:
                logger.warning(f"Error processing {file_path}: {e}")

        # Compare all pairs (could be optimized with LSH)
        file_list = list(signatures.keys())
        for i, file1 in enumerate(file_list):
            for file2 in file_list[i + 1 :]:
                similarity = self._minhasher.estimate_similarity(
                    signatures[file1], signatures[file2]
                )

                if similarity >= self.NEAR_DUPLICATE_THRESHOLD:
                    # Avoid reporting if already exact match
                    if self._content_hashes.get(file1) != self._content_hashes.get(file2):
                        matches.append(
                            DuplicateMatch(
                                file1=file1,
                                file2=file2,
                                similarity=similarity,
                                match_type="near",
                            )
                        )

        return matches

    def _find_semantic_duplicates(self, files: List[Path]) -> List[DuplicateMatch]:
        """Find semantic duplicates using embeddings."""
        if not self.embedding_service:
            return []

        matches = []

        # Get embeddings for all files
        embeddings = {}
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Truncate for embedding
                if len(content) > 10000:
                    content = content[:10000]

                emb = self.embedding_service.embed_query(content)
                embeddings[str(file_path)] = emb

            except Exception as e:
                logger.warning(f"Error embedding {file_path}: {e}")

        # Compare pairs
        file_list = list(embeddings.keys())
        for i, file1 in enumerate(file_list):
            for file2 in file_list[i + 1 :]:
                similarity = self._cosine_similarity(embeddings[file1], embeddings[file2])

                if similarity >= self.SEMANTIC_DUPLICATE_THRESHOLD:
                    # Avoid if already matched as exact or near
                    if (
                        self._content_hashes.get(file1) != self._content_hashes.get(file2)
                        and self._minhasher.estimate_similarity(
                            self._minhash_sigs.get(file1, []), self._minhash_sigs.get(file2, [])
                        )
                        < self.NEAR_DUPLICATE_THRESHOLD
                    ):
                        matches.append(
                            DuplicateMatch(
                                file1=file1,
                                file2=file2,
                                similarity=similarity,
                                match_type="semantic",
                            )
                        )

        return matches

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_dir / "duplicate_index.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                    self._content_hashes = data.get("hashes", {})
                    self._minhash_sigs = data.get("signatures", {})
                logger.info(f"Loaded duplicate index: {len(self._content_hashes)} files")
            except Exception as e:
                logger.warning(f"Failed to load duplicate state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.state_dir / "duplicate_index.json"

        try:
            with open(state_file, "w") as f:
                json.dump(
                    {
                        "hashes": self._content_hashes,
                        "signatures": self._minhash_sigs,
                    },
                    f,
                )
        except Exception as e:
            logger.warning(f"Failed to save duplicate state: {e}")
