"""Tests for story-tracking judgment log."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import tempfile
import pytest

from story_contracts import Judgment
from repository import JsonlJudgmentRepository, StateManager
from judgment_log import (
    create_judgment, verify_judgment, defer_judgment,
    get_pending, get_due, get_verified, get_by_event, get_by_entity,
    accuracy_stats, due_alerts, recent_verifications,
)


# ── Helpers ──

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
def repo_and_state():
    with tempfile.TemporaryDirectory() as d:
        repo = JsonlJudgmentRepository(d)
        state = StateManager(d)
        yield repo, state, "storage"


@pytest.fixture
def populated(repo_and_state):
    repo, state, domain = repo_and_state
    j1 = create_judgment(repo, state, domain, "entity", ["Samsung"],
                        "Samsung ships HBM4 in Q3", "B", "2026-05-28", "2026-09-30",
                        ["event-0001"])
    j2 = create_judgment(repo, state, domain, "entity", ["SK Hynix"],
                        "SK Hynix follows with HBM4 in Q4", "C", "2026-05-28", "2026-06-15",
                        ["event-0002"])
    j3 = create_judgment(repo, state, domain, "event_pair", ["event-0001", "event-0003"],
                        "HBM demand caused NAND price rise", "B", "2026-05-30", "2026-07-01",
                        ["event-0001", "event-0003"])
    return repo, state, domain, [j1, j2, j3]


# ── Creation ──

class TestCreation:
    def test_create_entity_judgment(self, repo_and_state):
        repo, state, domain = repo_and_state
        j = create_judgment(repo, state, domain, "entity", ["Samsung"],
                           "Test hypothesis", "B", "2026-05-28", "2026-06-15")
        assert j.id == "judgment-storage-0001"
        assert repo.get(j.id) is not None

    def test_create_causal_judgment(self, repo_and_state):
        repo, state, domain = repo_and_state
        j = create_judgment(repo, state, domain, "event_pair",
                           ["event-0001", "event-0002"],
                           "Causal link", "C", "2026-05-30", "2026-07-01")
        assert j.target_type == "event_pair"
        assert len(j.target_ids) == 2

    def test_sequence_increments(self, repo_and_state):
        repo, state, domain = repo_and_state
        j1 = create_judgment(repo, state, domain, "entity", ["S"], "H1", "B", "2026-05-28", "2026-06-01")
        j2 = create_judgment(repo, state, domain, "entity", ["S"], "H2", "B", "2026-05-29", "2026-06-02")
        assert j1.id == "judgment-storage-0001"
        assert j2.id == "judgment-storage-0002"


# ── Verification ──

class TestVerification:
    def test_verify_correct(self, populated):
        repo, state, domain, judgments = populated
        j = verify_judgment(repo, "judgment-storage-0001", "correct",
                           "2026-09-15", "Samsung confirmed HBM4 shipment")
        assert j.verdict == "correct"
        assert j.evidence == "Samsung confirmed HBM4 shipment"

    def test_verify_partial(self, populated):
        repo, state, domain, judgments = populated
        j = verify_judgment(repo, "judgment-storage-0001", "partial",
                           "2026-10-01", "Shipped but only samples, not mass production")
        assert j.verdict == "partial"

    def test_verify_nonexistent(self, populated):
        repo, state, domain, judgments = populated
        result = verify_judgment(repo, "bogus", "correct", "2026-06-01", "")
        assert result is None

    def test_defer_judgment(self, populated):
        repo, state, domain, judgments = populated
        j = defer_judgment(repo, "judgment-storage-0002", "2026-09-30",
                          "SK Hynix hasn't announced yet, extending window")
        assert j.verdict == "deferred"
        assert j.expected_verification == "2026-09-30"


# ── Queries ──

class TestQueries:
    def test_pending_initial(self, populated):
        _, _, _, judgments = populated
        pending = get_pending(judgments)
        assert len(pending) == 3  # All start as pending

    def test_pending_after_verification(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "evidence")
        all_j = repo.all()
        pending = get_pending(all_j)
        assert len(pending) == 2

    def test_verified(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-06-01", "e")
        verify_judgment(repo, "judgment-storage-0002", "incorrect", "2026-06-16", "e")
        verified = get_verified(repo.all())
        assert len(verified) == 2

    def test_get_by_event(self, populated):
        _, _, _, judgments = populated
        results = get_by_event(judgments, "event-0001")
        assert len(results) == 2  # j1 and j3

    def test_get_by_entity(self, populated):
        _, _, _, judgments = populated
        results = get_by_entity(judgments, "Samsung")
        assert len(results) == 1  # j1

    def test_get_due_overdue(self, populated):
        _, _, _, judgments = populated
        # Use a date far in the future to make them all overdue
        due = get_due(judgments, as_of="2027-01-01")
        assert len(due) == 3

    def test_get_due_within_days(self, populated):
        _, _, _, judgments = populated
        # j2 is due 2026-06-15, from 2026-06-01 that's 14 days
        due = get_due(judgments, as_of="2026-06-01", within_days=14)
        assert len(due) == 1
        assert due[0].id == "judgment-storage-0002"


# ── Statistics ──

class TestStats:
    def test_empty_stats(self):
        stats = accuracy_stats([])
        assert stats["total"] == 0
        assert stats["accuracy"] == 0.0

    def test_full_stats(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "e1")
        verify_judgment(repo, "judgment-storage-0002", "incorrect", "2026-06-16", "e2")
        verify_judgment(repo, "judgment-storage-0003", "partial", "2026-07-02", "e3")

        stats = accuracy_stats(repo.all())
        assert stats["total"] == 3
        assert stats["correct"] == 1
        assert stats["incorrect"] == 1
        assert stats["partial"] == 1
        # Accuracy: (1 + 0.5) / 3 = 0.5
        assert stats["accuracy"] == 0.5

    def test_by_confidence(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "e")  # B
        verify_judgment(repo, "judgment-storage-0002", "incorrect", "2026-06-16", "e") # C
        verify_judgment(repo, "judgment-storage-0003", "correct", "2026-07-02", "e") # B

        stats = accuracy_stats(repo.all())
        assert stats["by_confidence"]["B"]["correct"] == 2
        assert stats["by_confidence"]["C"]["incorrect"] == 1

    def test_by_target_type(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "e")
        verify_judgment(repo, "judgment-storage-0003", "correct", "2026-07-02", "e")

        stats = accuracy_stats(repo.all())
        assert stats["by_target_type"]["entity"]["total"] == 1  # Only j1 verified
        assert stats["by_target_type"]["event_pair"]["total"] == 1


# ── Due Alerts ──

class TestDueAlerts:
    def test_overdue_alerts(self, populated):
        _, _, _, judgments = populated
        alerts = due_alerts(judgments, as_of="2027-01-01")
        assert len(alerts) == 3
        assert all(a["urgency"] == "overdue" for a in alerts)

    def test_soon_alerts(self, populated):
        _, _, _, judgments = populated
        # j2 is due 2026-06-15, from 2026-06-13 that's 2 days
        alerts = due_alerts(judgments, as_of="2026-06-13")
        soon = [a for a in alerts if a["urgency"] == "soon"]
        assert len(soon) == 1
        assert soon[0]["judgment_id"] == "judgment-storage-0002"

    def test_alerts_exclude_verified(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "e")
        alerts = due_alerts(repo.all(), as_of="2027-01-01")
        assert len(alerts) == 2


# ── Recent Verifications ──

class TestRecentVerifications:
    def test_recent(self, populated):
        repo, state, domain, judgments = populated
        verify_judgment(repo, "judgment-storage-0001", "correct", "2026-09-15", "e")
        recent = recent_verifications(repo.all(), days=365)
        assert len(recent) == 1

    def test_none_recent(self, populated):
        recent = recent_verifications([], days=30)
        assert len(recent) == 0
