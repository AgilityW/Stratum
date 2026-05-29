"""Tests for verify stage — domain-agnostic article verification."""
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.verify.verify import (
    verify_article, is_blocklisted, validate_date,
    check_magnitude, extract_domain
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

    def test_no_date_rejected(self):
        article = {"url": "https://example.com/news", "title": "Test", "snippet": "No date here"}
        result = verify_article(article, "2026-05-28", 0, MOCK_PIPELINE_CONFIG)
        assert result["verification_status"] == "rejected"
        assert result["rejection_reason"] == "NO_DATE"

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
