"""Tests for story-tracking repository layer."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import json
import pytest
import tempfile

from story_contracts import EventRecord, CausalEdge, Judgment, TimelineEntry, ScaleRef, Prominence
from repository import (
    StateManager,
    JsonlEventRepository,
    JsonlCausalRepository,
    JsonlJudgmentRepository,
)


# ── Helpers ──

def make_event(seq: int, **overrides) -> EventRecord:
    defaults = dict(
        id=f"event-storage-{seq:04d}",
        title=f"Test Event {seq}",
        canonical_question=f"What is event {seq}?",
        created="2026-05-28",
        last_updated="2026-05-28",
        topic_tags=["HBM"],
        entity_tags=["Samsung"],
    )
    defaults.update(overrides)
    return EventRecord(**defaults)


def make_causal(seq: int, **overrides) -> CausalEdge:
    defaults = dict(
        id=f"causal-storage-{seq:04d}",
        cause_id=f"event-storage-{seq:04d}",
        effect_id=f"event-storage-{seq+100:04d}",
        mechanism=f"Causal mechanism #{seq}",
        confidence="B",
        created="2026-05-30",
    )
    defaults.update(overrides)
    return CausalEdge(**defaults)


def make_judgment(seq: int, **overrides) -> Judgment:
    defaults = dict(
        id=f"judgment-storage-{seq:04d}",
        target_type="entity",
        target_ids=["Samsung"],
        hypothesis=f"Hypothesis #{seq}",
        confidence="B",
        made_at="2026-05-28",
        expected_verification="2026-06-15",
    )
    defaults.update(overrides)
    return Judgment(**defaults)


# ── Fixtures ──

@pytest.fixture
def repo_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def event_repo(repo_dir):
    return JsonlEventRepository(repo_dir, "storage")


@pytest.fixture
def causal_repo(repo_dir):
    return JsonlCausalRepository(repo_dir)


@pytest.fixture
def judgment_repo(repo_dir):
    return JsonlJudgmentRepository(repo_dir)


# ── StateManager ──

class TestStateManager:
    def test_counters_start_at_1(self, repo_dir):
        sm = StateManager(repo_dir)
        assert sm.next_event_seq() == 1
        assert sm.next_causal_seq() == 1
        assert sm.next_judgment_seq() == 1

    def test_counters_increment(self, repo_dir):
        sm = StateManager(repo_dir)
        assert sm.next_event_seq() == 1
        assert sm.next_event_seq() == 2
        assert sm.next_event_seq() == 3

    def test_state_persists(self, repo_dir):
        sm = StateManager(repo_dir)
        sm.next_event_seq()
        sm.next_event_seq()

        sm2 = StateManager(repo_dir)
        assert sm2.next_event_seq() == 3  # Continues from where we left

    def test_independent_counters(self, repo_dir):
        sm = StateManager(repo_dir)
        e = sm.next_event_seq()
        c = sm.next_causal_seq()
        j = sm.next_judgment_seq()
        assert e == 1
        assert c == 1
        assert j == 1

    def test_creates_state_file(self, repo_dir):
        sm = StateManager(repo_dir)
        sm.next_event_seq()
        assert os.path.exists(os.path.join(repo_dir, "state.json"))


# ── EventRepository ──

class TestEventRepository:
    def test_add_and_get(self, event_repo, repo_dir):
        event = make_event(1)
        event_repo.add(event)
        retrieved = event_repo.get("event-storage-0001")
        assert retrieved is not None
        assert retrieved.title == "Test Event 1"
        assert os.path.exists(os.path.join(repo_dir, "events.jsonl"))

    def test_get_nonexistent(self, event_repo):
        assert event_repo.get("bogus") is None

    def test_all_returns_empty(self, event_repo):
        assert event_repo.all() == []

    def test_all_returns_all(self, event_repo):
        event_repo.add(make_event(1))
        event_repo.add(make_event(2))
        event_repo.add(make_event(3))
        assert len(event_repo.all()) == 3

    def test_count(self, event_repo):
        assert event_repo.count() == 0
        event_repo.add(make_event(1))
        assert event_repo.count() == 1

    def test_update_existing(self, event_repo):
        event = make_event(1)
        event_repo.add(event)
        event.title = "Updated Title"
        event.last_updated = "2026-05-29"
        event_repo.update(event)
        retrieved = event_repo.get("event-storage-0001")
        assert retrieved.title == "Updated Title"
        assert retrieved.last_updated == "2026-05-29"

    def test_update_nonexistent_raises(self, event_repo):
        with pytest.raises(ValueError):
            event_repo.update(make_event(1))

    def test_update_preserves_other_records(self, event_repo):
        event_repo.add(make_event(1))
        event_repo.add(make_event(2))
        event_repo.add(make_event(3))

        e2 = event_repo.get("event-storage-0002")
        e2.title = "Modified Event 2"
        event_repo.update(e2)

        assert event_repo.count() == 3
        assert event_repo.get("event-storage-0001").title != "Modified Event 2"

    def test_tags_persist(self, event_repo):
        event = make_event(1, topic_tags=["HBM", "memory"], entity_tags=["Samsung", "NVIDIA"])
        event_repo.add(event)
        retrieved = event_repo.get("event-storage-0001")
        assert "HBM" in retrieved.topic_tags
        assert "NVIDIA" in retrieved.entity_tags

    def test_scale_refs_persist(self, event_repo):
        event = make_event(1)
        event.scale_refs = [ScaleRef(
            scale="daily", briefing_id="daily-2026-05-28",
            date="2026-05-28", prominence=Prominence.LEAD,
            synthesis="Test synthesis")]
        event_repo.add(event)
        retrieved = event_repo.get("event-storage-0001")
        assert len(retrieved.scale_refs) == 1

    def test_loads_from_existing_file(self, event_repo, repo_dir):
        event_repo.add(make_event(1))
        event_repo.add(make_event(2))

        repo2 = JsonlEventRepository(repo_dir, "storage")
        assert repo2.count() == 2


# ── CausalRepository ──

class TestCausalRepository:
    def test_add_and_get(self, causal_repo, repo_dir):
        edge = make_causal(1)
        causal_repo.add(edge)
        assert os.path.exists(os.path.join(repo_dir, "causal.jsonl"))
        retrieved = causal_repo.get("causal-storage-0001")
        assert retrieved is not None
        assert retrieved.mechanism == "Causal mechanism #1"

    def test_get_nonexistent(self, causal_repo):
        assert causal_repo.get("bogus") is None

    def test_find_by_cause(self, causal_repo):
        causal_repo.add(make_causal(1, cause_id="ev-001", effect_id="ev-100"))
        causal_repo.add(make_causal(2, cause_id="ev-001", effect_id="ev-101"))
        causal_repo.add(make_causal(3, cause_id="ev-002", effect_id="ev-102"))
        results = causal_repo.find_by_cause("ev-001")
        assert len(results) == 2

    def test_find_by_effect(self, causal_repo):
        causal_repo.add(make_causal(1, cause_id="ev-001", effect_id="ev-100"))
        causal_repo.add(make_causal(2, cause_id="ev-002", effect_id="ev-100"))
        results = causal_repo.find_by_effect("ev-100")
        assert len(results) == 2

    def test_all_empty(self, causal_repo):
        assert causal_repo.all() == []

    def test_count(self, causal_repo):
        assert causal_repo.count() == 0
        causal_repo.add(make_causal(1))
        assert causal_repo.count() == 1


# ── JudgmentRepository ──

class TestJudgmentRepository:
    def test_add_and_get(self, judgment_repo, repo_dir):
        j = make_judgment(1)
        judgment_repo.add(j)
        assert os.path.exists(os.path.join(repo_dir, "judgments.jsonl"))
        retrieved = judgment_repo.get("judgment-storage-0001")
        assert retrieved is not None
        assert retrieved.hypothesis == "Hypothesis #1"

    def test_get_nonexistent(self, judgment_repo):
        assert judgment_repo.get("bogus") is None

    def test_update_verdict(self, judgment_repo):
        j = make_judgment(1)
        judgment_repo.add(j)
        j.verdict = "correct"
        j.verified_at = "2026-06-10"
        j.evidence = "Verified by press release"
        judgment_repo.update(j)
        retrieved = judgment_repo.get("judgment-storage-0001")
        assert retrieved.verdict == "correct"
        assert retrieved.evidence == "Verified by press release"

    def test_update_nonexistent_raises(self, judgment_repo):
        with pytest.raises(ValueError):
            judgment_repo.update(make_judgment(1))

    def test_find_by_verdict(self, judgment_repo):
        judgment_repo.add(make_judgment(1))
        judgment_repo.add(make_judgment(2))
        j3 = make_judgment(3)
        j3.verdict = "correct"
        judgment_repo.add(j3)

        pending = judgment_repo.find_by_verdict("pending")
        correct = judgment_repo.find_by_verdict("correct")
        assert len(pending) == 2
        assert len(correct) == 1

    def test_all_empty(self, judgment_repo):
        assert judgment_repo.all() == []

    def test_loads_from_existing_file(self, judgment_repo, repo_dir):
        judgment_repo.add(make_judgment(1))
        judgment_repo.add(make_judgment(2))

        repo2 = JsonlJudgmentRepository(repo_dir)
        assert repo2.count() == 2
