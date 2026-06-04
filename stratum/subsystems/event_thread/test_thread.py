"""Tests for event-thread subsystem."""
import pytest
from datetime import date

from stratum.subsystems.event_thread import (
    EventThread, TimelineEntry, compute_thread_status, should_archive,
    jaccard_similarity, match_cluster_to_thread, create_thread, add_update,
    generate_watch_queries, archive_resolved, evolve_threads,
    evaluate_thread_lifecycle, lifecycle_diagnostics,
)
from stratum.subsystems.event_thread import ThreadLifecycleScorer


class TestLifecycle:
    def test_lifecycle_scorer_marks_escalating_active_thread(self):
        scorer = ThreadLifecycleScorer()

        decision = scorer.evaluate(
            current_status="active",
            run_date="2026-05-28",
            observed_dates=[
                date.fromisoformat("2026-05-24"),
                date.fromisoformat("2026-05-26"),
                date.fromisoformat("2026-05-28"),
            ],
            last_updated="2026-05-28",
        )

        assert decision.status == "active"
        assert decision.momentum == "escalating"
        assert decision.lifecycle_score > 0.9
        assert decision.should_archive is False
        assert "3 visible updates" in decision.reason

    def test_lifecycle_scorer_marks_cooling_thread(self):
        scorer = ThreadLifecycleScorer()

        decision = scorer.evaluate(
            current_status="active",
            run_date="2026-05-28",
            observed_dates=[date.fromisoformat("2026-05-20")],
            last_updated="2026-05-20",
        )

        assert decision.status == "cooling"
        assert decision.momentum == "cooling"
        assert decision.days_since_last == 8
        assert decision.lifecycle_score < 0.5

    def test_lifecycle_scorer_keeps_archive_decision_separate_from_status(self):
        scorer = ThreadLifecycleScorer()

        decision = scorer.evaluate(
            current_status="resolved",
            run_date="2026-05-28",
            observed_dates=[date.fromisoformat("2026-04-20")],
            last_updated="2026-05-20",
        )

        assert decision.status == "resolved"
        assert decision.should_archive is True

    def test_lifecycle_scorer_keeps_dormant_threads_low_momentum_without_observations(self):
        scorer = ThreadLifecycleScorer()

        decision = scorer.evaluate(
            current_status="dormant",
            run_date="2026-05-28",
            observed_dates=[],
            last_updated="2026-05-20",
        )

        assert decision.status == "dormant"
        assert decision.momentum == "dormant"
        assert decision.lifecycle_score < 0.1

    def test_event_thread_exposes_structured_lifecycle_diagnostics(self):
        t = EventThread(
            id="et-storage-0001",
            title="HBM",
            canonical_question="?",
            status="active",
            priority="high",
            created="2026-05-20",
            last_updated="2026-05-20",
            timeline=[TimelineEntry(date="2026-05-20", cluster_id="sc-1",
                       update_type="first_disclosure", summary="old", confidence_after="B")],
        )

        diagnostic = evaluate_thread_lifecycle(t, "2026-05-28")

        assert diagnostic["thread_id"] == "et-storage-0001"
        assert diagnostic["status"] == "cooling"
        assert diagnostic["previous_status"] == "active"
        assert diagnostic["momentum"] == "cooling"
        assert diagnostic["days_since_last"] == 8
        assert "visible updates" in diagnostic["reason"]

    def test_lifecycle_diagnostics_are_returned_from_evolve_threads(self):
        threads = {
            "et-storage-0001": EventThread(
                id="et-storage-0001",
                title="HBM",
                canonical_question="?",
                status="active",
                priority="high",
                created="2026-05-20",
                last_updated="2026-05-20",
                timeline=[TimelineEntry(date="2026-05-20", cluster_id="sc-1",
                           update_type="first_disclosure", summary="old", confidence_after="B")],
            )
        }

        result = evolve_threads(threads, "storage", "2026-05-28", [])

        assert result["lifecycle_diagnostics"][0]["thread_id"] == "et-storage-0001"
        assert result["lifecycle_diagnostics"][0]["status"] == "cooling"

    def test_emerging_stays_emerging_same_day(self):
        t = EventThread(id="et-1", title="Test", canonical_question="?", status="emerging",
                        priority="high", created="2026-05-28", last_updated="2026-05-28",
                        timeline=[TimelineEntry(date="2026-05-28", cluster_id="sc-1",
                                   update_type="first_disclosure", summary="test", confidence_after="B")])
        assert compute_thread_status(t, "2026-05-28") == "emerging"

    def test_cools_after_7_days(self):
        t = EventThread(id="et-1", title="Test", canonical_question="?", status="active",
                        priority="high", created="2026-05-20", last_updated="2026-05-20",
                        timeline=[TimelineEntry(date="2026-05-20", cluster_id="sc-1",
                                   update_type="first_disclosure", summary="test", confidence_after="B")])
        assert compute_thread_status(t, "2026-05-28") == "cooling"

    def test_resolved_after_30_days(self):
        t = EventThread(id="et-1", title="Test", canonical_question="?", status="cooling",
                        priority="medium", created="2026-04-01", last_updated="2026-04-01",
                        timeline=[TimelineEntry(date="2026-04-01", cluster_id="sc-1",
                                   update_type="first_disclosure", summary="test", confidence_after="C")])
        assert compute_thread_status(t, "2026-05-28") == "resolved"

    def test_status_ignores_future_timeline_entries_for_backfills(self):
        t = EventThread(
            id="et-1",
            title="Backfill",
            canonical_question="?",
            status="active",
            priority="medium",
            created="2026-04-01",
            last_updated="2026-06-20",
            timeline=[
                TimelineEntry(date="2026-04-01", cluster_id="sc-1",
                              update_type="first_disclosure", summary="old", confidence_after="C"),
                TimelineEntry(date="2026-06-20", cluster_id="sc-2",
                              update_type="confirmation", summary="future", confidence_after="B"),
            ],
        )
        assert compute_thread_status(t, "2026-05-15") == "resolved"

    def test_status_uses_latest_timeline_date_even_when_entries_are_unsorted(self):
        t = EventThread(
            id="et-1",
            title="Unsorted",
            canonical_question="?",
            status="active",
            priority="medium",
            created="2026-05-01",
            last_updated="2026-05-20",
            timeline=[
                TimelineEntry(date="2026-05-20", cluster_id="sc-2",
                              update_type="confirmation", summary="new", confidence_after="B"),
                TimelineEntry(date="2026-05-01", cluster_id="sc-1",
                              update_type="first_disclosure", summary="old", confidence_after="C"),
            ],
        )
        assert compute_thread_status(t, "2026-05-28") == "cooling"

    def test_should_archive_resolved_old(self):
        t = EventThread(id="et-1", title="Test", canonical_question="?", status="resolved",
                        priority="low", created="2026-01-01", last_updated="2026-01-01",
                        timeline=[TimelineEntry(date="2026-01-01", cluster_id="sc-1",
                                   update_type="first_disclosure", summary="test", confidence_after="C")])
        assert should_archive(t, "2026-05-28") is True

    def test_should_not_archive_active(self):
        t = EventThread(id="et-1", title="Test", canonical_question="?", status="active",
                        priority="high", created="2026-05-20", last_updated="2026-05-27")
        assert should_archive(t, "2026-05-28") is False


