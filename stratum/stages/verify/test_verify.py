"""Tests for verify stage — domain-agnostic article verification."""
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.verify.verify import (
    verify_article, is_blocklisted, validate_date,
    check_magnitude, extract_domain, check_duplicate,
    date_confidence_for_source, date_confidence_meets_minimum,
    build_verification_stats, default_stats_path,
    is_low_priority_domain,
)

MOCK_PIPELINE_CONFIG = {
    "blocklist": {
        "social": ["youtube.com", "reddit.com", "twitter.com", "x.com"],
        "encyclopedia": ["wikipedia.org"],
    },
    "low_priority_domains": ["bing.com", "google.com"],
    "magnitude_rules": {
        "revenue_max_usd": 1_000_000_000_000,
        "share_max_pct": 100,
        "growth_max_pct": 1000,
        "chip_price_max_usd": 10_000,
    },
    "date_window": {
        "stale_days": 2,
        "max_future_days": 1,
    },
}


class TestExtractDomain:
    def test_basic(self):
        assert extract_domain("https://www.example.com/article") == "example.com"

    def test_no_www(self):
        assert extract_domain("https://reuters.com/news") == "reuters.com"

    def test_mobile_prefix(self):
        assert extract_domain("https://m.example.com/article") == "example.com"

    def test_empty(self):
        assert extract_domain("") == ""


class TestBlocklist:
    def test_social_blocked(self):
        blocked, reason = is_blocklisted("https://youtube.com/watch?v=123", MOCK_PIPELINE_CONFIG["blocklist"])
        assert blocked
        assert "youtube.com" in reason

    def test_wiki_blocked(self):
        blocked, _ = is_blocklisted("https://en.wikipedia.org/wiki/NAND", MOCK_PIPELINE_CONFIG["blocklist"])
        assert blocked

    def test_reuters_not_blocked(self):
        blocked, _ = is_blocklisted("https://www.reuters.com/technology", MOCK_PIPELINE_CONFIG["blocklist"])
        assert not blocked

    def test_impostor_domain_not_blocked_by_substring(self):
        blocked, _ = is_blocklisted("https://notyoutube.com/article", MOCK_PIPELINE_CONFIG["blocklist"])
        assert not blocked

    def test_blocklist_matches_subdomains(self):
        blocked, reason = is_blocklisted("https://m.youtube.com/watch?v=123", MOCK_PIPELINE_CONFIG["blocklist"])
        assert blocked
        assert reason == "BLOCKED: youtube.com"


class TestLowPriority:
    def test_low_priority_matches_subdomains(self):
        assert is_low_priority_domain("https://news.google.com/search?q=hbm", {"google.com"})

    def test_low_priority_does_not_match_impostor_domain(self):
        assert not is_low_priority_domain("https://notgoogle.com/search?q=hbm", {"google.com"})


class TestVerifyArticle:
    def test_blocklisted_article_rejected(self):
        article = {"url": "https://youtube.com/watch?v=123", "title": "Test", "snippet": ""}
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "rejected"
        assert "BLOCKED" in result["rejection_reason"]

    def test_low_priority_rejected(self):
        article = {"url": "https://bing.com/search?q=test", "title": "Test", "snippet": ""}
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "rejected"
        assert result["rejection_reason"] == "LOW_SIGNAL"

    def test_low_priority_subdomain_rejected(self):
        article = {"url": "https://news.google.com/search?q=test", "title": "Test", "snippet": ""}
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "rejected"
        assert result["rejection_reason"] == "LOW_SIGNAL"

    def test_no_date_rejected(self):
        article = {"url": "https://example.com/news", "title": "Test", "snippet": "No date here"}
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "rejected"
        assert result["rejection_reason"] == "NO_DATE"
        assert result["date_source"] == "none"

    def test_valid_article_verified(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "DRAM prices up 15%",
            "datePublished": "2026-05-28",
        }
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "verified"
        assert result["rejection_reason"] is None
        assert result["canonical_url"] == "https://reuters.com/technology/memory-chip"

    def test_preserves_date_source_lineage(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "DRAM prices up 15%",
            "datePublished": "2026-05-28",
            "date_source": "url_path",
        }
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "verified"
        assert result["date_source"] == "url_path"
        assert result["date_confidence"] == "high"

    def test_infers_snippet_regex_date_source_when_verify_extracts_date(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "Published on 2026-05-28; DRAM prices up 15%",
        }
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "verified"
        assert result["date_source"] == "snippet_regex"
        assert result["date_confidence"] == "low"
        assert result["quality_flags"] == ["LOW_CONFIDENCE_DATE"]

    def test_infers_search_api_date_source_for_unlabelled_metadata_date(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "DRAM prices up 15%",
            "datePublished": "2026-05-28",
        }
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "verified"
        assert result["date_source"] == "search_api"
        assert result["date_confidence"] == "high"

    def test_rejects_weak_date_source_when_domain_requires_medium_confidence(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "Published on 2026-05-28; DRAM prices up 15%",
        }
        config = {
            **MOCK_PIPELINE_CONFIG,
            "date_window": {
                **MOCK_PIPELINE_CONFIG["date_window"],
                "min_date_confidence": "medium",
            },
        }

        result = verify_article(article, "2026-05-28", 0, config)

        assert result["verification_status"] == "rejected"
        assert result["rejection_reason"] == "LOW_CONFIDENCE_DATE"
        assert result["date_source"] == "snippet_regex"
        assert result["date_confidence"] == "low"

    def test_freshness_window_is_medium_date_confidence(self):
        article = {
            "url": "https://reuters.com/technology/memory-chip",
            "title": "Memory chip prices rise",
            "snippet": "DRAM prices up 15%",
            "datePublished": "2026-05-28",
            "date_source": "freshness_window",
        }

        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)

        assert result["verification_status"] == "verified"
        assert result["date_confidence"] == "medium"

    def test_duplicate_uses_canonical_url(self):
        seen_urls = set()
        first = {
            "url": "https://www.example.com/story?utm_source=search",
            "title": "Samsung HBM4 update",
            "snippet": "Samsung HBM4 update",
            "datePublished": "2026-05-28",
        }
        second = {
            "url": "https://m.example.com/story/",
            "title": "Different headline",
            "snippet": "Samsung HBM4 update",
            "datePublished": "2026-05-28",
        }

        first_result = verify_article(
            first, "2026-05-28", 0, MOCK_PIPELINE_CONFIG,
            seen_urls=seen_urls, seen_titles={},
        )
        second_result = verify_article(
            second, "2026-05-28", 1, MOCK_PIPELINE_CONFIG,
            seen_urls=seen_urls, seen_titles={},
        )

        assert first_result["verification_status"] == "verified"
        assert second_result["verification_status"] == "rejected"
        assert second_result["rejection_reason"] == "DUPLICATE_URL"


