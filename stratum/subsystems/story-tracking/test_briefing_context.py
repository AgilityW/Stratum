"""Tests for story-tracking briefing context generator."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest

from story_contracts import EventRecord, CausalEdge, Judgment, ScaleRef, Prominence
from briefing_context import (
    generate_context, format_context_for_prompt,
    _carried_forward, _due_judgments, _coverage_gaps, _active_chains, _unassigned,
)


# ── Helpers ──

def make_event(seq: int, **overrides) -> EventRecord:
    defaults = dict(
        id=f"event-storage-{seq:04d}",
        title=f"Event {seq}",
        canonical_question=f"Q{seq}?",
        created="2026-05-28",
        last_updated="2026-05-28",
        topic_tags=["HBM"],
        entity_tags=["Samsung"],
        status="active",
        priority=3,
    )
    defaults.update(overrides)
    return EventRecord(**defaults)


def make_judgment(seq: int, **overrides) -> Judgment:
    defaults = dict(
        id=f"judgment-storage-{seq:04d}",
        target_type="entity",
        target_ids=["Samsung"],
        hypothesis=f"Hypothesis #{seq}: Samsung will do something in the market",
        confidence="B",
        made_at="2026-05-28",
        expected_verification="2026-06-15",
    )
    defaults.update(overrides)
    return Judgment(**defaults)


def make_edge(seq: int, cause="A", effect="B") -> CausalEdge:
    return CausalEdge(
        id=f"causal-storage-{seq:04d}",
        cause_id=cause,
        effect_id=effect,
        mechanism=f"Mechanism {seq}: {cause} → {effect} explained in detail",
        confidence="B",
        created="2026-05-30",
    )


# ── Carried Forward ──

class TestCarriedForward:
    def test_finds_recent_event(self):
        events = [
            make_event(1, last_updated="2026-06-01", scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert len(result) == 1

    def test_excludes_resolved(self):
        events = [
            make_event(1, status="resolved", scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert len(result) == 0

    def test_includes_cooling_events(self):
        events = [
            make_event(1, status="cooling", scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert len(result) == 1
        assert result[0]["current_status"] == "cooling"

    def test_excludes_outside_window(self):
        events = [
            make_event(1, last_updated="2026-01-01", scale_refs=[
                ScaleRef("daily", "d-001", "2026-01-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert len(result) == 0

    def test_excludes_future_refs_for_backfills(self):
        events = [
            make_event(1, scale_refs=[
                ScaleRef("daily", "d-future", "2026-06-03", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert result == []

    def test_sorted_by_priority(self):
        events = [
            make_event(1, priority=5, scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
            make_event(2, priority=1, scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert result[0]["priority"] == 1

    def test_same_priority_sorted_by_recent_ref(self):
        events = [
            make_event(1, priority=2, scale_refs=[
                ScaleRef("daily", "d-old", "2026-05-29", Prominence.LEAD, "test")]),
            make_event(2, priority=2, scale_refs=[
                ScaleRef("daily", "d-new", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _carried_forward(events, "daily", "2026-06-02", 7)
        assert [item["event_id"] for item in result] == [
            "event-storage-0002",
            "event-storage-0001",
        ]


# ── Due Judgments ──

class TestDueJudgments:
    def test_due_within_window(self):
        judgments = [
            make_judgment(1, expected_verification="2026-06-10"),
        ]
        result = _due_judgments(judgments, "2026-06-05", within_days=7)
        assert len(result) == 1
        assert result[0]["days_remaining"] == 5

    def test_past_due(self):
        judgments = [
            make_judgment(1, expected_verification="2026-05-01"),
        ]
        result = _due_judgments(judgments, "2026-06-05", within_days=30)
        assert len(result) == 1
        assert result[0]["days_remaining"] < 0

    def test_excludes_verified(self):
        judgments = [
            make_judgment(1, verdict="correct", verified_at="2026-05-30"),
        ]
        result = _due_judgments(judgments, "2026-06-05", within_days=30)
        assert len(result) == 0

    def test_excludes_future_made_judgments_for_backfills(self):
        judgments = [
            make_judgment(
                1,
                made_at="2026-06-20",
                expected_verification="2026-06-22",
            ),
            make_judgment(
                2,
                made_at="2026-06-01",
                expected_verification="2026-06-07",
            ),
        ]

        result = _due_judgments(judgments, "2026-06-05", within_days=30)

        assert [item["judgment_id"] for item in result] == ["judgment-storage-0002"]

    def test_sorted_by_days_remaining(self):
        judgments = [
            make_judgment(1, id="j-001", expected_verification="2026-06-10"),
            make_judgment(2, id="j-002", expected_verification="2026-06-05"),
        ]
        result = _due_judgments(judgments, "2026-06-01", within_days=30)
        assert result[0]["judgment_id"] == "j-002"  # sooner first


# ── Coverage Gaps ──

class TestCoverageGaps:
    def test_gap_detected(self):
        events = [
            make_event(1, entity_tags=["Samsung"], last_updated="2026-01-01"),
        ]
        result = _coverage_gaps(events, "2026-06-05", gap_days=14)
        assert len(result) == 1
        assert result[0]["entity"] == "Samsung"

    def test_no_gap_when_recent(self):
        events = [
            make_event(1, entity_tags=["Samsung"], last_updated="2026-06-04"),
        ]
        result = _coverage_gaps(events, "2026-06-05", gap_days=14)
        assert len(result) == 0

    def test_multiple_entities(self):
        events = [
            make_event(1, entity_tags=["Samsung"], last_updated="2026-01-01"),
            make_event(2, entity_tags=["Micron"], last_updated="2026-02-01"),
            make_event(3, entity_tags=["Samsung", "NVIDIA"], last_updated="2026-06-01"),
        ]
        result = _coverage_gaps(events, "2026-06-05", gap_days=14)
        # Samsung's latest is 2026-06-01 (recent), Micron is 2026-02-01 (old)
        assert len(result) == 1
        assert result[0]["entity"] == "Micron"

    def test_excludes_future_events_for_backfill_gap_detection(self):
        events = [
            make_event(1, entity_tags=["Micron"], last_updated="2026-01-01"),
            make_event(2, entity_tags=["Micron"], last_updated="2026-06-20"),
        ]
        result = _coverage_gaps(events, "2026-06-05", gap_days=14)
        assert len(result) == 1
        assert result[0]["entity"] == "Micron"
        assert result[0]["last_mentioned"] == "2026-01-01"

    def test_includes_never_seen_configured_entities(self):
        events = [
            make_event(1, entity_tags=["Samsung"], last_updated="2026-06-04"),
        ]

        result = _coverage_gaps(
            events,
            "2026-06-05",
            gap_days=14,
            coverage_entities=["Samsung", "Micron", "Kioxia", "Micron"],
        )

        assert {gap["entity"] for gap in result} == {"Micron", "Kioxia"}
        assert all(gap["last_mentioned"] is None for gap in result)
        assert all(gap["status"] == "never_seen" for gap in result)


# ── Active Chains ──

class TestActiveChains:
    def test_unverified_edges(self):
        edges = [
            make_edge(1, cause="A", effect="B"),
            make_edge(2, cause="B", effect="C"),
        ]
        events = [
            make_event(1, id="A", status="active"),
            make_event(2, id="B", status="emerging"),
            make_event(3, id="C", status="active"),
        ]
        result = _active_chains(edges, events)
        assert len(result) == 2

    def test_excludes_future_edges_for_backfill_context(self):
        edges = [
            make_edge(1, cause="A", effect="B"),
        ]
        edges[0].created = "2026-06-20"
        events = [
            make_event(1, id="A", status="active"),
            make_event(2, id="B", status="active"),
        ]

        result = _active_chains(edges, events, as_of="2026-06-05")

        assert result == []

    def test_excludes_verified(self):
        edges = [
            make_edge(1, cause="A", effect="B"),
        ]
        edges[0].verified = True
        result = _active_chains(edges, [])
        assert len(result) == 0

    def test_excludes_fully_resolved_chain(self):
        edges = [
            make_edge(1, cause="A", effect="B"),
        ]
        events = [
            make_event(1, id="A", status="resolved"),
            make_event(2, id="B", status="archived"),
        ]
        result = _active_chains(edges, events)
        assert result == []


# ── Unassigned ──

class TestUnassigned:
    def test_unassigned(self):
        events = [
            make_event(1, scale_refs=[]),
            make_event(2, scale_refs=[ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
            make_event(3, status="resolved", scale_refs=[]),
        ]
        result = _unassigned(events)
        assert result == ["event-storage-0001"]

    def test_excludes_future_unassigned_events_for_backfill_context(self):
        events = [
            make_event(1, scale_refs=[], last_updated="2026-06-01"),
            make_event(2, scale_refs=[], last_updated="2026-06-20"),
        ]

        result = _unassigned(events, as_of="2026-06-05")

        assert result == ["event-storage-0001"]

    def test_empty(self):
        events = [
            make_event(1, scale_refs=[ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")]),
        ]
        result = _unassigned(events)
        assert result == []


# ── Full Context ──

class TestGenerateContext:
    def test_generates_for_daily(self):
        events = [
            make_event(1, scale_refs=[ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")],
                      entity_tags=["Samsung"], priority=2),
        ]
        edges = [make_edge(1)]
        judgments = [make_judgment(1, expected_verification="2026-06-10")]

        ctx = generate_context("storage", "daily", "2026-06-02", events, edges, judgments, due_within_days=14)
        assert ctx.scale == "daily"
        assert ctx.domain_id == "storage"
        assert len(ctx.carried_forward) == 1
        assert len(ctx.due_judgments) == 1
        assert len(ctx.active_causal_chains) == 1

    def test_generates_coverage_gaps_from_configured_entity_universe(self):
        ctx = generate_context(
            "storage",
            "daily",
            "2026-06-02",
            [],
            [],
            [],
            coverage_entities=["Samsung", "Micron"],
        )

        assert [gap["entity"] for gap in ctx.coverage_gaps] == ["Samsung", "Micron"]
        assert all(gap["status"] == "never_seen" for gap in ctx.coverage_gaps)

    def test_generates_context_without_future_unassigned_or_edges(self):
        events = [
            make_event(1, id="A", scale_refs=[], last_updated="2026-06-01"),
            make_event(2, id="B", scale_refs=[], last_updated="2026-06-20"),
        ]
        edges = [make_edge(1, cause="A", effect="B")]
        edges[0].created = "2026-06-20"

        ctx = generate_context("storage", "daily", "2026-06-05", events, edges, [])

        assert ctx.unassigned_events == ["A"]
        assert ctx.active_causal_chains == []

    def test_format_context(self):
        events = [
            make_event(1, title="HBM4 Race", scale_refs=[
                ScaleRef("daily", "d-001", "2026-06-01", Prominence.LEAD, "test")],
                      open_questions=["Will SK Hynix follow?"], priority=1),
        ]
        ctx = generate_context("storage", "daily", "2026-06-02", events, [], [])
        text = format_context_for_prompt(ctx)
        assert "HBM4 Race" in text
        assert "Briefing Context" in text
        assert "Carried Forward" in text

    def test_format_context_lists_unassigned_event_ids(self):
        events = [
            make_event(1, scale_refs=[]),
        ]
        ctx = generate_context("storage", "daily", "2026-06-02", events, [], [])
        text = format_context_for_prompt(ctx)
        assert "Unassigned Events: 1" in text
        assert "event-storage-0001" in text

    def test_format_context_describes_never_seen_coverage_gap(self):
        ctx = generate_context(
            "storage",
            "daily",
            "2026-06-02",
            [],
            [],
            [],
            coverage_entities=["Micron"],
        )
        text = format_context_for_prompt(ctx)
        assert "Micron" in text
        assert "no prior coverage found" in text
