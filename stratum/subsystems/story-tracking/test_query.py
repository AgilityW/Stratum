"""Tests for story-tracking query engine."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest

from story_contracts import EventRecord, ScaleRef, Prominence
from query import (
    query_events, recent_events, events_by_topic, events_by_entity,
    active_events, events_needing_attention,
    events_by_scale, unassigned_events, events_missing_scale,
    query_stats,
)


# ── Helpers ──

def make_event(
    seq: int,
    created: str = "2026-05-28",
    topics: list = None,
    entities: list = None,
    scale_refs: list = None,
    status: str = "active",
    priority: int = 3,
) -> EventRecord:
    return EventRecord(
        id=f"event-storage-{seq:04d}",
        title=f"Event {seq}",
        canonical_question=f"What is event {seq}?",
        created=created,
        last_updated=created,
        topic_tags=topics or [],
        entity_tags=entities or [],
        scale_refs=scale_refs or [],
        status=status,
        priority=priority,
    )


def daily_ref(date: str) -> ScaleRef:
    return ScaleRef(scale="daily", briefing_id=f"daily-{date}",
                    date=date, prominence=Prominence.LEAD, synthesis="test")


def weekly_ref(date: str) -> ScaleRef:
    return ScaleRef(scale="weekly", briefing_id=f"weekly-{date}",
                    date=date, prominence=Prominence.SUPPORTING, synthesis="test")


# ── Fixtures ──

@pytest.fixture
def sample_events():
    return [
        make_event(1, "2026-05-25", topics=["HBM"], entities=["Samsung"],
                   scale_refs=[daily_ref("2026-05-25")]),
        make_event(2, "2026-05-26", topics=["HBM", "memory"], entities=["NVIDIA"],
                   scale_refs=[daily_ref("2026-05-26")]),
        make_event(3, "2026-05-27", topics=["NAND"], entities=["Micron"],
                   scale_refs=[]),
        make_event(4, "2026-05-28", topics=["HBM", "advanced packaging"],
                   entities=["Samsung", "NVIDIA"],
                   scale_refs=[daily_ref("2026-05-28"), weekly_ref("2026-W22")]),
        make_event(5, "2026-05-29", topics=["DDR5"], entities=["Samsung"],
                   status="resolved", scale_refs=[daily_ref("2026-05-29")]),
    ]


# ── Topic/Entity Filtering ──

class TestTagFiltering:
    def test_single_topic(self, sample_events):
        result = query_events(sample_events, topics=["HBM"])
        assert len(result) == 3  # events 1, 2, 4

    def test_multiple_topics_and(self, sample_events):
        result = query_events(sample_events, topics=["HBM", "advanced packaging"])
        assert len(result) == 1  # event 4
        assert result[0].id == "event-storage-0004"

    def test_single_entity(self, sample_events):
        result = query_events(sample_events, entities=["Samsung"])
        assert len(result) == 3  # events 1, 4, 5

    def test_topic_and_entity(self, sample_events):
        result = query_events(sample_events, topics=["HBM"], entities=["NVIDIA"])
        assert len(result) == 2  # events 2, 4

    def test_no_match(self, sample_events):
        result = query_events(sample_events, topics=["CXL"])
        assert len(result) == 0

    def test_case_insensitive(self, sample_events):
        result = query_events(sample_events, topics=["hbm"], entities=["samsung"])
        assert len(result) == 2  # events 1, 4


# ── Date Filtering ──

class TestDateFiltering:
    def test_date_from(self, sample_events):
        result = query_events(sample_events, date_from="2026-05-28")
        assert len(result) == 2  # events 4, 5

    def test_date_to(self, sample_events):
        result = query_events(sample_events, date_to="2026-05-26")
        assert len(result) == 2  # events 1, 2

    def test_date_range(self, sample_events):
        result = query_events(sample_events, date_from="2026-05-26", date_to="2026-05-28")
        assert len(result) == 3  # events 2, 3, 4

    def test_recent_events(self, sample_events):
        # sample_events are all in 2026-05, so recent(7) from today won't match
        result = recent_events(sample_events, days=365*10)  # 10 years catches them all
        assert len(result) == 5


# ── Scale Filtering ──

class TestScaleFiltering:
    def test_daily_scale(self, sample_events):
        result = query_events(sample_events, scale="daily")
        assert len(result) == 4  # events 1, 2, 4, 5

    def test_weekly_scale(self, sample_events):
        result = query_events(sample_events, scale="weekly")
        assert len(result) == 1  # event 4

    def test_no_scale_match(self, sample_events):
        result = query_events(sample_events, scale="yearly")
        assert len(result) == 0


# ── Status Filtering ──

class TestStatusFiltering:
    def test_active_only(self, sample_events):
        result = query_events(sample_events, status="active")
        assert len(result) == 4  # events 1, 2, 3, 4

    def test_resolved_only(self, sample_events):
        result = query_events(sample_events, status="resolved")
        assert len(result) == 1  # event 5


# ── Combined Queries ──

class TestCombinedQueries:
    def test_topic_date_scale(self, sample_events):
        """HBM + after May 27 + appeared in daily = Samsung/NVIDIA HBM on the 28th"""
        result = query_events(
            sample_events,
            topics=["HBM"],
            date_from="2026-05-28",
            scale="daily",
        )
        assert len(result) == 1
        assert result[0].id == "event-storage-0004"

    def test_entity_status(self, sample_events):
        """Samsung + active events"""
        result = query_events(sample_events, entities=["Samsung"], status="active")
        assert len(result) == 2  # events 1, 4


# ── Convenience Functions ──

class TestConvenience:
    def test_events_by_topic(self, sample_events):
        result = events_by_topic(sample_events, "NAND")
        assert len(result) == 1

    def test_events_by_entity(self, sample_events):
        result = events_by_entity(sample_events, "Micron")
        assert len(result) == 1

    def test_active_events(self, sample_events):
        result = active_events(sample_events)
        assert len(result) == 4

    def test_events_needing_attention(self, sample_events):
        result = events_needing_attention(sample_events)
        # event 3: NAND/Micron, active, no scale_refs, priority 3
        assert len(result) == 1
        assert result[0].id == "event-storage-0003"

    def test_unassigned_events(self, sample_events):
        result = unassigned_events(sample_events)
        assert len(result) == 1
        assert result[0].id == "event-storage-0003"

    def test_events_missing_scale(self, sample_events):
        result = events_missing_scale(sample_events, "weekly")
        # Events 1,2,3,5 don't have weekly
        assert len(result) == 4

    def test_events_by_scale(self, sample_events):
        assert len(events_by_scale(sample_events, "daily")) == 4
        assert len(events_by_scale(sample_events, "weekly")) == 1


# ── Sorting ──

class TestSorting:
    def test_date_desc_default(self, sample_events):
        result = query_events(sample_events)
        assert result[0].created == "2026-05-29"

    def test_date_asc(self, sample_events):
        result = query_events(sample_events, sort_by="date_asc")
        assert result[0].created == "2026-05-25"


# ── Stats ──

class TestStats:
    def test_query_stats(self, sample_events):
        stats = query_stats(sample_events)
        assert stats["total"] == 5
        assert stats["by_status"]["active"] == 4
        assert stats["by_status"]["resolved"] == 1
        assert stats["unique_topics"] == 5  # HBM, memory, NAND, advanced packaging, DDR5
        assert stats["unique_entities"] == 3  # Samsung, NVIDIA, Micron
