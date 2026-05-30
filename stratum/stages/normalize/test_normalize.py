"""Tests for normalize stage — domain-agnostic article normalization."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.normalize.normalize import (
    classify_source_type, classify_artifact_type, extract_entities,
    extract_terms, extract_numeric_claims, normalize_article,
    determine_source_locale, resolve_source_locale, content_hash,
    normalize_source_type, resolve_source_type, match_thread_keywords,
)

MOCK_PIPELINE_CONFIG = {
    "source_classification": {
        "official": ["samsung.com", "micron.com"],
        "analyst": ["trendforce.com"],
        "media": ["reuters.com", "bloomberg.com", "nikkei.com"],
        "blog": ["medium.com"],
    },
    "artifact_types": {
        "financial_transcript": {"pattern": r"(earnings|quarterly\s+result)"},
        "product_announcement": {"pattern": r"(announce|launch|release|推出)"},
        "patent": {"pattern": r"(patent|专利)"},
    },
    "flat_entities": ["Samsung", "Micron", "SK hynix", "NVIDIA"],
    "flat_terms": ["HBM", "DRAM", "NAND", "DDR5", "SSD"],
    "numeric_patterns": [
        r'(\+\d+(?:\.\d+)?%\s*(?:QoQ|YoY))',
        r'(\$\d+(?:\.\d+)?\s*(?:billion|million)\b)',
    ],
    "locale_rules": {
        "domain_patterns": [
            {"pattern": ".jp", "locale": "ja", "keywords": ["nikkei", "kioxia"]},
            {"pattern": ".cn", "locale": "zh-CN"},
            {"pattern": ".tw", "locale": "zh-TW"},
            {"pattern": ".kr", "locale": "ko"},
        ],
        "default_locale": "en",
    },
}


class TestSourceClassification:
    def test_official(self):
        assert classify_source_type("https://samsung.com/news", MOCK_PIPELINE_CONFIG["source_classification"]) == "official"

    def test_analyst(self):
        assert classify_source_type("https://trendforce.com/report", MOCK_PIPELINE_CONFIG["source_classification"]) == "analyst"

    def test_media(self):
        assert classify_source_type("https://reuters.com/technology", MOCK_PIPELINE_CONFIG["source_classification"]) == "media"

    def test_default_media(self):
        assert classify_source_type("https://newsite.com/article", MOCK_PIPELINE_CONFIG["source_classification"]) == "media"

    def test_mobile_prefix_normalized_for_classification(self):
        assert classify_source_type("https://m.reuters.com/technology", MOCK_PIPELINE_CONFIG["source_classification"]) == "media"

    def test_source_classification_respects_domain_boundaries(self):
        assert classify_source_type(
            "https://fakesamsung.com/news",
            MOCK_PIPELINE_CONFIG["source_classification"],
        ) == "media"
        assert classify_source_type(
            "https://asia.reuters.com/technology",
            MOCK_PIPELINE_CONFIG["source_classification"],
        ) == "media"

    def test_source_type_hint_wins(self):
        article = {"source_type_hint": "official"}
        assert resolve_source_type(
            article,
            "https://example.com/article",
            MOCK_PIPELINE_CONFIG["source_classification"],
        ) == "official"

    def test_source_type_alias_normalized(self):
        assert normalize_source_type("newsroom") == "official"
        assert normalize_source_type("rss") == "media"


class TestArtifactClassification:
    def test_financial(self):
        assert classify_artifact_type("Q1 earnings result", "Quarterly revenue up",
                                      MOCK_PIPELINE_CONFIG["artifact_types"]) == "financial_transcript"

    def test_product(self):
        assert classify_artifact_type("Samsung launches HBM4", "New product announced",
                                      MOCK_PIPELINE_CONFIG["artifact_types"]) == "product_announcement"

    def test_default_news(self):
        assert classify_artifact_type("Market update", "General news about the industry",
                                      MOCK_PIPELINE_CONFIG["artifact_types"]) == "news_article"


class TestEntityExtraction:
    def test_extracts_entities(self):
        entities = extract_entities("Samsung and Micron report earnings",
                                     "SK hynix also announces HBM production",
                                     MOCK_PIPELINE_CONFIG["flat_entities"])
        assert "Samsung" in entities
        assert "Micron" in entities
        assert "SK hynix" in entities

    def test_no_entities(self):
        entities = extract_entities("Random news", "Nothing relevant",
                                     MOCK_PIPELINE_CONFIG["flat_entities"])
        assert len(entities) == 0


class TestTermExtraction:
    def test_extracts_terms(self):
        terms = extract_terms("HBM and DRAM prices", "DDR5 production update",
                               MOCK_PIPELINE_CONFIG["flat_terms"])
        assert "HBM" in terms
        assert "DRAM" in terms
        assert "DDR5" in terms


class TestNumericExtraction:
    def test_extracts_qoq(self):
        claims = extract_numeric_claims("Revenue up +15% QoQ and +20% YoY",
                                         MOCK_PIPELINE_CONFIG["numeric_patterns"])
        assert "+15% QoQ" in claims

    def test_extracts_billion(self):
        claims = extract_numeric_claims("Revenue reached $3.2 billion",
                                         MOCK_PIPELINE_CONFIG["numeric_patterns"])
        assert "$3.2 billion" in claims


class TestLocaleRouting:
    def test_japanese(self):
        assert determine_source_locale("https://www.nikkei.com/article",
                                        MOCK_PIPELINE_CONFIG["locale_rules"]) == "ja"

    def test_chinese(self):
        assert determine_source_locale("https://example.cn/news",
                                        MOCK_PIPELINE_CONFIG["locale_rules"]) == "zh-CN"

    def test_default_english(self):
        assert determine_source_locale("https://example.com/news",
                                        MOCK_PIPELINE_CONFIG["locale_rules"]) == "en"

    def test_explicit_locale_wins_over_url_heuristic(self):
        article = {"raw_metadata": {"locale": "zh-CN"}}
        assert resolve_source_locale(
            article,
            "https://www.eet-china.com/article",
            MOCK_PIPELINE_CONFIG["locale_rules"],
        ) == "zh-CN"


class TestNormalizeArticle:
    def test_verified_article_normalized(self):
        article = {
            "verification_status": "verified",
            "url": "https://reuters.com/tech/samsung-hbm4",
            "canonical_url": "https://reuters.com/tech/samsung-hbm4",
            "title": "Samsung ships HBM4 to NVIDIA",
            "snippet": "Samsung Electronics announced HBM4 production milestone",
            "published_at": "2026-05-28T00:00:00+08:00",
            "date_source": "snippet_regex",
            "date_confidence": "low",
            "quality_flags": ["LOW_CONFIDENCE_DATE"],
            "source": "reuters.com",
            "query_used": "Samsung HBM4",
            "query_id": "q-storage-1",
            "query_dimension": "verification",
            "source_type_hint": "official",
            "engine": "tavily",
            "discovery_mode": "coverage_gap",
        }
        result = normalize_article(article, MOCK_PIPELINE_CONFIG, 0)
        assert result is not None
        assert result["source_type"] == "official"
        assert result["source_locale"] == "en"
        assert "Samsung" in result["entities"]
        assert "HBM" in result["terms"]
        assert "NVIDIA" in result["entities"]
        assert result["date_source"] == "snippet_regex"
        assert result["date_confidence"] == "low"
        assert result["quality_flags"] == ["LOW_CONFIDENCE_DATE"]
        assert result["canonical_url"] == "https://reuters.com/tech/samsung-hbm4"
        assert result["query_id"] == "q-storage-1"
        assert result["query_dimension"] == "verification"
        assert result["engine"] == "tavily"
        assert result["discovery_mode"] == "coverage_gap"

    def test_canonical_url_controls_id_and_hash(self):
        base = {
            "verification_status": "verified",
            "url": "https://www.example.com/story?utm_source=search",
            "title": "Samsung HBM4 update",
            "snippet": "Samsung HBM4 update",
            "published_at": "2026-05-28T00:00:00+08:00",
            "source": "example.com",
        }
        variant = {**base, "url": "https://m.example.com/story/"}

        first = normalize_article(base, MOCK_PIPELINE_CONFIG, 0)
        second = normalize_article(variant, MOCK_PIPELINE_CONFIG, 1)

        assert first["canonical_url"] == "https://example.com/story"
        assert second["canonical_url"] == "https://example.com/story"
        assert first["id"] == second["id"]
        assert first["content_hash"] == second["content_hash"]

    def test_rejected_article_skipped(self):
        article = {"verification_status": "rejected", "title": "Bad", "url": "https://x.com"}
        result = normalize_article(article, MOCK_PIPELINE_CONFIG, 0)
        assert result is None

    def test_thread_keywords_add_only_matched_terms(self):
        article = {
            "verification_status": "verified",
            "url": "https://reuters.com/tech/samsung-hbm4",
            "title": "Samsung ships HBM4",
            "snippet": "Samsung begins HBM4 shipments",
            "published_at": "2026-05-28T00:00:00+08:00",
            "source": "reuters.com",
        }
        thread_keywords = {
            "threads": [{
                "thread_id": "et-storage-0001",
                "keywords": ["samsung", "hbm4", "sk hynix", "supply shortage"],
                "topics": ["advanced packaging"],
            }]
        }

        result = normalize_article(article, MOCK_PIPELINE_CONFIG, 0, thread_keywords)

        assert result["event_thread_id"] == "et-storage-0001"
        assert "samsung" in result["terms"]
        assert "hbm4" in result["terms"]
        assert "sk hynix" not in result["terms"]
        assert "supply shortage" not in result["terms"]
        assert "advanced packaging" not in result["terms"]


class TestThreadKeywordMatching:
    def test_returns_only_tokens_present_in_article(self):
        thread_id, tokens = match_thread_keywords(
            "Samsung HBM4 production",
            "HBM4 ships to customers",
            {
                "threads": [{
                    "thread_id": "et-storage-0001",
                    "keywords": ["samsung", "hbm4", "micron", "supply shortage"],
                    "topics": ["advanced packaging"],
                }]
            },
        )

        assert thread_id == "et-storage-0001"
        assert tokens == ["samsung", "hbm4"]


class TestContentHash:
    def test_same_input_same_hash(self):
        h1 = content_hash("https://example.com", "Title")
        h2 = content_hash("https://example.com", "Title")
        assert h1 == h2

    def test_url_variants_same_hash(self):
        h1 = content_hash("https://www.example.com/story?utm_source=x", "Title")
        h2 = content_hash("https://m.example.com/story/", "Title")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = content_hash("https://example.com", "Title A")
        h2 = content_hash("https://example.com", "Title B")
        assert h1 != h2
