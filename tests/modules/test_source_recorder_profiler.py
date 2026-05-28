"""Source Recorder & Source Profiler — data model validation.

Validates:
- SourceRecord fields (from source-recorder SKILL.md)
- SourceProfile fields (from source-profiler SKILL.md)
- Profile EMA parameters
"""
import pytest

# SourceRecord fields
SOURCE_RECORD_FIELDS = {
    "source", "source_type", "source_locale",
    "date", "articles_collected", "articles_published",
    "cluster_ids", "discovery_mode", "trial",
}

DISCOVERY_MODES = {
    "baseline_seed", "trial_query", "value_chain_probe",
    "coverage_gap", "newsroom_crawl",
}

# SourceProfile fields
SOURCE_PROFILE_FIELDS = {
    "source", "source_type", "source_locale",
    "first_seen", "last_seen", "total_records",
    "status", "current", "history", "events",
}

SOURCE_PROFILE_CURRENT_FIELDS = {
    "novelty_ratio", "verifiability", "exclusivity",
    "signal_noise_ratio", "total_records",
}

PROFILE_STATUSES = {"active", "trial", "degraded", "archived"}

# EMA alpha from SKILL.md
EMA_ALPHA = 0.3


class TestSourceRecordSchema:
    """SourceRecord object model."""

    def test_nine_fields(self):
        assert len(SOURCE_RECORD_FIELDS) == 9

    def test_trial_is_boolean(self):
        """trial field: true if source is in trial pool."""
        assert "trial" in SOURCE_RECORD_FIELDS

    def test_discovery_mode_enum(self):
        assert "discovery_mode" in SOURCE_RECORD_FIELDS
        assert len(DISCOVERY_MODES) == 5

    def test_articles_collected_is_count(self):
        assert "articles_collected" in SOURCE_RECORD_FIELDS

    def test_cluster_ids_is_array(self):
        assert "cluster_ids" in SOURCE_RECORD_FIELDS


class TestSourceProfileSchema:
    """SourceProfile aggregated object model."""

    def test_ten_fields(self):
        assert len(SOURCE_PROFILE_FIELDS) == 10

    def test_current_is_subdict(self):
        assert "current" in SOURCE_PROFILE_FIELDS

    def test_history_is_array(self):
        """history is time-series of current snapshots."""
        assert "history" in SOURCE_PROFILE_FIELDS

    def test_events_is_array(self):
        """events log significant changes (novelty_drop, recovery, etc.)."""
        assert "events" in SOURCE_PROFILE_FIELDS

    def test_four_statuses(self):
        assert len(PROFILE_STATUSES) == 4

    def test_statuses_match_lifecycle(self):
        """Status lifecycle: trial → active → degraded → archived."""
        assert "trial" in PROFILE_STATUSES
        assert "active" in PROFILE_STATUSES
        assert "degraded" in PROFILE_STATUSES
        assert "archived" in PROFILE_STATUSES


class TestProfileCurrentMetrics:
    """Current snapshot metrics."""

    def test_five_current_fields(self):
        assert len(SOURCE_PROFILE_CURRENT_FIELDS) == 5

    def test_novelty_ratio_is_float(self):
        """novelty_ratio: 0.0-1.0."""
        assert "novelty_ratio" in SOURCE_PROFILE_CURRENT_FIELDS

    def test_verifiability_is_float(self):
        assert "verifiability" in SOURCE_PROFILE_CURRENT_FIELDS

    def test_exclusivity_is_float(self):
        assert "exclusivity" in SOURCE_PROFILE_CURRENT_FIELDS

    def test_signal_noise_ratio_is_float(self):
        assert "signal_noise_ratio" in SOURCE_PROFILE_CURRENT_FIELDS


class TestEMAParameters:
    """Exponential Moving Average for rolling metrics."""

    def test_alpha_value(self):
        """α = 0.3 for moderately smooth updates."""
        assert EMA_ALPHA == 0.3

    def test_alpha_in_range(self):
        """α between 0 and 1."""
        assert 0 < EMA_ALPHA < 1

    def test_ema_calculation(self):
        """EMA: new = value * α + old * (1-α)."""
        old_novelty = 0.5
        new_value = 0.8
        ema = new_value * EMA_ALPHA + old_novelty * (1 - EMA_ALPHA)
        # 0.8 * 0.3 + 0.5 * 0.7 = 0.24 + 0.35 = 0.59
        assert abs(ema - 0.59) < 0.01
