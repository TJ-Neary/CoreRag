"""
Conflict Detection for CoreRag.

Detect contradictions and inconsistencies across documents:
- Semantic contradiction detection
- Fact verification across sources
- Date/number inconsistencies
- Outdated information flagging
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ConflictType(Enum):
    """Types of conflicts detected."""

    CONTRADICTION = "contradiction"  # Direct semantic contradiction
    NUMERIC_MISMATCH = "numeric_mismatch"  # Different numbers for same thing
    DATE_MISMATCH = "date_mismatch"  # Different dates for same event
    VERSION_CONFLICT = "version_conflict"  # Different version numbers
    OUTDATED = "outdated"  # Newer info supersedes older
    AMBIGUOUS = "ambiguous"  # Unclear which is correct


class ConflictSeverity(Enum):
    """Severity of detected conflict."""

    LOW = "low"  # Minor inconsistency
    MEDIUM = "medium"  # Notable conflict
    HIGH = "high"  # Serious contradiction
    CRITICAL = "critical"  # Dangerous misinformation


@dataclass
class ConflictEvidence:
    """Evidence supporting a conflict."""

    file_path: str
    content: str
    line_number: Optional[int] = None
    context: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class Conflict:
    """A detected conflict between documents."""

    conflict_type: ConflictType
    severity: ConflictSeverity
    description: str
    evidence_a: ConflictEvidence
    evidence_b: ConflictEvidence
    topic: Optional[str] = None
    resolution_suggestion: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ConflictReport:
    """Report of all detected conflicts."""

    scan_timestamp: datetime
    documents_analyzed: int
    conflicts_found: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]
    conflicts: List[Conflict]

    def get_critical(self) -> List[Conflict]:
        """Get critical conflicts."""
        return [c for c in self.conflicts if c.severity == ConflictSeverity.CRITICAL]

    def get_high_priority(self) -> List[Conflict]:
        """Get high priority conflicts (critical + high)."""
        return [
            c
            for c in self.conflicts
            if c.severity in {ConflictSeverity.CRITICAL, ConflictSeverity.HIGH}
        ]


class NumericExtractor:
    """Extract numeric facts from text."""

    # Patterns for extracting numbers with context
    PATTERNS = [
        # Version numbers
        (r"version\s+(\d+(?:\.\d+)+)", "version"),
        (r"v(\d+(?:\.\d+)+)", "version"),
        # Dates
        (r"(\d{4}-\d{2}-\d{2})", "date"),
        (r"(\d{1,2}/\d{1,2}/\d{4})", "date"),
        (
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
            "date",
        ),
        # Percentages
        (r"(\d+(?:\.\d+)?)\s*%", "percentage"),
        # Counts/quantities
        (r"(\d+(?:,\d{3})*)\s+(users?|items?|files?|documents?|records?)", "count"),
        # Prices
        (r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)", "price"),
        # Times
        (r"(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?)", "duration"),
    ]

    @classmethod
    def extract(cls, text: str) -> List[Dict[str, Any]]:
        """
        Extract numeric facts from text.

        Args:
            text: Document text

        Returns:
            List of extracted facts
        """
        facts = []

        for pattern, fact_type in cls.PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                facts.append(
                    {
                        "type": fact_type,
                        "value": match.group(1) if match.groups() else match.group(0),
                        "full_match": match.group(0),
                        "position": match.start(),
                        "context": text[max(0, match.start() - 50) : match.end() + 50],
                    }
                )

        return facts


class SemanticConflictDetector:
    """
    Detect semantic contradictions using embeddings.

    Strategy:
    1. Find semantically similar passages
    2. Check if they contain opposing sentiment/facts
    3. Use NLI model for entailment/contradiction detection
    """

    def __init__(
        self,
        embedder: Callable[[str], List[float]],
        similarity_threshold: float = 0.8,
        nli_classifier: Optional[Callable[[str, str], str]] = None,
    ):
        """
        Initialize detector.

        Args:
            embedder: Embedding function
            similarity_threshold: Min similarity to compare
            nli_classifier: Optional NLI model for contradiction detection
        """
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.nli_classifier = nli_classifier

    def find_contradictions(
        self,
        passages: List[Dict[str, str]],
    ) -> List[Tuple[Dict, Dict, float]]:
        """
        Find contradicting passages.

        Args:
            passages: List of {text, source_path, ...}

        Returns:
            List of (passage_a, passage_b, confidence)
        """
        # Embed all passages
        embeddings = {}
        for p in passages:
            text = p.get("text", "")[:2000]
            embeddings[p.get("source_path", id(p))] = self.embedder(text)

        contradictions = []

        # Compare pairs
        passage_list = list(passages)
        for i, p1 in enumerate(passage_list):
            for p2 in passage_list[i + 1 :]:
                # Check similarity
                sim = self._cosine_similarity(
                    embeddings[p1.get("source_path", id(p1))],
                    embeddings[p2.get("source_path", id(p2))],
                )

                if sim >= self.similarity_threshold:
                    # Similar topic - check for contradiction
                    if self.nli_classifier:
                        result = self.nli_classifier(
                            p1.get("text", ""),
                            p2.get("text", ""),
                        )
                        if result == "contradiction":
                            contradictions.append((p1, p2, 0.9))
                    else:
                        # Heuristic check
                        if self._heuristic_contradiction(
                            p1.get("text", ""),
                            p2.get("text", ""),
                        ):
                            contradictions.append((p1, p2, 0.6))

        return contradictions

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _heuristic_contradiction(self, text1: str, text2: str) -> bool:
        """Simple heuristic for contradiction detection."""
        # Check for negation patterns
        negation_words = {
            "not",
            "never",
            "no",
            "none",
            "cannot",
            "don't",
            "doesn't",
            "won't",
            "isn't",
            "aren't",
        }

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        # If one has negation of similar content
        neg_in_1 = bool(words1 & negation_words)
        neg_in_2 = bool(words2 & negation_words)

        if neg_in_1 != neg_in_2:
            # Check for shared content words
            content_words = (
                (words1 & words2) - negation_words - {"the", "a", "is", "are", "was", "were"}
            )
            if len(content_words) > 3:
                return True

        return False


class ConflictDetector:
    """
    Main conflict detector combining multiple strategies.

    Features:
    - Numeric fact checking
    - Semantic contradiction detection
    - Date/version conflicts
    - Resolution suggestions
    """

    def __init__(
        self,
        embedder: Optional[Callable[[str], List[float]]] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize conflict detector.

        Args:
            embedder: Embedding function for semantic detection
            state_dir: Directory for state persistence
        """
        self.embedder = embedder
        from src.config import STATE_DIR

        self.state_dir = state_dir or STATE_DIR / "conflicts"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.semantic_detector = SemanticConflictDetector(embedder) if embedder else None

    def scan_documents(
        self,
        documents: List[Dict[str, Any]],
    ) -> ConflictReport:
        """
        Scan documents for conflicts.

        Args:
            documents: List of {text, source_path, ...}

        Returns:
            ConflictReport
        """
        start_time = datetime.now()
        conflicts: List[Conflict] = []

        # Extract facts from all documents
        doc_facts: Dict[str, List[Dict]] = {}
        for doc in documents:
            path = doc.get("source_path", "unknown")
            text = doc.get("text", "")
            doc_facts[path] = NumericExtractor.extract(text)

        # Check numeric conflicts
        conflicts.extend(self._check_numeric_conflicts(doc_facts, documents))

        # Check semantic contradictions
        if self.semantic_detector:
            semantic_conflicts = self.semantic_detector.find_contradictions(documents)
            for p1, p2, confidence in semantic_conflicts:
                conflicts.append(
                    Conflict(
                        conflict_type=ConflictType.CONTRADICTION,
                        severity=(
                            ConflictSeverity.HIGH if confidence > 0.8 else ConflictSeverity.MEDIUM
                        ),
                        description="Semantic contradiction detected between passages",
                        evidence_a=ConflictEvidence(
                            file_path=p1.get("source_path", ""),
                            content=p1.get("text", "")[:200],
                        ),
                        evidence_b=ConflictEvidence(
                            file_path=p2.get("source_path", ""),
                            content=p2.get("text", "")[:200],
                        ),
                        confidence=confidence,
                    )
                )

        # Build report
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        for c in conflicts:
            by_type[c.conflict_type.value] = by_type.get(c.conflict_type.value, 0) + 1
            by_severity[c.severity.value] = by_severity.get(c.severity.value, 0) + 1

        return ConflictReport(
            scan_timestamp=start_time,
            documents_analyzed=len(documents),
            conflicts_found=len(conflicts),
            by_type=by_type,
            by_severity=by_severity,
            conflicts=conflicts,
        )

    def scan_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_types: Optional[List[str]] = None,
    ) -> ConflictReport:
        """
        Scan a directory for conflicts.

        Args:
            directory: Directory to scan
            recursive: Scan recursively
            file_types: File extensions to scan

        Returns:
            ConflictReport
        """
        if file_types is None:
            file_types = ["md", "txt"]

        documents = []

        pattern = "**/*" if recursive else "*"
        for file_path in Path(directory).glob(pattern):
            if file_path.is_file():
                ext = file_path.suffix.lower().lstrip(".")
                if ext in file_types:
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        documents.append(
                            {
                                "text": content,
                                "source_path": str(file_path),
                                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime),
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Error reading {file_path}: {e}")

        return self.scan_documents(documents)

    def _check_numeric_conflicts(
        self,
        doc_facts: Dict[str, List[Dict]],
        documents: List[Dict],
    ) -> List[Conflict]:
        """Check for numeric fact conflicts."""
        conflicts = []

        # Group facts by type and context
        fact_groups: Dict[str, List[Tuple[str, Dict]]] = {}

        for doc_path, facts in doc_facts.items():
            for fact in facts:
                # Create a key based on context (simplified)
                context_key = self._normalize_context(fact.get("context", ""))
                group_key = f"{fact['type']}:{context_key}"

                if group_key not in fact_groups:
                    fact_groups[group_key] = []
                fact_groups[group_key].append((doc_path, fact))

        # Check each group for conflicts
        for group_key, items in fact_groups.items():
            if len(items) < 2:
                continue

            values = set(item[1]["value"] for item in items)
            if len(values) > 1:
                # Conflict found
                fact_type = group_key.split(":")[0]

                # Determine severity
                if fact_type == "version":
                    severity = ConflictSeverity.MEDIUM
                    conflict_type = ConflictType.VERSION_CONFLICT
                elif fact_type == "date":
                    severity = ConflictSeverity.MEDIUM
                    conflict_type = ConflictType.DATE_MISMATCH
                else:
                    severity = ConflictSeverity.LOW
                    conflict_type = ConflictType.NUMERIC_MISMATCH

                # Create conflict
                item1 = items[0]
                item2 = items[1]

                conflicts.append(
                    Conflict(
                        conflict_type=conflict_type,
                        severity=severity,
                        description=f"{fact_type.title()} mismatch: '{item1[1]['value']}' vs '{item2[1]['value']}'",
                        evidence_a=ConflictEvidence(
                            file_path=item1[0],
                            content=item1[1]["full_match"],
                            context=item1[1].get("context"),
                        ),
                        evidence_b=ConflictEvidence(
                            file_path=item2[0],
                            content=item2[1]["full_match"],
                            context=item2[1].get("context"),
                        ),
                        topic=group_key.split(":")[1][:50] if ":" in group_key else None,
                        resolution_suggestion=self._suggest_resolution(fact_type, items),
                        confidence=0.8,
                    )
                )

        return conflicts

    def _normalize_context(self, context: str) -> str:
        """Normalize context for grouping."""
        # Remove numbers and punctuation
        normalized = re.sub(r"[\d\.\,\-\/\:\;]+", "", context.lower())
        # Keep only significant words
        words = [w for w in normalized.split() if len(w) > 3]
        return " ".join(sorted(words[:5]))

    def _suggest_resolution(
        self,
        fact_type: str,
        items: List[Tuple[str, Dict]],
    ) -> str:
        """Suggest resolution for conflict."""
        if fact_type == "version":
            # Suggest keeping newest
            return "Consider keeping the highest version number and updating other documents."
        elif fact_type == "date":
            return "Verify dates against authoritative source and update outdated references."
        else:
            return "Review both sources and determine which value is correct."


def format_conflict_report(report: ConflictReport) -> str:
    """Format conflict report as markdown."""
    lines = [
        "# Conflict Detection Report",
        "",
        f"**Scan Time:** {report.scan_timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Documents Analyzed:** {report.documents_analyzed}",
        f"**Conflicts Found:** {report.conflicts_found}",
        "",
    ]

    if report.conflicts_found == 0:
        lines.append("✓ No conflicts detected!")
        return "\n".join(lines)

    # Summary by severity
    lines.extend(
        [
            "## Summary by Severity",
            "",
        ]
    )
    for severity, count in sorted(report.by_severity.items()):
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
        lines.append(f"- {icon} {severity.title()}: {count}")

    lines.append("")

    # Conflicts by type
    lines.extend(
        [
            "## Summary by Type",
            "",
        ]
    )
    for ctype, count in report.by_type.items():
        lines.append(f"- {ctype.replace('_', ' ').title()}: {count}")

    lines.append("")

    # High priority conflicts
    high_priority = report.get_high_priority()
    if high_priority:
        lines.extend(
            [
                "## High Priority Conflicts",
                "",
            ]
        )

        for i, conflict in enumerate(high_priority[:10], 1):
            lines.extend(
                [
                    f"### {i}. {conflict.description}",
                    "",
                    f"**Type:** {conflict.conflict_type.value}",
                    f"**Severity:** {conflict.severity.value}",
                    f"**Confidence:** {conflict.confidence:.0%}",
                    "",
                    "**Evidence A:**",
                    f"- File: `{Path(conflict.evidence_a.file_path).name}`",
                    f"- Content: {conflict.evidence_a.content[:100]}...",
                    "",
                    "**Evidence B:**",
                    f"- File: `{Path(conflict.evidence_b.file_path).name}`",
                    f"- Content: {conflict.evidence_b.content[:100]}...",
                    "",
                ]
            )

            if conflict.resolution_suggestion:
                lines.append(f"**Suggested Resolution:** {conflict.resolution_suggestion}")
                lines.append("")

    return "\n".join(lines)


# Convenience function
def detect_conflicts(
    directory: Path,
    embedder: Optional[Callable[[str], List[float]]] = None,
) -> ConflictReport:
    """
    Quick conflict detection for a directory.

    Args:
        directory: Directory to scan
        embedder: Optional embedding function

    Returns:
        ConflictReport
    """
    detector = ConflictDetector(embedder)
    return detector.scan_directory(directory)
