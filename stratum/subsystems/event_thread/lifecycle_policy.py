"""Reusable lifecycle scoring for event threads across report scales."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class LifecycleConfig:
    """Thresholds and weights for thread lifecycle decisions."""

    cooling_after_days: int = 7
    resolved_after_days: int = 30
    archive_resolved_after_days: int = 7
    status_scores: dict[str, float] = field(default_factory=lambda: {
        "emerging": 0.72,
        "active": 0.9,
        "cooling": 0.42,
        "dormant": 0.05,
        "resolved": 0.12,
        "archived": 0.0,
    })
    persistence_bonus_per_update: float = 0.06
    max_persistence_bonus: float = 0.18
    recent_update_bonus: float = 0.08


@dataclass(frozen=True)
class LifecycleDecision:
    """Structured lifecycle output for downstream ranking or reporting."""

    status: str
    momentum: str
    lifecycle_score: float
    days_since_last: int | None
    observed_updates: int
    should_archive: bool
    reason: str


class ThreadLifecycleScorer:
    """Score thread lifecycle status, momentum, and archive readiness."""

    def __init__(self, config: LifecycleConfig | None = None):
        self.config = config or LifecycleConfig()

    def evaluate(
        self,
        *,
        current_status: str,
        run_date: str,
        observed_dates: list[date],
        last_updated: str | None = None,
    ) -> LifecycleDecision:
        run_day = date.fromisoformat(str(run_date)[:10])
        visible_dates = sorted(d for d in observed_dates if d <= run_day)
        days_since_last = None

        if visible_dates:
            last_seen = visible_dates[-1]
            days_since_last = (run_day - last_seen).days
            status = self._status_from_observations(
                current_status=current_status,
                observed_count=len(visible_dates),
                days_since_last=days_since_last,
            )
        else:
            status = current_status

        should_archive = self._should_archive(
            current_status=current_status,
            run_day=run_day,
            last_updated=last_updated,
        )
        momentum = self._momentum(
            status=status,
            observed_count=len(visible_dates),
            days_since_last=days_since_last,
        )
        score = self.score_status(
            status=status,
            observed_count=len(visible_dates),
            days_since_last=days_since_last,
        )
        return LifecycleDecision(
            status=status,
            momentum=momentum,
            lifecycle_score=score,
            days_since_last=days_since_last,
            observed_updates=len(visible_dates),
            should_archive=should_archive,
            reason=self._reason(status, momentum, days_since_last, len(visible_dates)),
        )

    def score_status(
        self,
        *,
        status: str,
        observed_count: int = 0,
        days_since_last: int | None = None,
    ) -> float:
        base = self.config.status_scores.get(status, 0.0)
        persistence_bonus = min(
            max(0, observed_count - 1) * self.config.persistence_bonus_per_update,
            self.config.max_persistence_bonus,
        )
        recency_bonus = (
            self.config.recent_update_bonus
            if days_since_last is not None and days_since_last <= 1 and status in {"emerging", "active"}
            else 0.0
        )
        return round(min(1.0, max(0.0, base + persistence_bonus + recency_bonus)), 3)

    def _status_from_observations(
        self,
        *,
        current_status: str,
        observed_count: int,
        days_since_last: int,
    ) -> str:
        if days_since_last >= self.config.resolved_after_days:
            return "resolved"
        if days_since_last >= self.config.cooling_after_days:
            return "cooling"
        if current_status == "emerging" and observed_count == 1 and days_since_last == 0:
            return "emerging"
        return "active"

    def _should_archive(
        self,
        *,
        current_status: str,
        run_day: date,
        last_updated: str | None,
    ) -> bool:
        if current_status != "resolved" or not last_updated:
            return False
        last_day = date.fromisoformat(str(last_updated)[:10])
        return (run_day - last_day).days > self.config.archive_resolved_after_days

    def _momentum(
        self,
        *,
        status: str,
        observed_count: int,
        days_since_last: int | None,
    ) -> str:
        if status in {"archived", "dormant", "resolved"}:
            return status
        if status == "cooling":
            return "cooling"
        if status == "active" and observed_count >= 3 and (days_since_last or 0) <= 3:
            return "escalating"
        if status == "emerging":
            return "new"
        return "active"

    def _reason(
        self,
        status: str,
        momentum: str,
        days_since_last: int | None,
        observed_count: int,
    ) -> str:
        if days_since_last is None:
            return f"{status}: no visible timeline observations"
        return (
            f"{status}/{momentum}: {observed_count} visible updates, "
            f"{days_since_last} days since last update"
        )