class TestJaccard:
    def test_identical(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial(self):
        assert jaccard_similarity({"a", "b"}, {"b", "c"}) == 1/3

    def test_empty(self):
        assert jaccard_similarity(set(), {"a"}) == 0.0


class TestMatchCluster:
    def test_no_match_empty_threads(self):
        assert match_cluster_to_thread({"samsung", "hbm4"}, {"ddr5"}, {}) is None

    def test_match_by_watch_signals(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM Race", canonical_question="who leads HBM?",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4", "Samsung", "memory bandwidth", "NVIDIA"])
        }
        result = match_cluster_to_thread({"samsung", "hbm4", "nvidia"}, {"memory", "ddr5"}, threads)
        assert result == "et-1"

    def test_no_match_below_threshold(self):
        threads = {
            "et-1": EventThread(id="et-1", title="NAND Prices", canonical_question="nand price trend?",
                                status="active", priority="medium", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["NAND", "price", "QLC"])
        }
        result = match_cluster_to_thread({"samsung", "hbm4"}, {"ddr5"}, threads)
        assert result is None

    def test_does_not_match_resolved_threads(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM Race", canonical_question="who leads HBM?",
                                status="resolved", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4", "Samsung", "NVIDIA"])
        }
        result = match_cluster_to_thread({"samsung", "hbm4", "nvidia"}, {"memory"}, threads)
        assert result is None

    def test_tokenizes_watch_signal_phrases(self):
        threads = {
            "et-1": EventThread(id="et-1", title="Bandwidth", canonical_question="memory bandwidth roadmap",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["memory bandwidth"])
        }
        result = match_cluster_to_thread({"bandwidth"}, {"memory"}, threads)
        assert result == "et-1"

    def test_matches_by_title_when_watch_signals_missing(self):
        threads = {
            "et-1": EventThread(id="et-1", title="Samsung HBM4 qualification", canonical_question="",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=[])
        }
        result = match_cluster_to_thread({"Samsung"}, {"HBM4"}, threads)
        assert result == "et-1"

    def test_matches_by_timeline_summary_when_watch_signals_missing(self):
        threads = {
            "et-1": EventThread(id="et-1", title="Qualification", canonical_question="",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                timeline=[TimelineEntry(date="2026-05-20", cluster_id="sc-1",
                                           update_type="first_disclosure",
                                           summary="Micron enterprise SSD controller ramp",
                                           confidence_after="B")],
                                watch_signals=[])
        }
        result = match_cluster_to_thread({"Micron"}, {"enterprise", "SSD"}, threads)
        assert result == "et-1"


