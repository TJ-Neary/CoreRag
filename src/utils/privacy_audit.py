"""
Privacy audit system for CoreRag.

Scans content for sensitive information and enforces privacy tiers.

HYBRID APPROACH:
- Presidio (Microsoft's production-grade PII detection) for:
  Names, Locations, Credit Cards (with checksum), SSNs, Phones, Emails
- Custom regex patterns for:
  API Keys, Passwords, custom project codes, technical secrets

This provides enterprise-grade PII detection while maintaining
flexibility for technical credential scanning.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Check for Presidio availability
PRESIDIO_AVAILABLE = False
try:
    import importlib.util

    if importlib.util.find_spec("presidio_analyzer"):
        PRESIDIO_AVAILABLE = True
    else:
        raise ImportError("presidio_analyzer not found")
except ImportError:
    logger.info(
        "Presidio not installed. Using regex-only mode. Install with: pip install presidio-analyzer"
    )


class PrivacyTier(Enum):
    """Privacy classification levels."""

    PUBLIC = "public"  # Safe to share anywhere
    INTERNAL = "internal"  # Work-related, not public
    PRIVATE = "private"  # Personal, not for sharing
    SENSITIVE = "sensitive"  # PII, financial, health data
    RESTRICTED = "restricted"  # Highest protection level


class SensitiveDataType(Enum):
    """Types of sensitive data."""

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    PASSWORD = "password"
    ADDRESS = "address"
    NAME = "name"
    DATE_OF_BIRTH = "date_of_birth"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    ACCOUNT = "account"
    EMPLOYEE_ID = "employee_id"
    POLICY = "policy"
    CUSTOM = "custom"


@dataclass
class SensitiveMatch:
    """A detected sensitive data match."""

    data_type: SensitiveDataType
    matched_text: str
    start_pos: int
    end_pos: int
    confidence: float  # 0.0 to 1.0
    context: str  # Surrounding text for review


@dataclass
class AuditResult:
    """Result of a privacy audit."""

    file_path: Optional[str]
    timestamp: str
    privacy_tier: PrivacyTier
    matches: List[SensitiveMatch] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    approved: bool = False
    reviewed_by: Optional[str] = None

    @property
    def has_sensitive_data(self) -> bool:
        return len(self.matches) > 0

    @property
    def risk_level(self) -> str:
        if not self.matches:
            return "low"
        high_risk = {
            SensitiveDataType.SSN,
            SensitiveDataType.CREDIT_CARD,
            SensitiveDataType.API_KEY,
            SensitiveDataType.PASSWORD,
        }
        if any(m.data_type in high_risk for m in self.matches):
            return "high"
        return "medium"


class PrivacyScanner:
    """
    Scan content for sensitive information using hybrid approach.

    PRESIDIO (when available) handles:
    - Names (PERSON) - NER-based detection
    - Locations (LOCATION) - NER-based detection
    - Credit Cards (CREDIT_CARD) - with Luhn checksum validation
    - SSNs (US_SSN) - with format validation
    - Phone Numbers (PHONE_NUMBER) - international formats
    - Email Addresses (EMAIL_ADDRESS) - RFC-compliant

    CUSTOM REGEX handles:
    - API Keys - various provider patterns
    - Passwords - config file patterns
    - AWS Keys, GitHub tokens, etc.
    - Custom project codes
    """

    # Entity type mapping: Presidio -> SensitiveDataType
    PRESIDIO_ENTITY_MAP = {
        "PERSON": SensitiveDataType.NAME,
        "LOCATION": SensitiveDataType.ADDRESS,
        "CREDIT_CARD": SensitiveDataType.CREDIT_CARD,
        "US_SSN": SensitiveDataType.SSN,
        "PHONE_NUMBER": SensitiveDataType.PHONE,
        "EMAIL_ADDRESS": SensitiveDataType.EMAIL,
        "US_BANK_NUMBER": SensitiveDataType.FINANCIAL,
        "IBAN_CODE": SensitiveDataType.FINANCIAL,
        "IP_ADDRESS": SensitiveDataType.IP_ADDRESS,
        "DATE_TIME": SensitiveDataType.DATE_OF_BIRTH,
        "NRP": SensitiveDataType.NAME,  # Nationality/Religion/Political group
        "MEDICAL_LICENSE": SensitiveDataType.MEDICAL,
    }

    # Custom regex patterns for technical secrets (NOT handled by Presidio)
    TECHNICAL_PATTERNS = {
        SensitiveDataType.SSN: [
            # SSN with dashes: XXX-XX-XXXX (Presidio's US_SSN recognizer is unreliable)
            (r"\b\d{3}-\d{2}-\d{4}\b", 0.90),
            # SSN without dashes: XXXXXXXXX (9 digits)
            (r"\b(?:ssn|social\s*security)[:\s]*(\d{9})\b", 0.85),
        ],
        SensitiveDataType.API_KEY: [
            # Generic API key patterns
            (
                r'(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})',
                0.90,
            ),
            # AWS Access Key ID
            (r"AKIA[0-9A-Z]{16}", 0.95),
            # AWS Secret Access Key
            (
                r'(?:aws)?_?(?:secret)?_?(?:access)?_?key["\']?\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})',
                0.95,
            ),
            # GitHub Token
            (r"gh[pousr]_[A-Za-z0-9_]{36,}", 0.98),
            # Generic Bearer Token
            (r"Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", 0.90),
            # Slack Token
            (r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*", 0.95),
            # Google API Key
            (r"AIza[0-9A-Za-z\-_]{35}", 0.95),
            # Stripe API Key
            (r"(?:sk|pk)_(?:test|live)_[0-9a-zA-Z]{24,}", 0.98),
            # OpenAI API Key
            (r"sk-[A-Za-z0-9]{48}", 0.98),
            # Anthropic API Key
            (r"sk-ant-[A-Za-z0-9\-]{40,}", 0.98),
        ],
        SensitiveDataType.PASSWORD: [
            # Password in config files
            (r'(?:password|passwd|pwd|secret)["\']?\s*[:=]\s*["\']?([^\s\'"]{4,})', 0.85),
            # Database connection strings
            (r"(?:mysql|postgres|mongodb)://[^:]+:([^@]+)@", 0.90),
            # Private key markers
            (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", 0.99),
        ],
    }

    # Keywords that suggest sensitive content (kept for context detection)
    SENSITIVE_KEYWORDS = {
        SensitiveDataType.MEDICAL: {
            "diagnosis",
            "prescription",
            "patient",
            "medication",
            "symptoms",
            "treatment",
            "medical",
            "health",
            "doctor",
            "hospital",
            "clinic",
            "pharmacy",
        },
        SensitiveDataType.FINANCIAL: {
            "bank account",
            "routing number",
            "balance",
            "transaction",
            "salary",
            "income",
            "tax",
            "irs",
            "investment",
            "portfolio",
        },
        SensitiveDataType.ADDRESS: {
            "street",
            "avenue",
            "boulevard",
            "apartment",
            "apt",
            "suite",
            "zip code",
            "postal",
        },
    }

    def __init__(
        self,
        custom_patterns: Optional[Dict] = None,
        use_presidio: bool = True,
        presidio_languages: Optional[List[str]] = None,
    ):
        """
        Initialize hybrid scanner.

        Args:
            custom_patterns: Additional regex patterns to check
            use_presidio: Whether to use Presidio (if available)
            presidio_languages: Languages for NER (default: ["en"])
        """
        self.use_presidio = use_presidio and PRESIDIO_AVAILABLE
        self._analyzer: Optional[Any] = None

        # Initialize Presidio if available
        if self.use_presidio:
            self._init_presidio(presidio_languages or ["en"], custom_patterns)
        else:
            logger.info("Running in regex-only mode")

        # Compile technical patterns
        self._compiled_technical = {}
        for dtype, patterns in self.TECHNICAL_PATTERNS.items():
            self._compiled_technical[dtype] = [
                (re.compile(pattern, re.IGNORECASE), confidence) for pattern, confidence in patterns
            ]

        # Add any custom patterns
        if custom_patterns:
            for dtype, patterns in custom_patterns.items():
                if dtype not in self._compiled_technical:
                    self._compiled_technical[dtype] = []
                for pattern, confidence in patterns:
                    self._compiled_technical[dtype].append(
                        (re.compile(pattern, re.IGNORECASE), confidence)
                    )

    def _init_presidio(self, languages: List[str], custom_patterns: Optional[Dict] = None) -> None:
        """Initialize Presidio analyzer with custom recognizers."""
        try:
            from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

            # Create analyzer
            self._analyzer = AnalyzerEngine()

            # Add custom API key recognizer to Presidio
            api_key_patterns = [
                Pattern(name="aws_access_key", regex=r"AKIA[0-9A-Z]{16}", score=0.95),
                Pattern(name="github_token", regex=r"gh[pousr]_[A-Za-z0-9_]{36,}", score=0.98),
                Pattern(name="openai_key", regex=r"sk-[A-Za-z0-9]{48}", score=0.98),
                Pattern(name="anthropic_key", regex=r"sk-ant-[A-Za-z0-9\-]{40,}", score=0.98),
                Pattern(
                    name="stripe_key", regex=r"(?:sk|pk)_(?:test|live)_[0-9a-zA-Z]{24,}", score=0.98
                ),
                Pattern(name="google_api_key", regex=r"AIza[0-9A-Za-z\-_]{35}", score=0.95),
                Pattern(
                    name="slack_token",
                    regex=r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*",
                    score=0.95,
                ),
                Pattern(
                    name="generic_api_key",
                    regex=r"(?:api[_-]?key|secret[_-]?key)['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{20,})",
                    score=0.85,
                ),
            ]
            api_recognizer = PatternRecognizer(
                supported_entity="API_KEY", patterns=api_key_patterns, name="api_key_recognizer"
            )
            self._analyzer.registry.add_recognizer(api_recognizer)

            # Add private key recognizer
            private_key_pattern = Pattern(
                name="private_key",
                regex=r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
                score=0.99,
            )
            pk_recognizer = PatternRecognizer(
                supported_entity="CRYPTO_PRIVATE_KEY",
                patterns=[private_key_pattern],
                name="private_key_recognizer",
            )
            self._analyzer.registry.add_recognizer(pk_recognizer)

            logger.info("Presidio analyzer initialized with custom recognizers")

        except Exception as e:
            logger.warning(f"Failed to initialize Presidio: {e}. Falling back to regex.")
            self.use_presidio = False
            self._analyzer = None

    def scan(
        self, content: str, file_path: Optional[str] = None, context_chars: int = 50
    ) -> AuditResult:
        """
        Scan content for sensitive information using hybrid approach.

        Uses Presidio (when available) for standard PII detection,
        and custom regex for technical secrets like API keys.

        Args:
            content: Text content to scan
            file_path: Optional file path for logging
            context_chars: Characters of context to include

        Returns:
            AuditResult with all findings
        """
        matches: List[SensitiveMatch] = []

        # Phase 1: Presidio-based scanning (Names, Locations, Credit Cards, etc.)
        if self.use_presidio and self._analyzer:
            matches.extend(self._scan_with_presidio(content, context_chars))

        # Phase 2: Technical secrets scanning (API keys, passwords, etc.)
        matches.extend(self._scan_technical_secrets(content, context_chars))

        # Phase 3: Keyword-based context scanning (informational only)
        # These are NOT included in match results or tier determination because
        # topic words like "salary" and "hospital" are not PII — they cause
        # false positives on policy documents, HR guides, etc.
        # Kept for audit logging if needed in the future.

        # Deduplicate matches by position
        matches = self._deduplicate_matches(matches)

        # Determine privacy tier
        privacy_tier = self._determine_tier(matches)

        # Generate recommendations
        recommendations = self._generate_recommendations(matches, privacy_tier)

        return AuditResult(
            file_path=file_path,
            timestamp=datetime.now().isoformat(),
            privacy_tier=privacy_tier,
            matches=matches,
            recommendations=recommendations,
        )

    def _scan_with_presidio(self, content: str, context_chars: int) -> List[SensitiveMatch]:
        """Use Presidio for NER-based PII detection."""
        matches = []

        try:
            assert self._analyzer is not None
            results = self._analyzer.analyze(
                text=content,
                language="en",
                entities=[
                    "PERSON",
                    "LOCATION",
                    "CREDIT_CARD",
                    "US_SSN",
                    "PHONE_NUMBER",
                    "EMAIL_ADDRESS",
                    "US_BANK_NUMBER",
                    "IBAN_CODE",
                    "IP_ADDRESS",
                    "API_KEY",
                    "CRYPTO_PRIVATE_KEY",
                ],
            )

            for result in results:
                start, end = result.start, result.end
                matched_text = content[start:end]

                # Map Presidio entity to our type
                if result.entity_type == "API_KEY":
                    dtype = SensitiveDataType.API_KEY
                elif result.entity_type == "CRYPTO_PRIVATE_KEY":
                    dtype = SensitiveDataType.PASSWORD
                else:
                    dtype = self.PRESIDIO_ENTITY_MAP.get(
                        result.entity_type, SensitiveDataType.NAME  # Default fallback
                    )

                # Get context
                ctx_start = max(0, start - context_chars)
                ctx_end = min(len(content), end + context_chars)
                context = content[ctx_start:ctx_end]

                matches.append(
                    SensitiveMatch(
                        data_type=dtype,
                        matched_text=self._redact(matched_text, dtype),
                        start_pos=start,
                        end_pos=end,
                        confidence=result.score,
                        context=self._redact_context(context, matched_text),
                    )
                )

        except Exception as e:
            logger.warning(f"Presidio scan failed: {e}")

        return matches

    def _scan_technical_secrets(self, content: str, context_chars: int) -> List[SensitiveMatch]:
        """Scan for technical secrets using regex patterns."""
        matches = []

        for dtype, patterns in self._compiled_technical.items():
            for pattern, confidence in patterns:
                for match in pattern.finditer(content):
                    start, end = match.span()

                    # Get context
                    ctx_start = max(0, start - context_chars)
                    ctx_end = min(len(content), end + context_chars)
                    context = content[ctx_start:ctx_end]

                    matches.append(
                        SensitiveMatch(
                            data_type=dtype,
                            matched_text=self._redact(match.group(), dtype),
                            start_pos=start,
                            end_pos=end,
                            confidence=confidence,
                            context=self._redact_context(context, match.group()),
                        )
                    )

        return matches

    def _scan_keywords(self, content: str, context_chars: int) -> List[SensitiveMatch]:
        """Scan for sensitive keywords (medical, financial, etc.)."""
        matches = []
        content_lower = content.lower()

        for dtype, keywords in self.SENSITIVE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content_lower:
                    # Find position
                    pos = content_lower.find(keyword)
                    ctx_start = max(0, pos - context_chars)
                    ctx_end = min(len(content), pos + len(keyword) + context_chars)

                    matches.append(
                        SensitiveMatch(
                            data_type=dtype,
                            matched_text=f"[{dtype.value} keyword: {keyword}]",
                            start_pos=pos,
                            end_pos=pos + len(keyword),
                            confidence=0.60,  # Lower confidence for keywords
                            context=content[ctx_start:ctx_end],
                        )
                    )

        return matches

    def _deduplicate_matches(self, matches: List[SensitiveMatch]) -> List[SensitiveMatch]:
        """Remove duplicate matches at the same position."""
        seen_positions: Set[Tuple[int, int]] = set()
        unique_matches = []

        # Sort by confidence (descending) to keep highest confidence matches
        sorted_matches = sorted(matches, key=lambda m: m.confidence, reverse=True)

        for match in sorted_matches:
            pos_key = (match.start_pos, match.end_pos)
            if pos_key not in seen_positions:
                seen_positions.add(pos_key)
                unique_matches.append(match)

        return unique_matches

    def _redact(self, text: str, dtype: SensitiveDataType) -> str:
        """Redact sensitive text for safe storage."""
        if dtype in {SensitiveDataType.SSN, SensitiveDataType.CREDIT_CARD}:
            return f"***{text[-4:]}"
        elif dtype == SensitiveDataType.EMAIL:
            parts = text.split("@")
            if len(parts) == 2:
                return f"{parts[0][:2]}***@{parts[1]}"
        elif dtype in {SensitiveDataType.API_KEY, SensitiveDataType.PASSWORD}:
            return "***REDACTED***"
        return f"***{text[-4:]}" if len(text) > 4 else "***"

    def _redact_context(self, context: str, matched: str) -> str:
        """Redact the matched text within context."""
        if len(matched) > 4:
            redacted = f"***{matched[-4:]}"
        else:
            redacted = "***"
        return context.replace(matched, redacted)

    def _determine_tier(self, matches: List[SensitiveMatch]) -> PrivacyTier:
        """Determine appropriate privacy tier based on findings."""
        if not matches:
            return PrivacyTier.PUBLIC

        high_risk_types = {
            SensitiveDataType.SSN,
            SensitiveDataType.CREDIT_CARD,
            SensitiveDataType.API_KEY,
            SensitiveDataType.PASSWORD,
        }

        medium_risk_types = {SensitiveDataType.MEDICAL, SensitiveDataType.FINANCIAL}

        dtypes = {m.data_type for m in matches}

        if dtypes & high_risk_types:
            return PrivacyTier.RESTRICTED
        elif dtypes & medium_risk_types:
            return PrivacyTier.SENSITIVE
        elif SensitiveDataType.EMAIL in dtypes or SensitiveDataType.PHONE in dtypes:
            return PrivacyTier.PRIVATE

        return PrivacyTier.INTERNAL

    def _generate_recommendations(
        self, matches: List[SensitiveMatch], tier: PrivacyTier
    ) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []

        if tier == PrivacyTier.RESTRICTED:
            recommendations.append(
                "CRITICAL: This content contains highly sensitive data. "
                "Consider removing or encrypting before ingestion."
            )

        dtypes = {m.data_type for m in matches}

        if SensitiveDataType.API_KEY in dtypes:
            recommendations.append(
                "API keys detected. These should be stored in environment "
                "variables or a secure vault, not in documents."
            )

        if SensitiveDataType.PASSWORD in dtypes:
            recommendations.append(
                "Passwords detected. Remove before processing and use a "
                "password manager instead."
            )

        if SensitiveDataType.SSN in dtypes:
            recommendations.append(
                "Social Security numbers detected. This content should not "
                "be indexed in a searchable database."
            )

        if tier in {PrivacyTier.SENSITIVE, PrivacyTier.RESTRICTED}:
            recommendations.append("Consider applying content encryption and access controls.")

        return recommendations


class PrivacyAuditManager:
    """
    Manage privacy audits across the knowledge base.

    Tracks audit history, enforces policies, and generates reports.
    """

    def __init__(self, state_dir: Optional[Path] = None, auto_block_restricted: bool = True):
        """
        Initialize audit manager.

        Args:
            state_dir: Directory for audit logs
            auto_block_restricted: Block processing of restricted content
        """
        from src.config import STATE_DIR

        self.state_dir = state_dir or STATE_DIR / "privacy"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.scanner = PrivacyScanner()
        self.auto_block_restricted = auto_block_restricted

        self._audit_log: List[AuditResult] = []
        self._blocked_files: Set[str] = set()

        self._load_state()

    def audit_file(self, file_path: Path) -> AuditResult:
        """
        Audit a file for sensitive content.

        Args:
            file_path: Path to file to audit

        Returns:
            AuditResult
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Could not read file for audit: {e}")
            return AuditResult(
                file_path=str(file_path),
                timestamp=datetime.now().isoformat(),
                privacy_tier=PrivacyTier.RESTRICTED,
                recommendations=["Could not read file for audit"],
            )

        result = self.scanner.scan(content, str(file_path))

        # Log the audit
        self._audit_log.append(result)

        # Block if restricted
        if self.auto_block_restricted and result.privacy_tier == PrivacyTier.RESTRICTED:
            self._blocked_files.add(str(file_path))
            logger.warning(f"Blocked restricted file: {file_path}")

        self._save_state()

        return result

    def audit_content(self, content: str, source_id: Optional[str] = None) -> AuditResult:
        """
        Audit content string.

        Args:
            content: Text to audit
            source_id: Optional identifier for logging

        Returns:
            AuditResult
        """
        result = self.scanner.scan(content, source_id)
        self._audit_log.append(result)
        self._save_state()
        return result

    def is_blocked(self, file_path: str) -> bool:
        """Check if a file is blocked."""
        return file_path in self._blocked_files

    def approve_file(self, file_path: str, reviewer: str) -> bool:
        """
        Approve a blocked file for processing.

        Args:
            file_path: Path to the file
            reviewer: Who approved it

        Returns:
            True if successfully approved
        """
        if file_path in self._blocked_files:
            self._blocked_files.remove(file_path)
            logger.info(f"File approved by {reviewer}: {file_path}")
            self._save_state()
            return True
        return False

    def get_audit_report(
        self, since: Optional[datetime] = None, tier: Optional[PrivacyTier] = None
    ) -> Dict:
        """
        Generate audit report.

        Args:
            since: Filter to audits after this time
            tier: Filter to specific tier

        Returns:
            Report dictionary
        """
        audits = self._audit_log

        if since:
            audits = [a for a in audits if datetime.fromisoformat(a.timestamp) >= since]

        if tier:
            audits = [a for a in audits if a.privacy_tier == tier]

        # Count by tier
        tier_counts = {}
        for t in PrivacyTier:
            tier_counts[t.value] = sum(1 for a in audits if a.privacy_tier == t)

        # Count by data type
        type_counts: dict[str, int] = {}
        for a in audits:
            for m in a.matches:
                type_counts[m.data_type.value] = type_counts.get(m.data_type.value, 0) + 1

        return {
            "total_audits": len(audits),
            "blocked_files": len(self._blocked_files),
            "by_tier": tier_counts,
            "by_data_type": type_counts,
            "high_risk_count": sum(1 for a in audits if a.risk_level == "high"),
            "generated_at": datetime.now().isoformat(),
        }

    def export_audit_log(self, output_path: Path) -> None:
        """Export audit log to JSON."""
        with open(output_path, "w") as f:
            log_data = []
            for audit in self._audit_log:
                log_data.append(
                    {
                        "file_path": audit.file_path,
                        "timestamp": audit.timestamp,
                        "privacy_tier": audit.privacy_tier.value,
                        "risk_level": audit.risk_level,
                        "match_count": len(audit.matches),
                        "recommendations": audit.recommendations,
                    }
                )
            json.dump(log_data, f, indent=2)

    def _load_state(self) -> None:
        """Load state from disk."""
        blocked_file = self.state_dir / "blocked_files.json"
        if blocked_file.exists():
            try:
                with open(blocked_file) as f:
                    self._blocked_files = set(json.load(f))
            except Exception as e:
                logger.error(f"Failed to load blocked files: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        blocked_file = self.state_dir / "blocked_files.json"
        with open(blocked_file, "w") as f:
            json.dump(list(self._blocked_files), f, indent=2)


# ── Custom PII Dictionary ─────────────────────────────────────────────────────

# Maps user-facing type names to SensitiveDataType enum values
_CUSTOM_TYPE_MAP = {
    "SSN": SensitiveDataType.SSN,
    "EMAIL": SensitiveDataType.EMAIL,
    "PHONE": SensitiveDataType.PHONE,
    "ADDRESS": SensitiveDataType.ADDRESS,
    "NAME": SensitiveDataType.NAME,
    "CREDIT_CARD": SensitiveDataType.CREDIT_CARD,
    "ACCOUNT": SensitiveDataType.ACCOUNT,
    "EMPLOYEE_ID": SensitiveDataType.EMPLOYEE_ID,
    "POLICY": SensitiveDataType.POLICY,
    "FINANCIAL": SensitiveDataType.FINANCIAL,
    "MEDICAL": SensitiveDataType.MEDICAL,
    "CUSTOM": SensitiveDataType.CUSTOM,
}


def load_custom_pii_terms(path: Optional[Path] = None) -> list[dict]:
    """Load user-defined PII terms from a YAML file.

    Args:
        path: Path to the YAML file. Defaults to ~/.corerag/pii_terms.yaml

    Returns:
        List of term dicts with 'value' and 'type' keys, or empty list if
        the file doesn't exist or can't be parsed.
    """
    if path is None:
        from src.config import STATE_DIR

        path = STATE_DIR / "pii_terms.yaml"

    if not path.exists():
        return []

    try:
        import yaml

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data.get("terms"), list):
            return []

        terms = []
        for entry in data["terms"]:
            value = entry.get("value", "").strip()
            type_name = entry.get("type", "CUSTOM").strip().upper()
            if value:
                terms.append({"value": value, "type": type_name})

        logger.info(f"Loaded {len(terms)} custom PII terms from {path}")
        return terms

    except Exception as e:
        logger.error(f"Failed to load custom PII terms from {path}: {e}")
        return []


