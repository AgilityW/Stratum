"""Schema validation tests for ArticleRecord."""

import json
import jsonschema
import pytest


@pytest.fixture
def article_schema(schemas_dir):
    schema_path = schemas_dir / "article-record.schema.json"
    with open(schema_path) as f:
        return json.load(f)


class TestArticleRecordRequired:
    def test_all_required_fields(self, article_schema):
        valid = {
            "id": "abc123",
            "url": "https://example.com/article",
            "title": "Test Article",
            "source": "Example News",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
        }
        jsonschema.validate(valid, article_schema)  # should not raise

    def test_missing_id_fails(self, article_schema):
        invalid = {
            "url": "https://example.com/article",
            "title": "Test Article",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, article_schema)

    def test_missing_url_fails(self, article_schema):
        invalid = {
            "id": "abc",
            "title": "Test",
            "source": "x",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, article_schema)


class TestArticleRecordValidation:
    def test_valid_full_record(self, article_schema):
        record = {
            "id": "a1b2c3",
            "url": "https://news.skhynix.com/hbm4-production",
            "canonical_url": "https://news.skhynix.com/hbm4-production",
            "title": "SK hynix Begins HBM4 Mass Production",
            "source": "SK hynix Newsroom",
            "source_type": "official",
            "source_locale": "en",
            "date": "2025-06-15",
            "published_at": "2025-06-15T09:00:00+09:00",
            "fetched_at": "2025-06-15T12:00:00Z",
            "snippet": "SK hynix announced HBM4 mass production.",
            "extracted_summary": "HBM4 enters mass production with 1.5TB/s bandwidth.",
            "content_hash": "sha256:deadbeef",
            "entities": ["skhynix"],
            "terms": ["hbm4", "advanced-packaging"],
            "numeric_claims": ["1.5TB/s bandwidth"],
            "verification_status": "verified",
            "rejection_reason": None,
            "discovery_mode": "baseline_seed",
            "artifact_type": "news_article",
            "cluster_id": "sc-2025-06-15-001",
            "event_thread_id": None,
        }
        jsonschema.validate(record, article_schema)

    def test_invalid_source_type(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "invalid_type",  # not in enum
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, article_schema)

    def test_invalid_locale_pattern(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "media",
            "source_locale": "eng",  # should be en
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, article_schema)

    def test_valid_locale_with_region(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "测试文章",
            "source": "示例",
            "source_type": "media",
            "source_locale": "zh-CN",
            "published_at": "2025-06-15T10:00:00+08:00",
            "date": "2025-06-15",
            "artifact_type": "news_article",
        }
        jsonschema.validate(record, article_schema)

    def test_invalid_date_format(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "15-06-2025",  # wrong format
            "artifact_type": "news_article",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, article_schema)

    def test_invalid_verification_status(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
            "verification_status": "pending",  # not in enum
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, article_schema)

    def test_valid_artifact_types(self, article_schema):
        for atype in ["news_article", "patent", "paper", "hiring", "financial_transcript",
                       "product_announcement", "satellite_image", "conference_abstract"]:
            record = {
                "id": "abc",
                "url": "https://example.com/article",
                "title": "Test",
                "source": "Example",
                "source_type": "media",
                "source_locale": "en",
                "published_at": "2025-06-15T10:00:00Z",
                "date": "2025-06-15",
                "artifact_type": atype,
            }
            jsonschema.validate(record, article_schema)

    def test_invalid_artifact_type(self, article_schema):
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "podcast",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, article_schema)

    def test_nullable_fields(self, article_schema):
        """cluster_id, event_thread_id, rejection_reason can be null."""
        record = {
            "id": "abc",
            "url": "https://example.com/article",
            "title": "Test",
            "source": "Example",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
            "cluster_id": None,
            "event_thread_id": None,
            "rejection_reason": None,
        }
        jsonschema.validate(record, article_schema)
