"""Tests for story-tracking timeline module."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest
import tempfile

from story_contracts import EventRecord, ScaleRef, Prominence
from repository import JsonlEventRepository
from timeline import (
    scale_index, next_scale, prev_scale,
    record_appearance, trace_scales, trace_chain,
    find_rollup_candidates, events_for_scale_briefing,
    scale_summary, timeline_gap_events,
)


# ── Helpers ──

def make_event(seq: int, created: str = "2026-05-28", scale_refs=None, status="active", priority=3) -> EventRecord:
    return EventRecord(
        id=f"event-storage-{seq:04d}",
        title=f"Event {seq}",
        canonical_question=f"Q{seq}?",
        created=created,
        last_updated=created,
        topic_tags=["HBM"],
        entity_tags=["Samsung"],
        scale_refs=scale_refs or [],
        status=status,
        priority=priority,
    )


# ── Scale Utilities ──

class TestScaleUtils:
    def test_scale_index(self):
        assert scale_index("daily") == 0
        assert scale_index("yearly") == 4
        assert scale_index("bogus") == -1

    def test_next_scale(self):
        assert next_scale("daily") == "weekly"
        assert next_scale("weekly") == "monthly"
        assert next_scale("yearly") is None

    def test_prev_scale(self):
        assert prev_scale("weekly") == "daily"
        assert prev_scale("monthly") == "weekly"
        assert prev_scale("daily") is None


# ── Record Appearance ──

class TestRecordAppearance:
    def test_adds_scale_ref(self):
        event = make_event(1)
        record_appearance(event, "daily", "daily-2026-05-28", "2026-05-28",
                         prominence="lead", synthesis="HBM4 ships")
        assert len(event.scale_refs) == 1
        assert event.scale_refs[0].scale == "daily"

    def test_multiple_scales(self):
        event = make_event(1)
        record_appearance(event, "daily", "d-001", "2026-05-28", "lead", "day 1")
        record_appearance(event, "weekly", "w-001", "2026-05-31", "supporting", "week summary")
        assert len(event.scale_refs) == 2
        scales = {r.scale for r in event.scale_refs}
        assert scales == {"daily", "weekly"}

    def test_persists_via_repo(self):
        with tempfile.TemporaryDirectory() as d:
            repo = JsonlEventRepository(d, "storage")
            event = make_event(1)
            repo.add(event)

            record_appearance(event, "daily", "d-001", "2026-05-28",
                            "lead", "test", repo=repo)

            retrieved = repo.get("event-storage-0001")
            assert len(retrieved.scale_refs) == 1


# ── Trace Scales ──

class TestTraceScales:
    def test_single_scale(self):
        event = make_event(1)
        record_appearance(event, "daily", "d-001", "2026-05-28", "lead", "test")
        result = trace_scales(event)
        assert result["chain"] == ["daily"]
        assert result["highest_scale"] == "daily"
        assert "weekly" in result["missing"]

    def test_complete_chain(self):
        event = make_event(1)
        for scale in ["daily", "weekly", "monthly", "quarterly", "yearly"]:
            record_appearance(event, scale, f"{scale}-001", "2026-01-01", "lead", scale)
        result = trace_scales(event)
        assert result["is_complete"] is True
        assert result["missing"] == []

    def test_partial_chain(self):
        event = make_event(1)
        record_appearance(event, "daily", "d-001", "2026-05-28", "lead", "test")
        record_appearance(event, "weekly", "w-001", "2026-05-31", "supporting", "test")
        result = trace_scales(event)
        assert result["chain"] == ["daily", "weekly"]
        assert result["missing"] == ["monthly", "quarterly", "yearly"]

    def test_no_appearances(self):
        event = make_event(1)
        result = trace_scales(event)
        assert result["chain"] == []
        assert result["highest_scale"] is None

    def test_trace_chain_sorted(self):
        event = make_event(1)
        record_appearance(event, "weekly", "w-001", "2026-05-31", "supporting", "week")
        record_appearance(event, "daily", "d-001", "2026-05-28", "lead", "day")
        chain = trace_chain(event)
        assert chain[0]["scale"] == "daily"  # daily before weekly
        assert chain[1]["scale"] == "weekly"


# ── Rollup Discovery ──

class TestRollupDiscovery:
    def test_find_rollup_candidates(self):
        events = [
            make_event(1, scale_refs=[
                ScaleRef("daily", "d-001", "2026-05-28", Prominence.LEAD, "test")]),
            make_event(2, scale_refs=[
                ScaleRef("daily", "d-002", "2026-05-29", Prominence.SUPPORTING, "test"),
                ScaleRef("weekly", "w-001", "2026-05-31", Prominence.SUPPORTING, "test"),
            ]),
            make_event(3, scale_refs=[]),
        ]
        candidates = find_rollup_candidates(events, "daily", "weekly")
        assert len(candidates) == 1
        assert candidates[0].id == "event-storage-0001"

    def test_no_candidates(self):
        events = [make_event(1, scale_refs=[])]
        candidates = find_rollup_candidates(events, "daily", "weekly")
        assert len(candidates) == 0

    def test_monthly_from_weekly(self):
        events = [
            make_event(1, scale_refs=[
                ScaleRef("daily", "d-001", "2026-05-28", Prominence.LEAD, "test"),
                ScaleRef("weekly", "w-001", "2026-05-31", Prominence.LEAD, "test"),
            ]),
        ]
        candidates = find_rollup_candidates(events, "weekly", "monthly")
        assert len(candidates) == 1


# ── Events for Scale Briefing ──

class TestEventsForScaleBriefing:
    def test_daily_gets_active(self):
        events = [
            make_event(1, status="active"),
            make_event(2, status="active"),
            make_event(3, status="resolved"),
            make_event(4, status="archived"),
        ]
        result = events_for_scale_briefing(events, "daily")
        assert len(result) == 2

    def test_weekly_gets_rollup_candidates(self):
        events = [
            make_event(1, scale_refs=[
                ScaleRef("daily", "d-001", "2026-05-28", Prominence.LEAD, "test")]),
            make_event(2, scale_refs=[
                ScaleRef("daily", "d-002", "2026-05-29", Prominence.SUPPORTING, "test"),
                ScaleRef("weekly", "w-001", "2026-05-31", Prominence.SUPPORTING, "test"),
            ]),
        ]
        result = events_for_scale_briefing(events, "weekly")
        assert len(result) == 1

    def test_priority_sorting(self):
        events = [
            make_event(1, priority=5),
            make_event(2, priority=1),
            make_event(3, priority=3),
        ]
        result = events_for_scale_briefing(events, "daily")
        assert result[0].priority == 1  # highest priority first


# ── Scale Summary ──

class TestScaleSummary:
    def test_basic_summary(self):
        events = [
            make_event(1, scale_refs=[
                ScaleRef("daily", "d-001", "2026-05-28", Prominence.LEAD, "test")]),
            make_event(2, scale_refs=[
                ScaleRef("daily", "d-002", "2026-05-29", Prominence.SUPPORTING, "test"),
                ScaleRef("weekly", "w-001", "2026-05-31", Prominence.SUPPORTING, "test"),
            ]),
            make_event(3, scale_refs=[]),
        ]
        summary = scale_summary(events)
        assert summary["total_events"] == 3
        assert summary["unassigned"] == 1
        assert summary["scales"]["daily"]["total"] == 2
        assert summary["scales"]["weekly"]["total"] == 1
        assert summary["scales"]["monthly"]["total"] == 0


# ── Timeline Gaps ──

class TestTimelineGaps:
    def test_stale_events(self):
        events = [
            make_event(1, created="2026-01-01", status="active"),
            make_event(2, created="2026-05-28", status="active"),
        ]
        # Event 1 is very old, should show up as stale
        gaps = timeline_gap_events(events, gap_days=30)
        assert len(gaps) == 1
        assert gaps[0]["event_id"] == "event-storage-0001"

    def test_resolved_not_reported(self):
        events = [
            make_event(1, created="2026-01-01", status="resolved"),
        ]
        gaps = timeline_gap_events(events, gap_days=30)
        assert len(gaps) == 0  # Resolved events are fine to be stale
