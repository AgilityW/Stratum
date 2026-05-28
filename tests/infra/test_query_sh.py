"""Layer 2: Shell script smoke tests — query.sh minimal validation.

Tests query.sh with temporary health-data fixtures. No real data needed.
Catches: syntax errors, missing dependencies, exit codes.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def query_script():
    p = Path(__file__).resolve().parents[2] / "skills" / "health-tracker" / "scripts" / "query.sh"
    if not p.exists():
        pytest.skip("query.sh not found")
    return str(p)


@pytest.fixture
def health_data_dir():
    """Temporary health-data dir with minimal fixture data."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        # Create channel dir
        ch = root / "test-channel"
        ch.mkdir()

        # Write source-daily.ndjson — 2 days, 2 sources
        ndjson = ch / "source-daily.ndjson"
        records = [
            {"date": "2026-05-27", "source": "reuters", "selected": 1, "total": 5},
            {"date": "2026-05-27", "source": "bloomberg", "selected": 0, "total": 3},
            {"date": "2026-05-28", "source": "reuters", "selected": 1, "total": 4},
            {"date": "2026-05-28", "source": "bloomberg", "selected": 1, "total": 2},
        ]
        with open(ndjson, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        # Write source-stats.json
        stats = ch / "source-stats.json"
        stats_data = {
            "sources": {
                "reuters": {
                    "name": "reuters",
                    "freq": 0.75,
                    "dry_streak": 0,
                    "lifetime": {"hit_rate": 0.75, "total_scans": 4},
                },
                "bloomberg": {
                    "name": "bloomberg",
                    "freq": 0.25,
                    "dry_streak": 1,
                    "lifetime": {"hit_rate": 0.25, "total_scans": 4},
                },
                "stale_source": {
                    "name": "stale_source",
                    "freq": 0.0,
                    "dry_streak": 30,
                    "lifetime": {"hit_rate": 0.0, "total_scans": 50},
                },
            },
            "blindspots": {"missing_official": ["skhynix"]},
        }
        with open(stats, "w") as f:
            json.dump(stats_data, f)

        yield str(root)


def _run(query_script, health_data_dir, *args):
    """Run query.sh with HEALTH_DATA_DIR set."""
    env = {**os.environ, "HEALTH_DATA_DIR": health_data_dir}
    result = subprocess.run(
        ["bash", query_script, *args],
        capture_output=True, text=True, env=env, timeout=10
    )
    return result


class TestQueryShSyntax:
    """Basic syntax and structure checks."""

    def test_bash_syntax_valid(self, query_script):
        """bash -n passes — script is syntactically valid."""
        result = subprocess.run(["bash", "-n", query_script], capture_output=True, text=True)
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_shebang_present(self, query_script):
        """Script starts with #!/bin/bash."""
        with open(query_script) as f:
            first_line = f.readline().strip()
        assert first_line == "#!/bin/bash", f"Expected #!/bin/bash, got '{first_line}'"

    def test_no_line_number_prefix(self, query_script):
        """Script is not polluted with `NN|` line number prefixes."""
        with open(query_script) as f:
            for i, line in enumerate(f, 1):
                assert not line.lstrip().startswith(
                    tuple(f"{n}|" for n in range(100))
                ), f"Line {i} has line number prefix: {line[:20].strip()}"


class TestQueryShList:
    """query.sh list — channel enumeration."""

    def test_list_returns_zero(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "test-channel", "list")
        assert result.returncode == 0, f"list failed:\n{result.stderr}"


class TestQueryShRanking:
    """query.sh ranking — source ranking."""

    def test_ranking_returns_zero(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "test-channel", "ranking")
        assert result.returncode == 0, f"ranking failed:\n{result.stderr}"
        assert "reuters" in result.stdout, "ranking output should include 'reuters'"
        assert "bloomberg" in result.stdout, "ranking output should include 'bloomberg'"


class TestQueryShDrought:
    """query.sh drought — dry streak detection."""

    def test_drought_finds_stale(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "test-channel", "drought", "14")
        assert result.returncode == 0
        assert "stale_source" in result.stdout, "drought should find stale_source (dry=30d)"


class TestQueryShBlindspots:
    """query.sh blindspots — coverage gaps."""

    def test_blindspots_returns_zero(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "test-channel", "blindspots")
        assert result.returncode == 0
        assert "skhynix" in result.stdout or "missing_official" in result.stdout


class TestQueryShErrorHandling:
    """query.sh error handling."""

    def test_missing_args_shows_usage(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir)
        assert result.returncode == 1, "missing args should exit 1"
        assert "Usage:" in result.stdout

    def test_bad_channel_exits_1(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "nonexistent", "ranking")
        assert result.returncode == 1, "bad channel should exit 1"
        assert "not found" in result.stdout

    def test_bad_query_shows_error(self, query_script, health_data_dir):
        result = _run(query_script, health_data_dir, "test-channel", "nonexistent_query")
        assert "not recognized" in result.stdout
