"""Tests for normalize stage — domain-agnostic article normalization."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.normalize.normalize import (
    classify_source_type, classify_artifact_type, extract_entities,
    extract_terms, extract_numeric_claims, normalize_article,
    determine_source_locale, content_hash,
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


class TestNormalizeArticle:
    def test_verified_article_normalized(self):
        article = {
            "verification_status": "verified",
            "url": "https://reuters.com/tech/samsung-hbm4",
            "title": "Samsung ships HBM4 to NVIDIA",
            "snippet": "Samsung Electronics announced HBM4 production milestone",
            "published_at": "2026-05-28T00:00:00+08:00",
            "source": "reuters.com",
            "query_used": "Samsung HBM4",
        }
        result = normalize_article(article, MOCK_PIPELINE_CONFIG, 0)
        assert result is not None
        assert result["source_type"] == "media"
        assert result["source_locale"] == "en"
        assert "Samsung" in result["entities"]
        assert "HBM" in result["terms"]
        assert "NVIDIA" in result["entities"]

    def test_rejected_article_skipped(self):
        article = {"verification_status": "rejected", "title": "Bad", "url": "https://x.com"}
        result = normalize_article(article, MOCK_PIPELINE_CONFIG, 0)
        assert result is None


class TestContentHash:
    def test_same_input_same_hash(self):
        h1 = content_hash("https://example.com", "Title")
        h2 = content_hash("https://example.com", "Title")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = content_hash("https://example.com", "Title A")
        h2 = content_hash("https://example.com", "Title B")
        assert h1 != h2
