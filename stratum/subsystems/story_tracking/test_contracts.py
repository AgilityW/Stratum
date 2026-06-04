"""Tests for story-tracking contracts."""
import json
import pytest

from stratum.subsystems.story_tracking import (
    EventRecord, CausalEdge, Judgment,
    TimelineEntry, ScaleRef,
    Verdict, Scale, UpdateType, Prominence,
    to_jsonl_line, from_jsonl_line,
)


class TestEnums:
    def test_verdict_values(self):
        assert Verdict.PENDING.value == "pending"
        assert Verdict.CORRECT.value == "correct"
        assert Verdict.PARTIAL.value == "partial"
        assert Verdict.DEFERRED.value == "deferred"
        assert Verdict.UNVERIFIABLE.value == "unverifiable"

    def test_scale_order(self):
        assert Scale.order("daily") == 0
        assert Scale.order("yearly") == 4
        assert Scale.order("bogus") == -1


class TestEventRecord:
    def test_minimal_creation(self):
        er = EventRecord(
            id="event-storage-0001",
            title="Samsung ships HBM4",
            canonical_question="When does Samsung start HBM4 mass production?",
            created="2026-05-28",
            last_updated="2026-05-28",
        )
        assert er.topic_tags == []
        assert er.entity_tags == []
        assert er.status == "emerging"

    def test_with_tags(self):
        er = EventRecord(
            id="event-storage-0001",
            title="Samsung ships HBM4",
            canonical_question="Samsung HBM4 production status?",
            created="2026-05-28",
            last_updated="2026-05-28",
            topic_tags=["HBM", "memory interface"],
            entity_tags=["Samsung", "NVIDIA"],
        )
        assert "HBM" in er.topic_tags
        assert "Samsung" in er.entity_tags

    def test_with_scale_refs(self):
        ref = ScaleRef(
            scale="daily",
            briefing_id="daily-2026-05-28",
            date="2026-05-28",
            prominence=Prominence.LEAD,
            synthesis="Samsung begins HBM4 shipments to NVIDIA",
        )
        er = EventRecord(
            id="event-storage-0001",
            title="Samsung ships HBM4",
            canonical_question="Samsung HBM4 production status?",
            created="2026-05-28",
            last_updated="2026-05-28",
            scale_refs=[ref],
        )
        assert len(er.scale_refs) == 1
        assert er.scale_refs[0].prominence == "lead"

    def test_identity_fields(self):
        er = EventRecord(
            id="event-storage-0002",
            title="Samsung HBM4 mass production (English source)",
            canonical_question="Samsung HBM4?",
            created="2026-05-29",
            last_updated="2026-05-29",
            canonical_id="event-storage-0001",
            parent_event=None,
            child_events=[],
            source_ids=["src-en-001"],
        )
        assert er.canonical_id == "event-storage-0001"

    def test_date_facets(self):
        er = EventRecord(
            id="event-storage-0003",
            title="NAND spot price increase",
            canonical_question="NAND pricing trend?",
            created="2026-05-30",
            last_updated="2026-05-30",
            occurred_at="2026-05-27",
            first_reported_at="2026-05-29",
        )
        assert er.occurred_at == "2026-05-27"
        assert er.first_reported_at == "2026-05-29"


class TestCausalEdge:
    def test_creation(self):
        ce = CausalEdge(
            id="causal-storage-0001",
            cause_id="event-storage-0001",
            effect_id="event-storage-0003",
            mechanism="Samsung Pyeongtaek fab allocates floorspace to HBM lines, "
                      "reducing NAND-capable capacity → NAND spot prices rise",
            confidence="B",
            created="2026-05-30",
        )
        assert ce.cause_id == "event-storage-0001"
        assert ce.effect_id == "event-storage-0003"
        assert ce.verified is False

    def test_verified(self):
        ce = CausalEdge(
            id="causal-storage-0001",
            cause_id="event-storage-0001",
            effect_id="event-storage-0003",
            mechanism="Capacity shift",
            confidence="B",
            created="2026-05-30",
            verified=True,
            verified_at="2026-06-15",
            judgment_id="judgment-storage-0001",
        )
        assert ce.verified is True


