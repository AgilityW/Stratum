"""Tests for monitoring subsystem — health tracker."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest
import json
import os
import tempfile
from pathlib import Path

from health import (
    write_daily_record, load_daily_records, rebuild_stats,
    get_dry_sources, get_top_contributors, ensure_channel_dir,
)
from coverage import detect_gaps, generate_followup_queries, run_coverage_check


class TestHealthTracker:
    def test_write_and_load(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "reuters.com", hits=3, selected=2)
        write_daily_record(str(tmp_path), "2026-05-28", "bloomberg.com", hits=0, selected=0)

        records = load_daily_records(str(tmp_path))
        assert len(records) == 2
        assert records[0]["source"] == "reuters.com"
        assert records[0]["hits"] == 3

    def test_rebuild_stats(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-27", "reuters.com", hits=2, selected=1)
        write_daily_record(str(tmp_path), "2026-05-28", "reuters.com", hits=3, selected=2)
        write_daily_record(str(tmp_path), "2026-05-28", "bloomberg.com", hits=0, selected=0)

        stats = rebuild_stats(str(tmp_path))
        assert stats["total_sources"] == 2
        reuters = stats["sources"]["reuters.com"]
        assert reuters["total_scans"] == 2
        assert reuters["total_hits"] == 5
        assert reuters["hit_rate"] == 2.5  # 5 hits / 2 scans
        assert reuters["dry_streak"] == 0

        bloomberg = stats["sources"]["bloomberg.com"]
        assert bloomberg["total_hits"] == 0
        assert bloomberg["dry_streak"] == 1

    def test_dry_sources(self, tmp_path):
        for day in ["2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28"]:
            write_daily_record(str(tmp_path), day, "dry.com", hits=0, selected=0)
            write_daily_record(str(tmp_path), day, "active.com", hits=5, selected=3)

        dry = get_dry_sources(str(tmp_path), min_dry_days=3)
        assert len(dry) == 1
        assert dry[0]["source"] == "dry.com"

    def test_top_contributors(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "a.com", hits=10, selected=8)
        write_daily_record(str(tmp_path), "2026-05-28", "b.com", hits=3, selected=1)
        write_daily_record(str(tmp_path), "2026-05-28", "c.com", hits=7, selected=5)

        top = get_top_contributors(str(tmp_path), limit=2)
        assert len(top) == 2
        assert top[0]["source"] == "a.com"
        assert top[0]["hits"] == 10

    def test_http_errors_tracked(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "broken.com", hits=0, http_code=404)
        write_daily_record(str(tmp_path), "2026-05-28", "ok.com", hits=5, http_code=200)

        stats = rebuild_stats(str(tmp_path))
        assert stats["sources"]["broken.com"]["http_errors"] == 1
        assert stats["sources"]["ok.com"]["http_errors"] == 0


class TestCoverageMonitor:
    def test_detect_gaps_missing_types(self):
        clusters = [
            {"id": "sc-1", "canonical_title": "HBM4 Launch", "confidence": "C"},
        ]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "reuters.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert len(gaps) == 1
        assert "missing_types" in gaps[0]
        assert "analyst" in gaps[0]["missing_types"] or "official" in gaps[0]["missing_types"]

    def test_no_gaps_when_complete(self):
        clusters = [{"id": "sc-1", "canonical_title": "Complete Story", "confidence": "A"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "official", "source_locale": "en", "source": "samsung.com"},
            {"cluster_id": "sc-1", "source_type": "analyst", "source_locale": "zh-CN", "source": "trendforce.com"},
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "reuters.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert len(gaps) == 0

    def test_missing_locale_flagged(self):
        clusters = [{"id": "sc-1", "canonical_title": "CN-only Story", "confidence": "B"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "reuters.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert len(gaps) == 1
        assert "missing_locales" in gaps[0]
        assert "zh-CN" in gaps[0]["missing_locales"]

    def test_high_severity_for_low_confidence(self):
        clusters = [{"id": "sc-1", "canonical_title": "Rumor", "confidence": "D"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "blog.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert gaps[0]["severity"] == "high"

    def test_generate_followup_queries(self):
        gaps = [{
            "cluster_id": "sc-1", "title": "HBM4 Supply Chain Shift",
            "confidence": "D", "severity": "high",
            "missing_types": ["analyst"],
            "missing_locales": ["zh-CN"], "entities": ["Samsung"],
        }]
        queries = generate_followup_queries(gaps)
        assert len(queries) > 0
        assert any("analysis" in q["query"].lower() for q in queries)

    def test_run_coverage_check_writes_files(self, tmp_path):
        clusters = [{"id": "sc-1", "canonical_title": "Test", "confidence": "C"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "test.com"},
        ]
        result = run_coverage_check(clusters, records, "2026-05-28", str(tmp_path))
        assert result["total_clusters"] == 1
        assert result["gaps_found"] >= 0
        assert os.path.exists(os.path.join(str(tmp_path), "gap-alerts.json"))
