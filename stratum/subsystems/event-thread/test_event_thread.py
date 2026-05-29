"""Tests for event-thread subsystem."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest
from datetime import date

from event_thread import (
    EventThread, TimelineEntry, compute_thread_status, should_archive,
    jaccard_similarity, match_cluster_to_thread, create_thread, add_update,
    generate_watch_queries, archive_resolved, evolve_threads,
)


class TestLifecycle:
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
        assert t.confidence_history[-1]["confidence"] == "A"

    def test_update_changes_status(self):
        t = create_thread("storage", 1, "Test", "?", "medium",
                         "2026-05-13", "sc-1", "first report", "B", [], [])
        add_update(t, "2026-05-28", "sc-2", "confirmation", "update", "A")
        # Last update = today, originally "emerging" → stays emerging
        assert t.status == "emerging"


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


class TestEvolve:
    def test_empty_clusters_no_change(self):
        threads = {}
        result = evolve_threads(threads, "storage", "2026-05-28", [])
        assert result["stats"]["created"] == 0
        assert result["stats"]["matched"] == 0

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
