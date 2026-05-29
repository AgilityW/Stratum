"""Judgment log — record, verify, and track accuracy of hypotheses.

A Judgment is a testable hypothesis about an entity or causal relationship.
This module provides the operational layer: create, verify, query, and stats.

All operations work through the JudgmentRepository interface.
"""

from datetime import date, timedelta
from typing import Optional

from story_contracts import Judgment


# ── Creation ──

def create_judgment(
    repo,
    state_manager,
    domain_id: str,
    target_type: str,
    target_ids: list[str],
    hypothesis: str,
    confidence: str,
    made_at: str,
    expected_verification: str,
    triggered_by_events: list[str] = None,
) -> Judgment:
    """Create a new judgment with auto-incremented ID.

    Returns the created judgment (already persisted).
    """
    seq = state_manager.next_judgment_seq()
    judgment = Judgment(
        id=f"judgment-{domain_id}-{seq:04d}",
        target_type=target_type,
        target_ids=target_ids,
        hypothesis=hypothesis,
        confidence=confidence,
        made_at=made_at,
        expected_verification=expected_verification,
        triggered_by_events=triggered_by_events or [],
    )
    repo.add(judgment)
    return judgment


# ── Verification ──

def verify_judgment(
    repo,
    judgment_id: str,
    verdict: str,
    verified_at: str,
    evidence: str = "",
) -> Optional[Judgment]:
    """Record a verification result for a judgment.

    Updates the judgment in-place via repo.update().

    Returns the updated judgment, or None if not found.
    """
    judgment = repo.get(judgment_id)
    if judgment is None:
        return None

    judgment.verdict = verdict
    judgment.verified_at = verified_at
    judgment.evidence = evidence
    repo.update(judgment)
    return judgment


def defer_judgment(
    repo,
    judgment_id: str,
    new_expected_verification: str,
    reason: str = "",
) -> Optional[Judgment]:
    """Defer a judgment's verification window.

    Sets verdict to 'deferred' and updates expected_verification.
    """
    judgment = repo.get(judgment_id)
    if judgment is None:
        return None

    judgment.verdict = "deferred"
    judgment.expected_verification = new_expected_verification
    judgment.evidence = f"Deferred: {reason}" if reason else "Deferred"
    repo.update(judgment)
    return judgment


# ── Queries ──

def get_pending(judgments: list[Judgment]) -> list[Judgment]:
    """Judgments still awaiting verification (pending or deferred)."""
    return [j for j in judgments if j.verdict in ("pending", "deferred")]


def get_due(
    judgments: list[Judgment],
    as_of: Optional[str] = None,
    within_days: Optional[int] = None,
) -> list[Judgment]:
    """Judgments past their expected_verification date.

    If within_days is set, returns judgments due within that many days from as_of.
    """
    today = date.today() if as_of is None else date.fromisoformat(as_of)
    due = []

    for j in judgments:
        if j.verdict not in ("pending", "deferred"):
            continue
        try:
            expected = date.fromisoformat(j.expected_verification[:10])
        except (ValueError, TypeError):
            continue

        if within_days:
            delta = (expected - today).days
            if 0 <= delta <= within_days:
                due.append(j)
        else:
            if expected <= today:
                due.append(j)

    # Sort by most overdue first
    due.sort(key=lambda j: j.expected_verification)
    return due


def get_verified(judgments: list[Judgment]) -> list[Judgment]:
    """Judgments that have reached a final verdict (correct, incorrect, partial, unverifiable)."""
    return [j for j in judgments if j.verdict in ("correct", "incorrect", "partial", "unverifiable")]


def get_by_event(judgments: list[Judgment], event_id: str) -> list[Judgment]:
    """Judgments triggered by a specific event."""
    return [j for j in judgments if event_id in j.triggered_by_events]


def get_by_entity(judgments: list[Judgment], entity_id: str) -> list[Judgment]:
    """Entity judgments for a specific entity."""
    return [
        j for j in judgments
        if j.target_type == "entity" and entity_id in j.target_ids
    ]


# ── Statistics ──

def accuracy_stats(judgments: list[Judgment]) -> dict:
    """Compute judgment accuracy statistics.

    Only considers judgments with final verdicts (correct/incorrect/partial/unverifiable).
    Partial counts as 0.5 correct in the accuracy rate.
    Unverifiable is excluded from the rate calculation.
    """
    final = get_verified(judgments)

    correct = sum(1 for j in final if j.verdict == "correct")
    partial = sum(1 for j in final if j.verdict == "partial")
    incorrect = sum(1 for j in final if j.verdict == "incorrect")
    unverifiable = sum(1 for j in final if j.verdict == "unverifiable")

    # Rateable = correct + partial + incorrect (exclude unverifiable)
    rateable = correct + partial + incorrect
    weighted_correct = correct + (partial * 0.5)
    accuracy = weighted_correct / rateable if rateable > 0 else 0.0

    # By confidence
    by_confidence = {}
    for conf in ("A", "B", "C"):
        conf_judgments = [j for j in final if j.confidence == conf]
        by_confidence[conf] = _conf_stats(conf_judgments)

    # By target type
    by_type = {}
    for ttype in ("entity", "event_pair"):
        type_judgments = [j for j in final if j.target_type == ttype]
        by_type[ttype] = _conf_stats(type_judgments)

    pending_count = len(get_pending(judgments))
    overdue_count = len(get_due(judgments))

    return {
        "total": len(judgments),
        "finalized": len(final),
        "pending": pending_count,
        "overdue": overdue_count,
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "unverifiable": unverifiable,
        "accuracy": round(accuracy, 3),
        "by_confidence": by_confidence,
        "by_target_type": by_type,
    }


def _conf_stats(judgments: list[Judgment]) -> dict:
    if not judgments:
        return {"total": 0, "correct": 0, "incorrect": 0, "accuracy": 0.0}
    correct = sum(1 for j in judgments if j.verdict == "correct")
    partial = sum(1 for j in judgments if j.verdict == "partial")
    incorrect = sum(1 for j in judgments if j.verdict == "incorrect")
    rateable = correct + partial + incorrect
    weighted = correct + (partial * 0.5)
    return {
        "total": len(judgments),
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "accuracy": round(weighted / rateable, 3) if rateable > 0 else 0.0,
    }


# ── Due Alerts ──

def due_alerts(judgments: list[Judgment], as_of: Optional[str] = None) -> list[dict]:
    """Generate alerts for overdue and soon-due judgments.

    Returns list of {judgment_id, hypothesis, due_date, days_overdue, urgency}
    """
    today = date.today() if as_of is None else date.fromisoformat(as_of)
    alerts = []

    for j in judgments:
        if j.verdict not in ("pending", "deferred"):
            continue
        try:
            expected = date.fromisoformat(j.expected_verification[:10])
        except (ValueError, TypeError):
            continue

        delta = (today - expected).days
        if delta >= 0:
            alerts.append({
                "judgment_id": j.id,
                "hypothesis": j.hypothesis,
                "due_date": j.expected_verification,
                "days_overdue": delta,
                "urgency": "overdue",
            })
        elif delta >= -3:
            alerts.append({
                "judgment_id": j.id,
                "hypothesis": j.hypothesis,
                "due_date": j.expected_verification,
                "days_overdue": abs(delta),
                "urgency": "soon",
            })

    alerts.sort(key=lambda a: a["days_overdue"], reverse=True)
    return alerts


def recent_verifications(judgments: list[Judgment], days: int = 30) -> list[Judgment]:
    """Judgments verified in the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [
        j for j in judgments
        if j.verified_at and j.verified_at >= cutoff
    ]
