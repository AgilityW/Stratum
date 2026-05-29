"""Tests for enrich stage — date extraction from raw search results."""
import json
import pytest
import sys
import os

# Add stages to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.enrich.enrich import extract_date, enrich_article


class TestEnrichExtractDate:
    """Date extraction from various formats."""

    def test_iso_date(self):
        result = extract_date("Published 2026-05-28 by Reuters", "2026-05-28")
        assert result == "2026-05-28"

    def test_chinese_date(self):
        result = extract_date("2026年5月28日 发布", "2026-05-28")
        assert result == "2026-05-28"

    def test_english_long_date(self):
        result = extract_date("May 28, 2026 — SK hynix announced", "2026-05-29")
        assert result == "2026-05-28"

    def test_english_short_date(self):
        result = extract_date("On 28 May 2026, Micron reported", "2026-05-29")
        assert result == "2026-05-28"

    def test_relative_today_en(self):
        result = extract_date("Published today by Reuters", "2026-05-28")
        assert result == "2026-05-28"

    def test_relative_today_zh(self):
        result = extract_date("今天发布", "2026-05-28")
        assert result == "2026-05-28"

    def test_relative_yesterday(self):
        result = extract_date("Published yesterday", "2026-05-28")
        assert result == "2026-05-27"

    def test_empty_text(self):
        result = extract_date("", "2026-05-28")
        assert result is None

    def test_far_future_rejected(self):
        """Dates more than 365 days from run_date are rejected."""
        result = extract_date("Published 2028-05-28", "2026-05-28")
        assert result is None

    def test_far_past_rejected(self):
        result = extract_date("Published 2020-05-28", "2026-05-28")
        assert result is None


class TestEnrichArticle:
    """Article-level enrichment."""

    def test_respects_existing_date(self):
        article = {
            "title": "Test", "url": "https://example.com",
            "datePublished": "2026-05-28", "snippet": ""
        }
        result = enrich_article(article, "2026-05-29")
        assert result["datePublished"] == "2026-05-28"
        assert result["date_source"] == "web_extract"

    def test_extracts_from_snippet(self):
        article = {
            "title": "Test", "url": "https://example.com",
            "datePublished": "", "snippet": "Published on May 28, 2026"
        }
        result = enrich_article(article, "2026-05-28")
        assert result["datePublished"] == "2026-05-28"
        assert result["date_source"] == "snippet_regex"

    def test_no_date_found(self):
        article = {
            "title": "No date here", "url": "https://example.com",
            "datePublished": "", "snippet": "Just some text without dates"
        }
        result = enrich_article(article, "2026-05-28")
        assert result["datePublished"] == ""
        assert result["date_source"] == "none"
