"""Tests for monitoring subsystem — health tracker."""
import pytest
import json
import os
import tempfile
from pathlib import Path

from stratum.subsystems.monitoring import (
    EngineHealthScorer,
    detect_gaps,
    ensure_channel_dir,
    generate_followup_queries,
    get_dry_sources,
    get_non_contributing_sources,
    get_source_alerts,
    get_top_contributors,
    load_daily_records,
    rebuild_stats,
    run_coverage_check,
    score_search_engine_health,
    write_daily_record,
)


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
        assert reuters["selected_rate"] == 1.5
        assert reuters["dry_streak"] == 0
        assert reuters["selected_dry_streak"] == 0

        bloomberg = stats["sources"]["bloomberg.com"]
        assert bloomberg["total_hits"] == 0
        assert bloomberg["dry_streak"] == 1
        assert bloomberg["selected_dry_streak"] == 1

    def test_dry_sources(self, tmp_path):
        for day in ["2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28"]:
            write_daily_record(str(tmp_path), day, "dry.com", hits=0, selected=0)
            write_daily_record(str(tmp_path), day, "active.com", hits=5, selected=3)

        dry = get_dry_sources(str(tmp_path), min_dry_days=3)
        assert len(dry) == 1
        assert dry[0]["source"] == "dry.com"

    def test_dry_streak_uses_chronological_order(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-30", "source.com", hits=0)
        write_daily_record(str(tmp_path), "2026-05-28", "source.com", hits=0)
        write_daily_record(str(tmp_path), "2026-05-29", "source.com", hits=4)

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["source.com"]
        assert source["first_seen"] == "2026-05-28"
        assert source["last_seen"] == "2026-05-30"
        assert source["dry_streak"] == 1

    def test_rebuild_stats_uses_latest_same_day_record(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "source.com", hits=0, selected=0)
        write_daily_record(str(tmp_path), "2026-05-28", "source.com", hits=5, selected=3)
        write_daily_record(str(tmp_path), "2026-05-29", "source.com", hits=0, selected=0)

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["source.com"]
        assert source["total_scans"] == 2
        assert source["total_hits"] == 5
        assert source["total_selected"] == 3
        assert source["dry_streak"] == 1
        assert source["selected_dry_streak"] == 1

    def test_selected_dry_streak_tracks_sources_that_do_not_survive_merge(self, tmp_path):
        for day in ["2026-05-28", "2026-05-29", "2026-05-30"]:
            write_daily_record(str(tmp_path), day, "duplicate-source", hits=5, selected=0)
            write_daily_record(str(tmp_path), day, "useful-source", hits=5, selected=2)

        stats = rebuild_stats(str(tmp_path))
        duplicate = stats["sources"]["duplicate-source"]
        assert duplicate["dry_streak"] == 0
        assert duplicate["selected_dry_streak"] == 3

        stale = get_non_contributing_sources(str(tmp_path), min_days=3)
        assert [s["source"] for s in stale] == ["duplicate-source"]

    def test_unscanned_records_do_not_create_dry_streaks(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "paused-source", scanned=False)
        write_daily_record(str(tmp_path), "2026-05-29", "paused-source", scanned=False)
        write_daily_record(str(tmp_path), "2026-05-30", "paused-source", scanned=True, hits=0, selected=0)

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["paused-source"]

        assert source["total_scans"] == 1
        assert source["dry_streak"] == 1
        assert source["selected_dry_streak"] == 1
        assert source["first_seen"] == "2026-05-28"
        assert source["last_seen"] == "2026-05-30"

        dry = get_dry_sources(str(tmp_path), min_dry_days=3)
        assert dry == []

    def test_unsupported_records_do_not_create_source_quality_streaks(self, tmp_path):
        write_daily_record(
            str(tmp_path),
            "2026-05-28",
            "browser-source",
            hits=0,
            selected=0,
            http_code=500,
            tags=["watchlist", "browser", "unsupported"],
        )
        write_daily_record(
            str(tmp_path),
            "2026-05-29",
            "browser-source",
            hits=0,
            selected=0,
            http_code=500,
            metadata={"status": "unsupported"},
        )
        write_daily_record(
            str(tmp_path),
            "2026-05-30",
            "browser-source",
            hits=2,
            selected=1,
            metadata={"status": "ok"},
        )

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["browser-source"]

        assert source["total_scans"] == 1
        assert source["total_hits"] == 2
        assert source["total_selected"] == 1
        assert source["dry_streak"] == 0
        assert source["selected_dry_streak"] == 0
        assert source["http_errors"] == 0
        assert source["first_seen"] == "2026-05-28"
        assert source["last_seen"] == "2026-05-30"

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
        assert stats["sources"]["broken.com"]["http_error_streak"] == 1
        assert stats["sources"]["ok.com"]["http_errors"] == 0
        assert stats["sources"]["ok.com"]["http_error_streak"] == 0

    def test_http_error_streak_resets_after_success(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-27", "recovered.com", hits=0, http_code=500)
        write_daily_record(str(tmp_path), "2026-05-28", "recovered.com", hits=0, http_code=502)
        write_daily_record(str(tmp_path), "2026-05-29", "recovered.com", hits=2, selected=1, http_code=200)

        stats = rebuild_stats(str(tmp_path))
        recovered = stats["sources"]["recovered.com"]

        assert recovered["http_errors"] == 2
        assert recovered["http_error_streak"] == 0
        assert get_source_alerts(str(tmp_path), http_error_days=2) == []

    def test_status_error_counts_as_http_error(self, tmp_path):
        write_daily_record(
            str(tmp_path),
            "2026-05-28",
            "watchlist-error.com",
            hits=0,
            metadata={"status": "error"},
        )

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["watchlist-error.com"]

        assert source["http_errors"] == 1
        assert source["http_error_streak"] == 1

    def test_dated_rate_uses_watchlist_metadata(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-28", "source.com", hits=4, selected=3, metadata={"dated": 2})
        write_daily_record(str(tmp_path), "2026-05-29", "source.com", hits=2, selected=2, metadata={"dated": 1})

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["source.com"]

        assert source["total_hits"] == 6
        assert source["total_dated"] == 3
        assert source["dated_hits_observed"] == 6
        assert source["dated_rate"] == 0.5

    def test_dated_rate_ignores_hits_without_dated_observations(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-27", "source.com", hits=10, selected=8)
        write_daily_record(str(tmp_path), "2026-05-28", "source.com", hits=4, selected=4, metadata={"dated": 4})

        stats = rebuild_stats(str(tmp_path))
        source = stats["sources"]["source.com"]

        assert source["total_hits"] == 14
        assert source["dated_hits_observed"] == 4
        assert source["total_dated"] == 4
        assert source["dated_rate"] == 1.0

    def test_source_alerts_report_threshold_breaches(self, tmp_path):
        for day in ["2026-05-27", "2026-05-28", "2026-05-29"]:
            write_daily_record(str(tmp_path), day, "dry.com", hits=0, selected=0)
            write_daily_record(str(tmp_path), day, "duplicate.com", hits=4, selected=0, metadata={"dated": 4})
            write_daily_record(str(tmp_path), day, "undated.com", hits=4, selected=4, metadata={"dated": 1})
        write_daily_record(str(tmp_path), "2026-05-28", "broken.com", hits=0, selected=0, http_code=500)
        write_daily_record(str(tmp_path), "2026-05-29", "broken.com", hits=0, selected=0, http_code=502)

        alerts = get_source_alerts(
            str(tmp_path),
            dry_streak_days=3,
            selected_dry_streak_days=3,
            http_error_days=2,
            min_dated_rate=0.5,
            min_scans_for_quality=3,
        )
        by_type = {(alert["source"], alert["type"]): alert for alert in alerts}

        assert ("dry.com", "dry_streak") in by_type
        assert ("duplicate.com", "selected_dry_streak") in by_type
        assert by_type[("broken.com", "http_errors")]["value"] == 2
        assert by_type[("undated.com", "low_dated_rate")]["value"] == 0.25

    def test_source_alerts_ignore_unscanned_and_missing_dated_metadata(self, tmp_path):
        write_daily_record(str(tmp_path), "2026-05-27", "paused.com", scanned=False)
        write_daily_record(str(tmp_path), "2026-05-28", "paused.com", scanned=False, http_code=500)
        write_daily_record(str(tmp_path), "2026-05-29", "legacy.com", hits=4, selected=4)
        write_daily_record(str(tmp_path), "2026-05-30", "legacy.com", hits=4, selected=4)
        write_daily_record(str(tmp_path), "2026-05-31", "legacy.com", hits=4, selected=4)

        alerts = get_source_alerts(str(tmp_path), min_scans_for_quality=3)

        assert alerts == []


class TestSearchEngineHealth:
    def test_search_engine_health_uses_attempt_chains(self):
        stats = [
            {
                "query_id": "q1",
                "engine_used": "tavily",
                "status": "fallback",
                "engine_attempts": [
                    {
                        "engine": "bocha",
                        "status": "failed",
                        "error": "bocha: RuntimeError: down",
                    },
                    {
                        "engine": "tavily",
                        "status": "success",
                        "results_count": 2,
                    },
                ],
            },
            {
                "query_id": "q2",
                "engine_used": "tavily",
                "status": "failed",
                "engine_attempts": [
                    {
                        "engine": "bocha",
                        "status": "rate_limited",
                        "error": "bocha: rate limited",
                    },
                    {
                        "engine": "tavily",
                        "status": "failed",
                        "error": "tavily: quota",
                    },
                ],
            },
        ]

        health = score_search_engine_health(stats)

        assert health["bocha"]["attempts"] == 2
        assert health["bocha"]["failure_rate"] == 1.0
        assert health["bocha"]["recommendation"] == "avoid"
        assert health["tavily"]["successes"] == 1
        assert health["tavily"]["recommendation"] == "deprioritize"

    def test_search_engine_health_supports_legacy_query_stats(self):
        health = score_search_engine_health([
            {"engine_used": "tavily", "status": "success", "results_count": 3}
        ])

        assert health["tavily"]["health_score"] == 1.0
        assert health["tavily"]["recommendation"] == "healthy"

    def test_engine_health_scorer_owns_recommendation_policy(self):
        scorer = EngineHealthScorer()

        health = scorer.score([
            {
                "engine_attempts": [
                    {"engine": "bocha", "status": "no_results", "results_count": 0},
                    {"engine": "bocha", "status": "success", "results_count": 1},
                ]
            }
        ])

        assert health["bocha"]["health_score"] == 0.75
        assert health["bocha"]["recommendation"] == "healthy"


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

    def test_cluster_summary_coverage_used_without_source_records(self):
        clusters = [{
            "id": "sc-1",
            "canonical_title": "Complete Story",
            "confidence": "A",
            "source_types": ["official", "analyst", "media"],
            "locales": ["en", "zh-CN"],
        }]
        gaps = detect_gaps(clusters, [])
        assert gaps == []

    def test_cluster_source_domains_used_for_severity(self):
        clusters = [{
            "id": "sc-1",
            "canonical_title": "Sparse Story",
            "confidence": "low",
            "source_types": ["media"],
            "locales": ["en"],
            "source_domains": ["reuters.com", "bloomberg.com", "extra.com"],
        }]
        gaps = detect_gaps(clusters, [])
        assert gaps[0]["severity"] == "medium"
        assert gaps[0]["current_sources"] == ["reuters.com", "bloomberg.com", "extra.com"]

    def test_missing_locale_flagged(self):
        clusters = [{"id": "sc-1", "canonical_title": "CN-only Story", "confidence": "B"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "reuters.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert len(gaps) == 1
        assert "missing_locales" in gaps[0]
        assert "zh-CN" in gaps[0]["missing_locales"]

    def test_missing_source_locale_does_not_default_to_english_coverage(self):
        clusters = [{"id": "sc-1", "canonical_title": "Unlabelled Locale", "confidence": "B"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source": "example.com"},
        ]

        gaps = detect_gaps(clusters, records)

        assert gaps[0]["current_locales"] == []
        assert gaps[0]["missing_locales"] == ["en", "zh-CN"]

    def test_coverage_normalizes_source_type_and_locale_labels(self):
        clusters = [{
            "id": "sc-1",
            "canonical_title": "Case Normalized Story",
            "confidence": "high",
            "source_types": ["Official", "Analyst"],
            "locales": ["zh-cn"],
        }]
        records = [
            {"cluster_id": "sc-1", "source_type": "MEDIA", "source_locale": "EN", "source": "reuters.com"},
        ]

        gaps = detect_gaps(clusters, records)

        assert gaps == []

    def test_detect_gaps_preserves_entities_for_followup(self):
        clusters = [{
            "id": "sc-1",
            "canonical_title": "HBM4 Qualification",
            "confidence": "D",
            "source_types": ["media"],
            "locales": ["en"],
            "entities": ["Samsung"],
            "terms": ["HBM4"],
        }]
        gaps = detect_gaps(clusters, [])

        assert gaps[0]["entities"] == ["Samsung"]
        queries = generate_followup_queries(gaps)
        assert any("Samsung" in q["query"] and "official" in q["query"] for q in queries)

    def test_high_severity_for_low_confidence(self):
        clusters = [{"id": "sc-1", "canonical_title": "Rumor", "confidence": "low"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "blog.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert gaps[0]["severity"] == "high"
        assert gaps[0]["confidence_rank"] == "low"

    def test_legacy_confidence_labels_still_supported(self):
        clusters = [{"id": "sc-1", "canonical_title": "Rumor", "confidence": "D"}]
        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "blog.com"},
        ]
        gaps = detect_gaps(clusters, records)
        assert gaps[0]["severity"] == "high"
        assert gaps[0]["confidence_rank"] == "low"

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