def scan_custom_terms(
    content: str, terms: list[dict], context_chars: int = 50
) -> list[SensitiveMatch]:
    """Match user-defined PII terms against document text.

    Uses case-insensitive exact string matching. Each match gets
    confidence=1.0 since these are user-confirmed PII values.

    Args:
        content: Document text to scan
        terms: List of term dicts from load_custom_pii_terms()
        context_chars: Characters of surrounding context to include

    Returns:
        List of SensitiveMatch objects for all matches found
    """
    if not terms:
        return []

    matches = []
    content_lower = content.lower()

    for term in terms:
        value = term["value"]
        type_name = term["type"]
        dtype = _CUSTOM_TYPE_MAP.get(type_name, SensitiveDataType.CUSTOM)
        value_lower = value.lower()

        # Find all occurrences
        start = 0
        while True:
            pos = content_lower.find(value_lower, start)
            if pos == -1:
                break

            end_pos = pos + len(value)
            ctx_start = max(0, pos - context_chars)
            ctx_end = min(len(content), end_pos + context_chars)
            context = content[ctx_start:ctx_end]

            # Redact the value in matched_text and context
            redacted_value = f"***{value[-4:]}" if len(value) > 4 else "***"

            matches.append(
                SensitiveMatch(
                    data_type=dtype,
                    matched_text=redacted_value,
                    start_pos=pos,
                    end_pos=end_pos,
                    confidence=1.0,
                    context=context.replace(value, redacted_value),
                )
            )

            start = end_pos  # Move past this match

    if matches:
        logger.info(f"Custom PII dictionary matched {len(matches)} term(s)")

    return matches


# Convenience function for quick privacy check
def check_privacy(content: str) -> Tuple[PrivacyTier, List[str]]:
    """
    Quick privacy check for content.

    Returns:
        Tuple of (PrivacyTier, list of recommendations)
    """
    scanner = PrivacyScanner()
    result = scanner.scan(content)
    return result.privacy_tier, result.recommendations
