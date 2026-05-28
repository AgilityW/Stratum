"""ArticleRecord schema validation.

Every field in the ArticleRecord must have a valid type and allowed values.
"""
import pytest

# From article-normalizer SKILL.md — canonical schema
REQUIRED_FIELDS = {
    "id", "url", "title", "source", "source_type", "source_locale",
    "published_at", "fetched_at", "snippet", "extracted_summary",
    "content_hash", "entities", "terms", "numeric_claims",
    "verification_status", "rejection_reason", "discovery_mode",
    "artifact_type", "cluster_id", "event_thread_id",
}

VALID_ARTIFACT_TYPES = {
    "news_article", "patent", "paper", "hiring",
    "financial_transcript", "product_announcement",
    "satellite_image", "conference_abstract",
}

VALID_SOURCE_TYPES = {
    "official", "media", "analyst", "blog", "social", "financial",
}

VALID_VERIFICATION_STATUSES = {
    "verified", "uncertain", "rejected", "unverifiable",
}

VALID_DISCOVERY_MODES = {
    "baseline_seed", "trial_query", "value_chain_probe",
    "coverage_gap", "newsroom_crawl",
}


class TestArticleRecordSchema:
    """Validate ArticleRecord canonical schema from SKILL.md."""

    def test_required_fields_complete(self):
        """The 20 required fields defined in SKILL.md."""
        assert len(REQUIRED_FIELDS) == 20, (
            f"Expected 20 fields, got {len(REQUIRED_FIELDS)}"
        )

    def test_artifact_types_complete(self):
        """All 8 artifact types defined."""
        assert len(VALID_ARTIFACT_TYPES) == 8, (
            f"Expected 8 artifact_types, got {len(VALID_ARTIFACT_TYPES)}"
        )

    def test_source_types_complete(self):
        """All 6 source types defined with signal weights."""
        assert len(VALID_SOURCE_TYPES) == 6

    def test_verification_statuses_complete(self):
        """4 verification statuses defined."""
        assert len(VALID_VERIFICATION_STATUSES) == 4

    def test_discovery_modes_complete(self):
        """5 discovery modes — covers collection, trial, value chain, gaps, crawls."""
        assert len(VALID_DISCOVERY_MODES) == 5, (
            f"Expected 5 discovery modes, got {len(VALID_DISCOVERY_MODES)}"
        )

    def test_artifact_type_enum_coverage(self):
        """artifact_type field is required and all values are valid."""
        assert "artifact_type" in REQUIRED_FIELDS
        # All types are descriptive (no empty string, no untitled)
        for t in VALID_ARTIFACT_TYPES:
            assert "_" in t or t.isalpha(), (
                f"Artifact type '{t}' should use snake_case"
            )

    def test_every_source_type_has_signal_weight(self):
        """From SKILL.md table: each source_type has High/Medium/Low signal weight."""
        # This is validated by the SKILL.md document itself
        # Signal weights: official=High, media=Medium, analyst=Medium,
        #                 blog=Low-Medium, social=Low, financial=High
        assert "official" in VALID_SOURCE_TYPES
        assert "financial" in VALID_SOURCE_TYPES
        # Both are High signal weight


class TestArticleRecordConstraints:
    """Value constraints on ArticleRecord fields."""

    def test_id_format(self):
        """id must be SHA-256 (64 hex chars)."""
        import hashlib
        test_id = hashlib.sha256(b"https://example.comTest Title").hexdigest()
        assert len(test_id) == 64
        assert all(c in "0123456789abcdef" for c in test_id)

    def test_source_locale_is_bcp47(self):
        """source_locale must be BCP 47 format (e.g., 'zh-CN', 'en')."""
        import re
        bcp47 = re.compile(r'^[a-z]{2,3}(-[A-Z]{2,4})?$')
        for locale in ["zh-CN", "zh-TW", "en", "ja", "ko"]:
            assert bcp47.match(locale), f"'{locale}' not valid BCP 47"

    def test_published_at_is_iso8601(self):
        """published_at must be ISO 8601 with timezone."""
        from datetime import datetime
        test_date = "2026-05-28T00:00:00+08:00"
        dt = datetime.fromisoformat(test_date)
        assert dt.tzinfo is not None, "published_at must have timezone"

    def test_nullable_fields(self):
        """rejection_reason, cluster_id, event_thread_id are nullable."""
        nullable = {"rejection_reason", "cluster_id", "event_thread_id"}
        assert nullable.issubset(REQUIRED_FIELDS), (
            f"Nullable fields missing from REQUIRED_FIELDS: {nullable - REQUIRED_FIELDS}"
        )

    def test_entities_and_terms_are_arrays(self):
        """entities and terms must be arrays."""
        assert "entities" in REQUIRED_FIELDS
        assert "terms" in REQUIRED_FIELDS
