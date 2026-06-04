"""Judgment and causal-edge lifecycle policy for DB persistence and reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any


_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


@dataclass(frozen=True)
class JudgmentDueDecision:
    """Structured due-check output for pending judgments."""

    is_due: bool
    due_date: str | None
    basis: str
    reason: str


@dataclass(frozen=True)
class JudgmentReviewState:
    """Normalized review state consumed by DB reads and synthesis feedback."""

    state: str
    confidence_effect: int
    is_pending: bool
    is_terminal: bool
    reason: str


class JudgmentLifecyclePolicy:
    """Own judgment due checks and verification-field preservation."""

    pending_results = {"", "pending", "deferred", None}
    supportive_results = {"supported", "correct", "confirmed"}
    challenged_results = {"challenged", "incorrect", "rejected"}
    invalidated_results = {"invalidated", "expired", "superseded"}
    partial_results = {"partial", "partially_correct", "mixed"}

    def evaluate_due(
        self,
        judgment: dict[str, Any],
        *,
        end_period: str | None = None,
    ) -> JudgmentDueDecision:
        review = self.review_state(judgment)
        if not review.is_pending:
            return JudgmentDueDecision(False, None, "result", f"judgment already has result={review.state}")
        if not end_period:
            return JudgmentDueDecision(True, None, "no_window", "pending judgment requested without an end period")

        end_date = _parse_date(end_period)
        if not end_date:
            return JudgmentDueDecision(True, None, "invalid_window", "end period has no parseable date")

        expected = _parse_expected_verification(judgment.get("expected_verification"))
        if expected:
            is_due = expected <= end_date
            return JudgmentDueDecision(
                is_due=is_due,
                due_date=expected.isoformat(),
                basis="expected_verification",
                reason=(
                    "expected verification date is inside the requested window"
                    if is_due else "expected verification date is after the requested window"
                ),
            )

        created_at = _parse_date(judgment.get("created_at"))
        if created_at:
            is_due = created_at <= end_date
            return JudgmentDueDecision(
                is_due=is_due,
                due_date=created_at.isoformat(),
                basis="created_at",
                reason=(
                    "created date is inside the requested window"
                    if is_due else "created date is after the requested window"
                ),
            )

        return JudgmentDueDecision(True, None, "missing_dates", "pending judgment has no verification or created date")

    def is_due(self, judgment: dict[str, Any], *, end_period: str | None = None) -> bool:
        """Return True when a pending judgment should be revisited."""
        return self.evaluate_due(judgment, end_period=end_period).is_due

    def review_state(self, judgment: dict[str, Any]) -> JudgmentReviewState:
        """Normalize judgment review results into scored lifecycle states."""
        result = str(judgment.get("result") or "").strip().lower()
        if result in self.supportive_results:
            return JudgmentReviewState("supported", 2, False, True, "review supports the judgment")
        if result in self.challenged_results:
            return JudgmentReviewState("challenged", -3, False, True, "review challenges the judgment")
        if result in self.invalidated_results:
            return JudgmentReviewState("invalidated", -4, False, True, "judgment is invalidated or expired")
        if result in self.partial_results:
            return JudgmentReviewState("partial", -1, False, False, "review is mixed or partially supported")
        if result == "deferred":
            return JudgmentReviewState("deferred", 0, True, False, "review was deferred to a later window")
        return JudgmentReviewState("pending", 0, True, False, "judgment is pending review")

    def preserve_judgment_verification(self, existing: Any | None) -> dict[str, Any]:
        """Return existing judgment review fields that must survive replacement."""
        if not existing:
            return {
                "result": None,
                "verified_at": None,
                "verified_by_scale": None,
                "actual_outcome": None,
            }
        return {
            "result": existing["result"],
            "verified_at": existing["verified_at"],
            "verified_by_scale": existing["verified_by_scale"],
            "actual_outcome": existing["actual_outcome"],
        }

    def preserve_causal_edge_verification(self, existing: Any | None) -> dict[str, Any]:
        """Return existing causal-edge review fields that must survive replacement."""
        if not existing:
            return {
                "verified": None,
                "verified_at": None,
                "verified_by_scale": None,
            }
        return {
            "verified": existing["verified"],
            "verified_at": existing["verified_at"],
            "verified_by_scale": existing["verified_by_scale"],
        }


def _parse_expected_verification(value: Any) -> date | None:
    if not value:
        return None
    match = _ISO_DATE_RE.search(str(value))
    if not match:
        return None
    return _parse_date(match.group(1))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)).date()
        except ValueError:
            return None