class TestJudgment:
    def test_entity_judgment(self):
        j = Judgment(
            id="judgment-storage-0001",
            target_type="entity",
            target_ids=["Samsung"],
            hypothesis="Samsung will ship HBM4 to NVIDIA by Q3 2026",
            confidence="B",
            made_at="2026-05-28",
            expected_verification="2026-09-30",
        )
        assert j.target_type == "entity"
        assert j.verdict == "pending"
        assert j.verified_at is None

    def test_causal_judgment(self):
        j = Judgment(
            id="judgment-storage-0002",
            target_type="event_pair",
            target_ids=["event-0001", "event-0003"],
            hypothesis="HBM demand surge caused NAND spot price increase",
            confidence="C",
            made_at="2026-05-30",
            expected_verification="2026-07-01",
        )
        assert j.target_type == "event_pair"
        assert len(j.target_ids) == 2

    def test_verdict_update(self):
        j = Judgment(
            id="judgment-storage-0001",
            target_type="entity",
            target_ids=["Samsung"],
            hypothesis="Test",
            confidence="B",
            made_at="2026-05-28",
            expected_verification="2026-06-15",
        )
        j.verdict = "correct"
        j.verified_at = "2026-06-10"
        j.evidence = "Samsung press release confirms HBM4 shipment"
        assert j.verdict == "correct"


class TestSerialization:
    def test_event_record_roundtrip(self):
        er = EventRecord(
            id="event-storage-0001",
            title="Samsung ships HBM4",
            canonical_question="Samsung HBM4 production?",
            created="2026-05-28",
            last_updated="2026-05-28",
            topic_tags=["HBM"],
            entity_tags=["Samsung"],
            timeline=[TimelineEntry(
                date="2026-05-28",
                update_type=UpdateType.FIRST_DISCLOSURE,
                summary="First report of HBM4 shipping",
                confidence="B",
            )],
            scale_refs=[ScaleRef(
                scale="daily", briefing_id="daily-2026-05-28",
                date="2026-05-28", prominence=Prominence.LEAD,
                synthesis="Samsung ships HBM4")],
        )
        line = to_jsonl_line(er)
        data = json.loads(line)
        assert data["id"] == "event-storage-0001"
        assert data["topic_tags"] == ["HBM"]
        assert data["scale_refs"][0]["prominence"] == "lead"

        restored = from_jsonl_line(line, EventRecord)
        assert isinstance(restored, EventRecord)
        assert isinstance(restored.scale_refs[0], ScaleRef)
        assert restored.scale_refs[0].prominence == Prominence.LEAD
        assert isinstance(restored.timeline[0], TimelineEntry)
        assert restored.timeline[0].update_type == UpdateType.FIRST_DISCLOSURE

    def test_causal_edge_roundtrip(self):
        ce = CausalEdge(
            id="causal-storage-0001",
            cause_id="event-0001",
            effect_id="event-0003",
            mechanism="Capacity shift",
            confidence="B",
            created="2026-05-30",
        )
        line = to_jsonl_line(ce)
        data = json.loads(line)
        assert data["cause_id"] == "event-0001"
        assert data["verified"] is False

    def test_judgment_enum_serialization(self):
        j = Judgment(
            id="judgment-storage-0001",
            target_type="entity",
            target_ids=["Samsung"],
            hypothesis="Test",
            confidence="B",
            made_at="2026-05-28",
            expected_verification="2026-06-15",
        )
        line = to_jsonl_line(j)
        data = json.loads(line)
        assert data["verdict"] == "pending"
        assert data["target_type"] == "entity"

    def test_timeline_entry_serialization(self):
        te = TimelineEntry(
            date="2026-05-28",
            update_type=UpdateType.FIRST_DISCLOSURE,
            summary="First report of HBM4 shipping",
            confidence="B",
        )
        line = to_jsonl_line(te)
        data = json.loads(line)
        assert data["update_type"] == "first_disclosure"
