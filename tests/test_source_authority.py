"""Tests for the source authority classifier."""

from src.classification.source_authority import SourceAuthority, SourceAuthorityClassifier


class TestSourceAuthorityClassifier:
    def setup_method(self):
        self.classifier = SourceAuthorityClassifier()

    def test_official_by_tag(self):
        result = self.classifier.classify({"tags": ["gov-document", "tax-2024"]})
        assert result == SourceAuthority.OFFICIAL

    def test_professional_by_category(self):
        result = self.classifier.classify({"category": "work"})
        assert result == SourceAuthority.PROFESSIONAL

    def test_educational_by_tag(self):
        result = self.classifier.classify({"tags": ["sphr-study"]})
        assert result == SourceAuthority.EDUCATIONAL

    def test_personal_by_category(self):
        result = self.classifier.classify({"category": "notes"})
        assert result == SourceAuthority.PERSONAL

    def test_unknown_default(self):
        result = self.classifier.classify({})
        assert result == SourceAuthority.UNKNOWN

    def test_extension_fallback(self):
        result = self.classifier.classify({"source_path": "report.pdf"})
        assert result == SourceAuthority.PROFESSIONAL

    def test_md_extension(self):
        result = self.classifier.classify({"source_path": "my_notes.md"})
        assert result == SourceAuthority.PERSONAL

    def test_tag_priority_over_category(self):
        """Tags take priority over category."""
        result = self.classifier.classify(
            {
                "tags": ["official"],
                "category": "personal",
            }
        )
        assert result == SourceAuthority.OFFICIAL

    def test_comma_delimited_tags_string(self):
        """Handle LanceDB-style comma-delimited tag strings."""
        result = self.classifier.classify({"tags": ",cert-prep,sphr-study,"})
        assert result == SourceAuthority.PROFESSIONAL

    def test_certification_category(self):
        result = self.classifier.classify({"category": "certification"})
        assert result == SourceAuthority.PROFESSIONAL

    def test_education_category(self):
        result = self.classifier.classify({"category": "education"})
        assert result == SourceAuthority.EDUCATIONAL

    def test_enum_values(self):
        """Verify enum string values for storage."""
        assert SourceAuthority.OFFICIAL.value == "official"
        assert SourceAuthority.UNKNOWN.value == "unknown"
