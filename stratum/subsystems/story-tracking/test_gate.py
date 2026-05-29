"""Tests for story-tracking validation gates."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest

from story_contracts import EventRecord, CausalEdge, Judgment
from gate import (
    GateResult, ok, fail,
    gate_event, gate_causal_edge, gate_judgment,
    gate_batch, batch_passed,
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
    )
    defaults.update(overrides)
    return EventRecord(**defaults)


def make_edge(seq: int, cause="ev-001", effect="ev-002") -> CausalEdge:
    return CausalEdge(
        id=f"causal-storage-{seq:04d}",
        cause_id=cause,
        effect_id=effect,
        mechanism=f"Mechanism explaining {cause} → {effect} in detail",
        confidence="B",
        created="2026-05-30",
    )


def make_judgment(seq: int, **overrides) -> Judgment:
    defaults = dict(
        id=f"judgment-storage-{seq:04d}",
        target_type="entity",
        target_ids=["Samsung"],
        hypothesis=f"Hypothesis #{seq}: Samsung will do something significant in the market",
        confidence="B",
        made_at="2026-05-28",
        expected_verification="2026-09-30",
    )
    defaults.update(overrides)
    return Judgment(**defaults)


# ── GateResult ──

class TestGateResult:
    def test_ok(self):
        r = ok()
        assert r.passed is True
        assert r.errors == []

    def test_ok_with_warnings(self):
        r = ok(["this is a warning"])
        assert r.passed is True
        assert len(r.warnings) == 1

    def test_fail(self):
        r = fail(["error 1", "error 2"])
        assert r.passed is False
        assert len(r.errors) == 2


# ── Event Gate ──

class TestEventGate:
    def test_valid_event_passes(self):
        event = make_event(1)
        result = gate_event(event, [])
        assert result.passed is True

    def test_missing_title_fails(self):
        event = make_event(1, title="")
        result = gate_event(event, [])
        assert result.passed is False
        assert any("title" in e for e in result.errors)

    def test_bad_id_format_fails(self):
        event = make_event(1, id="bad-id")
        result = gate_event(event, [])
        assert result.passed is False

    def test_bad_priority_fails(self):
        event = make_event(1, priority=99)
        result = gate_event(event, [])
        assert result.passed is False

    def test_bad_status_fails(self):
        event = make_event(1, status="bogus")
        result = gate_event(event, [])
        assert result.passed is False

    def test_empty_tags_warns(self):
        event = make_event(1, topic_tags=[], entity_tags=[])
        result = gate_event(event, [])
        assert result.passed is True
        assert any("topic_tags" in w.lower() for w in result.warnings)
        assert any("entity_tags" in w.lower() for w in result.warnings)

    def test_duplicate_title_warns(self):
        existing = make_event(1, title="Samsung ships HBM4", created="2026-05-28")
        duplicate = make_event(2, id="event-storage-0002", title="Samsung ships HBM4", created="2026-05-28")
        result = gate_event(duplicate, [existing])
        assert result.passed is True
        assert any("duplicate" in w for w in result.warnings)


# ── Causal Edge Gate ──

class TestCausalEdgeGate:
    def test_valid_edge_passes(self):
        edge = make_edge(1)
        result = gate_causal_edge(edge, [], {"ev-001", "ev-002"})
        assert result.passed is True

    def test_self_loop_fails(self):
        edge = make_edge(1, cause="ev-001", effect="ev-001")
        result = gate_causal_edge(edge, [], {"ev-001"})
        assert result.passed is False
        assert any("self-loop" in e.lower() for e in result.errors)

    def test_missing_cause_fails(self):
        edge = make_edge(1, cause="ev-missing")
        result = gate_causal_edge(edge, [], {"ev-002"})
        assert result.passed is False
        assert any("not exist" in e for e in result.errors)

    def test_missing_effect_fails(self):
        edge = make_edge(1, effect="ev-missing")
        result = gate_causal_edge(edge, [], {"ev-001"})
        assert result.passed is False

    def test_short_mechanism_fails(self):
        edge = CausalEdge(
            id="causal-storage-0001", cause_id="ev-001", effect_id="ev-002",
            mechanism="too short", confidence="B", created="2026-05-30",
        )
        result = gate_causal_edge(edge, [], {"ev-001", "ev-002"})
        assert result.passed is False

    def test_duplicate_edge_warns(self):
        existing = make_edge(1, cause="ev-001", effect="ev-002")
        duplicate = make_edge(2, cause="ev-001", effect="ev-002")
        result = gate_causal_edge(duplicate, [existing], {"ev-001", "ev-002"})
        assert result.passed is True
        assert any("duplicate" in w for w in result.warnings)

    def test_transitive_warns(self):
        existing = [
            make_edge(1, cause="A", effect="B"),
            make_edge(2, cause="B", effect="C"),
        ]
        transitive = make_edge(3, cause="A", effect="C")
        result = gate_causal_edge(transitive, existing, {"A", "B", "C"})
        assert any("transitive" in w.lower() for w in result.warnings)

    def test_bad_confidence(self):
        edge = make_edge(1)
        edge.confidence = "X"
        result = gate_causal_edge(edge, [], {"ev-001", "ev-002"})
        assert result.passed is False


# ── Judgment Gate ──

class TestJudgmentGate:
    def test_valid_judgment_passes(self):
        j = make_judgment(1)
        result = gate_judgment(j, [])
        assert result.passed is True

    def test_bad_target_type_fails(self):
        j = make_judgment(1, target_type="bogus")
        result = gate_judgment(j, [])
        assert result.passed is False

    def test_wrong_target_ids_count_fails(self):
        j = make_judgment(1, target_type="event_pair", target_ids=["only-one"])
        result = gate_judgment(j, [])
        assert result.passed is False

    def test_short_hypothesis_fails(self):
        j = make_judgment(1, hypothesis="Too short")
        result = gate_judgment(j, [])
        assert result.passed is False

    def test_date_reversal_fails(self):
        j = make_judgment(1, made_at="2026-10-01", expected_verification="2026-01-01")
        result = gate_judgment(j, [])
        assert result.passed is False

    def test_duplicate_hypothesis_warns(self):
        existing = make_judgment(1, hypothesis="Samsung will do something significant in the market")
        duplicate = make_judgment(2, id="judgment-storage-0002",
                                 hypothesis="Samsung will do something significant in the market")
        result = gate_judgment(duplicate, [existing])
        assert any("duplicate" in w for w in result.warnings)

    def test_empty_triggered_by_events_warns(self):
        j = make_judgment(1, triggered_by_events=[])
        result = gate_judgment(j, [])
        assert any("triggered_by_events" in w.lower() for w in result.warnings)

    def test_bad_verdict_fails(self):
        j = make_judgment(1)
        j.verdict = "bogus"
        result = gate_judgment(j, [])
        assert result.passed is False


# ── Batch ──

class TestBatch:
    def test_batch_all_pass(self):
        events = [make_event(1, id="event-storage-0001"), make_event(99, id="event-storage-0099")]
        edges = [make_edge(1, cause="event-storage-0001", effect="event-storage-0099")]
        judgments = [make_judgment(1)]
        results = gate_batch(
            events=events, edges=edges, judgments=judgments,
            existing_events=[], existing_edges=[], existing_judgments=[],
        )
        assert batch_passed(results) is True

    def test_batch_one_fails(self):
        events = [make_event(1, title="")]
        results = gate_batch(events=events)
        assert batch_passed(results) is False

    def test_batch_respects_new_event_ids(self):
        """Edges referencing events in the same batch should pass."""
        events = [make_event(1, id="event-new")]
        edges = [make_edge(1, cause="event-new", effect="event-storage-0099")]
        results = gate_batch(
            events=events, edges=edges,
            existing_events=[make_event(99, id="event-storage-0099")],
        )
        assert batch_passed(results) is True
