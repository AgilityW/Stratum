"""Coverage Monitor — gap detection logic.

Validates:
- IDEAL_TYPES completeness
- LOCALE_PRIORITY ordering
- Gap detection algorithm structure
"""
import pytest

# From coverage-monitor SKILL.md Step 2
IDEAL_TYPES = {"official", "analyst", "media"}
LOCALE_PRIORITY = ["zh-CN", "en"]  # ordered: first = highest priority
BONUS_LOCALES = {"ja", "ko"}

# Output gap structure
GAP_FIELDS = {"cluster_id", "cluster_title", "confidence", "gaps"}


class TestIdealTypes:
    """IDEAL_TYPES must cover high-signal source types."""

    def test_three_ideal_types(self):
        assert len(IDEAL_TYPES) == 3

    def test_official_is_highest_signal(self):
        """official source_type has highest signal weight."""
        assert "official" in IDEAL_TYPES

    def test_analyst_included(self):
        """analyst reports are essential for industry coverage."""
        assert "analyst" in IDEAL_TYPES

    def test_media_included(self):
        """media provides real-time coverage."""
        assert "media" in IDEAL_TYPES

    def test_blog_not_ideal(self):
        """Blogs are low signal — not in IDEAL_TYPES."""
        assert "blog" not in IDEAL_TYPES

    def test_social_not_ideal(self):
        """Social is low signal — not in IDEAL_TYPES."""
        assert "social" not in IDEAL_TYPES


class TestLocalePriority:
    """LOCALE_PRIORITY defines the core coverage locales."""

    def test_two_core_locales(self):
        assert len(LOCALE_PRIORITY) == 2

    def test_zh_cn_first(self):
        """Chinese sources are highest priority for storage industry."""
        assert LOCALE_PRIORITY[0] == "zh-CN"

    def test_en_second(self):
        assert LOCALE_PRIORITY[1] == "en"

    def test_ja_ko_are_bonus(self):
        """Japanese and Korean are bonus, not core."""
        assert "ja" in BONUS_LOCALES
        assert "ko" in BONUS_LOCALES
        assert "ja" not in LOCALE_PRIORITY
        assert "ko" not in LOCALE_PRIORITY


class TestGapStructure:
    """Gap alert output structure."""

    def test_gap_has_required_fields(self):
        assert len(GAP_FIELDS) == 4

    def test_gaps_is_array(self):
        """The 'gaps' field is an array of gap descriptions."""
        assert "gaps" in GAP_FIELDS


class TestGapDetectionLogic:
    """Coverage gap detection is source-type + locale based."""

    def test_missing_official_is_gap(self):
        """A cluster without official source coverage has a gap."""
        covered_types = {"media", "analyst"}
        missing = IDEAL_TYPES - covered_types
        assert "official" in missing

    def test_missing_analyst_is_gap(self):
        covered_types = {"official", "media"}
        missing = IDEAL_TYPES - covered_types
        assert "analyst" in missing

    def test_missing_media_is_gap(self):
        covered_types = {"official"}
        missing = IDEAL_TYPES - covered_types
        assert "media" in missing

    def test_all_three_covered_no_gap(self):
        """All three ideal types covered → no gap."""
        covered_types = {"official", "analyst", "media"}
        missing = IDEAL_TYPES - covered_types
        assert len(missing) == 0

    def test_missing_core_locale_is_gap(self):
        """Missing zh-CN or en coverage is a gap."""
        covered_locales = {"ja", "ko"}
        missing = set(LOCALE_PRIORITY) - covered_locales
        assert len(missing) == 2  # both zh-CN and en missing