class TestCreateAndUpdate:
    def test_create_thread(self):
        t = create_thread("storage", 1, "Test Story", "what happened?", "high",
                         "2026-05-28", "sc-1", "summary text", "B",
                         ["signal1"], ["condition1"])
        assert t.id == "et-storage-0001"
        assert t.status == "emerging"
        assert len(t.timeline) == 1
        assert t.timeline[0].update_type == "first_disclosure"

    def test_add_update(self):
        t = create_thread("storage", 1, "Test", "?", "medium",
                         "2026-05-20", "sc-1", "first report", "B", [], [])
        add_update(t, "2026-05-25", "sc-2", "confirmation", "confirmed by second source", "A")
        assert len(t.timeline) == 2
        assert t.last_updated == "2026-05-25"
        assert t.confidence == "A"
        assert t.confidence_history[-1]["confidence"] == "A"

    def test_update_changes_status(self):
        t = create_thread("storage", 1, "Test", "?", "medium",
                         "2026-05-13", "sc-1", "first report", "B", [], [])
        add_update(t, "2026-05-28", "sc-2", "confirmation", "update", "A")
        # A second update means the thread has moved beyond first disclosure.
        assert t.status == "active"


class TestWatchQueries:
    def test_generates_for_active_threads(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM", canonical_question="?",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4 supply", "Samsung HBM"]),
            "et-2": EventThread(id="et-2", title="Old Story", canonical_question="?",
                                status="resolved", priority="low", created="2026-01-01", last_updated="2026-01-01",
                                watch_signals=["old signal"]),
        }
        queries = generate_watch_queries(threads)
        assert len(queries) == 2
        assert queries[0]["source"] == "thread:et-1"

    def test_generates_for_cooling_threads(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM", canonical_question="?",
                                status="cooling", priority="medium", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4 follow-up"]),
        }
        queries = generate_watch_queries(threads)
        assert len(queries) == 1
        assert queries[0]["query"] == "HBM4 follow-up"

    def test_prioritizes_high_priority_threads(self):
        threads = {
            "et-low": EventThread(id="et-low", title="Low", canonical_question="?",
                                  status="active", priority="low", created="2026-05-01", last_updated="2026-05-20",
                                  watch_signals=["low signal"]),
            "et-high": EventThread(id="et-high", title="High", canonical_question="?",
                                   status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                   watch_signals=["high signal"]),
        }
        queries = generate_watch_queries(threads, max_queries=1)
        assert queries[0]["source"] == "thread:et-high"

    def test_prioritizes_recent_threads_within_same_priority(self):
        threads = {
            "et-old": EventThread(id="et-old", title="Old", canonical_question="?",
                                  status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                  watch_signals=["old signal"]),
            "et-new": EventThread(id="et-new", title="New", canonical_question="?",
                                  status="active", priority="high", created="2026-05-01", last_updated="2026-05-30",
                                  watch_signals=["new signal"]),
        }
        queries = generate_watch_queries(threads, max_queries=1)
        assert queries[0]["source"] == "thread:et-new"
        assert queries[0]["query"] == "new signal"

    def test_prioritizes_active_threads_over_cooling_threads_with_same_priority(self):
        threads = {
            "et-cooling": EventThread(id="et-cooling", title="Cooling", canonical_question="?",
                                      status="cooling", priority="medium", created="2026-05-01", last_updated="2026-05-30",
                                      watch_signals=["cooling signal"],
                                      timeline=[TimelineEntry(date="2026-05-10", cluster_id="sc-1",
                                                 update_type="first_disclosure", summary="old", confidence_after="C")]),
            "et-active": EventThread(id="et-active", title="Active", canonical_question="?",
                                     status="active", priority="medium", created="2026-05-01", last_updated="2026-05-20",
                                     watch_signals=["active signal"],
                                     timeline=[
                                         TimelineEntry(date="2026-05-10", cluster_id="sc-1",
                                                       update_type="first_disclosure", summary="first", confidence_after="C"),
                                         TimelineEntry(date="2026-05-20", cluster_id="sc-2",
                                                       update_type="confirmation", summary="second", confidence_after="B"),
                                     ]),
        }

        queries = generate_watch_queries(threads, max_queries=1)

        assert queries[0]["source"] == "thread:et-active"
        assert queries[0]["query"] == "active signal"

    def test_respects_max_queries(self):
        threads = {}
        for i in range(5):
            threads[f"et-{i}"] = EventThread(
                id=f"et-{i}", title=f"Story {i}", canonical_question="?",
                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                watch_signals=[f"signal-{i}-a", f"signal-{i}-b", f"signal-{i}-c"],
            )
        queries = generate_watch_queries(threads, max_queries=5)
        assert len(queries) == 5

    def test_generates_watch_queries_for_configured_locales(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM", canonical_question="?",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4 supply"]),
        }
        queries = generate_watch_queries(threads, locales=["en", "zh-CN"])
        assert [(q["query"], q["locale"]) for q in queries] == [
            ("HBM4 supply", "en"),
            ("HBM4 supply", "zh-CN"),
        ]

    def test_watch_queries_dedupe_same_signal_and_locale(self):
        threads = {
            "et-high": EventThread(id="et-high", title="High", canonical_question="?",
                                   status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                   watch_signals=["HBM4 supply"]),
            "et-low": EventThread(id="et-low", title="Low", canonical_question="?",
                                  status="active", priority="low", created="2026-05-01", last_updated="2026-05-20",
                                  watch_signals=["hbm4 supply"]),
        }
        queries = generate_watch_queries(threads)
        assert len(queries) == 1
        assert queries[0]["source"] == "thread:et-high"

    def test_watch_queries_fall_back_to_thread_title(self):
        threads = {
            "et-1": EventThread(id="et-1", title="Samsung HBM4 qualification", canonical_question="",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=[]),
        }
        queries = generate_watch_queries(threads)
        assert queries == [{
            "query": "Samsung HBM4 qualification",
            "locale": "en",
            "source": "thread:et-1",
            "reason": "watch signal from Samsung HBM4 qualification",
        }]


