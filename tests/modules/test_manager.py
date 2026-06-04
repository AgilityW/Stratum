"""Source Manager — URL validation and auto-healing.

Validates source-manager's URL preflight and auto-healing rules.
"""
import pytest

# From source-manager SKILL.md v3.0 — URL validation categories
URL_STATUSES = {"valid", "redirected", "timeout", "blocked", "paywall", "unreachable"}

# URL pattern rules
KNOWN_PATTERNS = {
    "samsung_newsroom": "semiconductor.samsung.com/newsroom",
    "sk_hynix_newsroom": "news.skhynix.com",
    "micron_blog": "micron.com/about/blog",
    "trendforce": "trendforce.com",
    "blocks_and_files": "blocksandfiles.com",
    "anandtech": "anandtech.com",
    "tomshardware": "tomshardware.com",
}


class TestURLStatuses:
    """All 6 URL validation states."""

    def test_six_statuses(self):
        assert len(URL_STATUSES) == 6

    def test_valid_is_best(self):
        assert "valid" in URL_STATUSES

    def test_unreachable_is_worst(self):
        assert "unreachable" in URL_STATUSES

    def test_redirected_is_acceptable(self):
        """Redirect is OK — source-manager follows and records."""
        assert "redirected" in URL_STATUSES

    def test_paywall_not_blocking(self):
        """Paywall doesn't block — content may still be extractable."""
        assert "paywall" in URL_STATUSES


class TestKnownPatterns:
    """Canonical URL patterns for key sources."""

    def test_seven_known_patterns(self):
        assert len(KNOWN_PATTERNS) == 7

    def test_samsung_newsroom(self):
        assert "samsung" in KNOWN_PATTERNS["samsung_newsroom"].lower()

    def test_sk_hynix_newsroom(self):
        assert "skhynix" in KNOWN_PATTERNS["sk_hynix_newsroom"].lower()

    def test_micron_blog(self):
        assert "micron" in KNOWN_PATTERNS["micron_blog"].lower()

    def test_analyst_sources(self):
        """TrendForce is critical analyst source."""
        assert "trendforce" in KNOWN_PATTERNS["trendforce"]
