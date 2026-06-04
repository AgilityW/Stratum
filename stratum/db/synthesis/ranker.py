"""Ranking algorithms for DB-native synthesis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from stratum.db.synthesis.judgment_feedback import JudgmentFeedbackScorer
from stratum.subsystems.event_thread import ThreadLifecycleScorer


@dataclass(frozen=True)
class ThemeRank:
    """Ranking features for a candidate synthesis theme."""

    thread_id: str
    priority: int
    event_count: int
    latest: str
    evidence_quality: int
    impact_score: int
    novelty_score: int
    uncertainty_score: int
    lifecycle_score: float
    lifecycle_momentum: str
    judgment_feedback_score: int
    judgment_feedback_status: str
    importance_score: int


class ThemeRanker:
    """Rank lower-scale thread groups for higher-scale report synthesis."""

    def rank_thread_groups(
        self,
        groups: dict[str, dict[str, Any]],
        judgments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        ranked = []
        for group in groups.values():
            events = group["events"]
            rank = self.rank_features(group, judgments=judgments)
            ranked.append({
                **group,
                "priority": rank.priority,
                "latest": rank.latest,
                "event_count": rank.event_count,
                "evidence_quality": rank.evidence_quality,
                "impact_score": rank.impact_score,
                "novelty_score": rank.novelty_score,
                "uncertainty_score": rank.uncertainty_score,
                "lifecycle_score": rank.lifecycle_score,
                "lifecycle_momentum": rank.lifecycle_momentum,
                "judgment_feedback_score": rank.judgment_feedback_score,
                "judgment_feedback_status": rank.judgment_feedback_status,
                "importance_score": rank.importance_score,
            })
        return sorted(ranked, key=self.sort_key)

    def rank_features(
        self,
        group: dict[str, Any],
        judgments: list[dict[str, Any]] | None = None,
    ) -> ThemeRank:
        events = group["events"]
        event_count = len(events)
        evidence_quality = self.evidence_quality(events)
        impact_score = self.impact_score(events)
        novelty_score = self.novelty_score(events)
        uncertainty_score = self.uncertainty_score(events)
        lifecycle = self.lifecycle_features(events)
        judgment_feedback = JudgmentFeedbackScorer().score_group(group, judgments)
        importance_score = (
            event_count * 3
            + evidence_quality * 2
            + impact_score * 3
            + novelty_score * 2
            + int(round(lifecycle["lifecycle_score"] * 10))
            + judgment_feedback.score
            - uncertainty_score * 2
        )
        return ThemeRank(
            thread_id=str(group.get("thread_id") or ""),
            priority=min(int(event.get("priority") or 999) for event in events),
            event_count=event_count,
            latest=max(event.get("date") or "" for event in events),
            evidence_quality=evidence_quality,
            impact_score=impact_score,
            novelty_score=novelty_score,
            uncertainty_score=uncertainty_score,
            lifecycle_score=lifecycle["lifecycle_score"],
            lifecycle_momentum=lifecycle["lifecycle_momentum"],
            judgment_feedback_score=judgment_feedback.score,
            judgment_feedback_status=judgment_feedback.status,
            importance_score=importance_score,
        )

    def sort_key(self, item: dict[str, Any]) -> tuple[int, int, float, int, int, str]:
        return (
            int(item.get("priority") or 999),
            -int(item.get("importance_score") or 0),
            -float(item.get("lifecycle_score") or 0.0),
            -int(item.get("event_count") or 0),
            -_date_rank(str(item.get("latest") or "")),
            str(item.get("thread_id") or ""),
        )

    def evidence_quality(self, events: list[dict[str, Any]]) -> int:
        """Score source and article support for one candidate theme."""
        source_domains = {
            str(source).lower()
            for event in events
            for source in _jsonish_list(event.get("source_domains"))
            if source
        }
        article_ids = {
            str(article_id)
            for event in events
            for article_id in _jsonish_list(event.get("article_ids"))
            if article_id
        }
        confidence_bonus = sum(_confidence_score(event.get("confidence")) for event in events)
        return min(len(source_domains), 3) + min(len(article_ids), 3) + min(confidence_bonus, 3)

    def impact_score(self, events: list[dict[str, Any]]) -> int:
        """Score business or technical impact signals for executive ranking."""
        text = " ".join(_event_text(event) for event in events).lower()
        high_impact_terms = {
            "ai",
            "asp",
            "capacity",
            "capex",
            "customer",
            "data center",
            "hbm",
            "margin",
            "nvidia",
            "qualification",
            "revenue",
            "supply",
            "yield",
        }
        return min(sum(1 for term in high_impact_terms if term in text), 6)

    def novelty_score(self, events: list[dict[str, Any]]) -> int:
        """Score spread across dates and source events as a persistence/novelty proxy."""
        dates = {event.get("date") for event in events if event.get("date")}
        source_event_ids = {
            str(source_event_id)
            for event in events
            for source_event_id in _jsonish_list(event.get("source_event_ids"))
            if source_event_id
        }
        return min(len(dates), 3) + min(len(source_event_ids), 3)

    def uncertainty_score(self, events: list[dict[str, Any]]) -> int:
        """Score weak-confidence or speculative signals that should not lead."""
        text = " ".join(_event_text(event) for event in events).lower()
        speculative_terms = {"could", "may", "might", "reportedly", "rumor", "unconfirmed"}
        low_confidence = sum(1 for event in events if str(event.get("confidence") or "").upper() in {"C", "D", "LOW"})
        return min(low_confidence + sum(1 for term in speculative_terms if term in text), 5)

    def lifecycle_features(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Score lifecycle momentum for one candidate theme."""
        dates = [_parse_date(event.get("date")) for event in events]
        observed_dates = [value for value in dates if value]
        latest_event = max(
            events,
            key=lambda event: _date_rank(str(event.get("date") or "")),
            default={},
        )
        latest_date = str(latest_event.get("date") or "")
        current_status = str(latest_event.get("status") or "active").lower()
        if current_status in {"cooling", "dormant", "resolved", "archived"}:
            return {
                "lifecycle_score": ThreadLifecycleScorer().score_status(
                    status=current_status,
                    observed_count=len(events),
                ),
                "lifecycle_momentum": current_status,
            }
        if latest_date and observed_dates:
            decision = ThreadLifecycleScorer().evaluate(
                current_status=current_status,
                run_date=latest_date,
                observed_dates=observed_dates,
                last_updated=latest_date,
            )
            return {
                "lifecycle_score": decision.lifecycle_score,
                "lifecycle_momentum": decision.momentum,
            }
        score = ThreadLifecycleScorer().score_status(
            status=current_status,
            observed_count=len(events),
        )
        return {
            "lifecycle_score": score,
            "lifecycle_momentum": current_status,
        }


def _confidence_score(value: Any) -> int:
    return {"A": 2, "B": 1}.get(str(value or "").upper(), 0)


def _event_text(event: dict[str, Any]) -> str:
    fields = [
        event.get("title", ""),
        event.get("summary", ""),
        " ".join(str(value) for value in _jsonish_list(event.get("term_ids"))),
        " ".join(str(value) for value in _jsonish_list(event.get("entity_ids"))),
    ]
    return " ".join(str(field) for field in fields if field)


def _jsonish_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [value]
    return [value]


def _date_rank(value: str) -> int:
    digits = "".join(char for char in value if char.isdigit())
    return int(digits or 0)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
