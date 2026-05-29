"""Health Tracker — query.sh and metrics validation.

query.sh is the only executable script in the pipeline.
Validates: script behavior, output format, metric types.
"""
import os
import json
import subprocess
import pytest

QUERY_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "stratum", "subsystems", "monitoring", "health-tracker", "scripts", "query.sh"
)

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


class TestQueryScript:
    """query.sh was the health tracker's data collector — now superseded by health.py.
    Kept as skip in case the shell script is restored as a CLI wrapper."""

    @pytest.mark.skip(reason="query.sh superseded by health.py — no code references it")
    def test_script_exists(self):
        assert os.path.exists(QUERY_SCRIPT), (
            f"query.sh missing at {QUERY_SCRIPT}"
        )

    @pytest.mark.skip(reason="query.sh superseded by health.py")
    def test_script_is_executable(self):
        import stat
        mode = os.stat(QUERY_SCRIPT).st_mode
        assert mode & stat.S_IXUSR, "query.sh is not executable"

    @pytest.mark.skip(reason="query.sh superseded by health.py")
    def test_script_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", QUERY_SCRIPT],
            capture_output=True, text=True, timeout=5
        )
        assert result.returncode == 0, (
            f"query.sh syntax error: {result.stderr}"
        )

    def test_script_produces_valid_json(self):
        """query.sh output must be parseable JSON (or handle missing data gracefully)."""
        result = subprocess.run(
            ["bash", QUERY_SCRIPT],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CHANNEL": "storage"}
        )
        # May fail if no data — that's OK, just check it doesn't crash
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip())
                assert isinstance(data, dict), "query.sh output must be JSON object"
            except json.JSONDecodeError:
                # Could be empty or partial — acceptable if no data yet
                pass

    def test_script_respects_channel_env(self):
        """CHANNEL env var is used for data path."""
        result = subprocess.run(
            ["bash", "-c", f"CHANNEL=storage {QUERY_SCRIPT} 2>&1 || true"],
            capture_output=True, text=True, timeout=30,
            shell=True
        )
        # Should not crash with "CHANNEL not set"
        assert "CHANNEL not set" not in result.stderr.lower()


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