class TestEvolve:
    def test_empty_clusters_no_change(self):
        threads = {}
        result = evolve_threads(threads, "storage", "2026-05-28", [])
        assert result["stats"]["created"] == 0
        assert result["stats"]["matched"] == 0

    def test_evolve_threads_passes_watch_locales(self):
        threads = {
            "et-1": EventThread(id="et-1", title="HBM", canonical_question="?",
                                status="active", priority="high", created="2026-05-01", last_updated="2026-05-20",
                                watch_signals=["HBM4 supply"]),
        }
        result = evolve_threads(threads, "storage", "2026-05-28", [], watch_locales=["en", "ja"])
        assert [q["locale"] for q in result["watch_queries"]] == ["en", "ja"]

    def test_new_cluster_creates_thread(self):
        threads = {}
        clusters = [{
            "id": "sc-1", "canonical_title": "New HBM4 Story",
            "canonical_summary": "Samsung ships HBM4", "canonical_question": "HBM4 market?",
            "confidence": "B", "entities": ["Samsung", "NVIDIA"],
            "terms": ["HBM4", "memory"], "watch_signals": ["HBM4"], "close_conditions": [],
        }]
        result = evolve_threads(threads, "storage", "2026-05-28", clusters)
        assert result["stats"]["created"] == 1
        assert len(result["threads"]) == 1

    def test_archive_resolved(self):
        threads = {
            "et-old": EventThread(id="et-old", title="Old", canonical_question="?",
                                  status="resolved", priority="low",
                                  created="2026-01-01", last_updated="2026-01-01",
                                  timeline=[TimelineEntry(date="2026-01-01", cluster_id="sc-x",
                                             update_type="first_disclosure", summary="old", confidence_after="C")]),
        }
        result = evolve_threads(threads, "storage", "2026-05-28", [])
        assert threads["et-old"].status == "archived"
        assert result["stats"]["archived"] == 1

    def test_does_not_overcount_preexisting_archived_threads(self):
        threads = {
            "et-archived": EventThread(id="et-archived", title="Archived", canonical_question="?",
                                       status="archived", priority="low",
                                       created="2026-01-01", last_updated="2026-01-01"),
        }
        result = evolve_threads(threads, "storage", "2026-05-28", [])
        assert result["stats"]["archived"] == 0

    def test_respects_max_thread_limit(self):
        threads = {}
        for i in range(30):
            threads[f"et-storage-{i:04d}"] = EventThread(
                id=f"et-storage-{i:04d}",
                title=f"Thread {i}",
                canonical_question="?",
                status="active",
                priority="medium",
                created="2026-05-01",
                last_updated="2026-05-20",
            )
        clusters = [{
            "id": "sc-new", "canonical_title": "New Story",
            "canonical_summary": "New signal", "entities": ["Samsung"],
            "terms": ["HBM4"],
        }]
        result = evolve_threads(threads, "storage", "2026-05-28", clusters)
        assert result["stats"]["created"] == 0
        assert result["stats"]["skipped"] == 1
        assert len(result["threads"]) == 30

    def test_new_thread_id_does_not_collide_with_sparse_existing_ids(self):
        threads = {
            "et-storage-0001": EventThread(
                id="et-storage-0001",
                title="Old 1",
                canonical_question="?",
                status="active",
                priority="medium",
                created="2026-05-01",
                last_updated="2026-05-20",
            ),
            "et-storage-0003": EventThread(
                id="et-storage-0003",
                title="Old 3",
                canonical_question="?",
                status="active",
                priority="medium",
                created="2026-05-01",
                last_updated="2026-05-20",
            ),
        }
        clusters = [{
            "id": "sc-new",
            "canonical_title": "New sparse-id story",
            "canonical_summary": "New signal",
            "entities": ["Samsung"],
            "terms": ["HBM4"],
        }]

        result = evolve_threads(threads, "storage", "2026-05-28", clusters)

        assert result["stats"]["created"] == 1
        assert "et-storage-0004" in result["threads"]
        assert result["threads"]["et-storage-0003"].title == "Old 3"