class TestDuplicateCheck:
    def test_check_duplicate_accepts_canonical_keys(self):
        seen = {"https://example.com/story"}
        is_dup, reason = check_duplicate(
            "https://m.example.com/story/?utm_campaign=x",
            "Different title",
            seen,
            {},
        )
        assert is_dup
        assert reason == "DUPLICATE_URL"


class TestDateConfidence:
    def test_date_source_confidence_mapping(self):
        assert date_confidence_for_source("search_api") == "high"
        assert date_confidence_for_source("web_extract") == "high"
        assert date_confidence_for_source("url_path") == "high"
        assert date_confidence_for_source("freshness_window") == "medium"
        assert date_confidence_for_source("snippet_regex") == "low"
        assert date_confidence_for_source("none") == "none"

    def test_date_confidence_minimum_ordering(self):
        assert date_confidence_meets_minimum("high", "medium")
        assert date_confidence_meets_minimum("medium", "medium")
        assert not date_confidence_meets_minimum("low", "medium")


class TestVerificationStats:
    def test_default_stats_path(self):
        assert default_stats_path("/tmp/verified.jsonl") == "/tmp/verified.stats.json"
        assert default_stats_path(None) is None

    def test_build_verification_stats_summarizes_rejections_and_quality(self):
        stats = build_verification_stats([
            {
                "verification_status": "verified",
                "date_confidence": "high",
                "quality_flags": [],
            },
            {
                "verification_status": "verified",
                "date_confidence": "low",
                "quality_flags": ["LOW_CONFIDENCE_DATE"],
                "platform_admitted": True,
            },
            {
                "verification_status": "rejected",
                "rejection_reason": "BLOCKED: youtube.com",
            },
            {
                "verification_status": "rejected",
                "rejection_reason": "DUPLICATE_URL",
            },
        ], "2026-05-28")

        assert stats["date"] == "2026-05-28"
        assert stats["total"] == 4
        assert stats["verified"] == 2
        assert stats["rejected"] == 2
        assert stats["date_confidence"] == {"high": 1, "low": 1}
        assert stats["quality_flags"] == {"LOW_CONFIDENCE_DATE": 1}
        assert stats["reasons"] == {"BLOCKED: youtube.com": 1, "DUPLICATE_URL": 1}
        assert stats["blocklisted"] == 1
        assert stats["duplicates"] == 1
        assert stats["platform_admitted"] == 1


class TestMagnitudeCheck:
    def test_share_over_100_impossible(self):
        article = {
            "title": "Company dominates market",
            "snippet": "Company holds 150% market share in NAND",
            "url": "https://example.com",
        }
        flags = check_magnitude(article, MOCK_PIPELINE_CONFIG["magnitude_rules"])
        assert any("IMPOSSIBLE" in f for f in flags)

    def test_trillion_dollar_flag(self):
        article = {
            "title": "Company revenue",
            "snippet": "Company reports $2 trillion in revenue",
            "url": "https://example.com",
        }
        flags = check_magnitude(article, MOCK_PIPELINE_CONFIG["magnitude_rules"])
        assert any("FLAG" in f for f in flags)

    def test_normal_article_no_flags(self):
        article = {
            "title": "Normal report",
            "snippet": "Company reports 15% revenue growth",
            "url": "https://example.com",
        }
        flags = check_magnitude(article, MOCK_PIPELINE_CONFIG["magnitude_rules"])
        assert len(flags) == 0
