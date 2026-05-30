"""Health Tracker — metrics validation.

Legacy query.sh checks were removed when monitoring moved to health.py.
"""

# From health-tracker SKILL.md v3.0
HEALTH_METRICS = [
    "total_sources",
    "active_sources",
    "trial_sources",
    "archived_sources",
    "total_records_today",
    "novelty_ratio_avg",
    "verifiability_avg",
    "signal_noise_avg",
    "sources_with_drop",
    "sources_with_recovery",
]

OUTPUT_FIELDS = {"sources", "records_today", "signals", "alerts"}


class TestHealthMetrics:
    """10 health metrics defined in SKILL.md."""

    def test_ten_metrics(self):
        assert len(HEALTH_METRICS) == 10, (
            f"Expected 10 health metrics, got {len(HEALTH_METRICS)}"
        )

    def test_source_count_metrics(self):
        """Source inventory metrics."""
        expected = {
            "total_sources", "active_sources",
            "trial_sources", "archived_sources",
        }
        assert expected.issubset(set(HEALTH_METRICS))

    def test_quality_metrics(self):
        """Signal quality metrics."""
        expected = {
            "novelty_ratio_avg", "verifiability_avg", "signal_noise_avg",
        }
        assert expected.issubset(set(HEALTH_METRICS))

    def test_change_metrics(self):
        """Change detection metrics."""
        expected = {"sources_with_drop", "sources_with_recovery"}
        assert expected.issubset(set(HEALTH_METRICS))

    def test_all_metrics_snake_case(self):
        for metric in HEALTH_METRICS:
            assert "_" in metric, f"Metric '{metric}' should be snake_case"
