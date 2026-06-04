"""Judgment feedback scoring for DB-native synthesis ranking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from stratum.db.judgment_lifecycle import JudgmentLifecyclePolicy


@dataclass(frozen=True)
class JudgmentFeedback:
    """Structured feedback signal for one candidate synthesis theme."""

    score: int
    status: str
    supported_count: int = 0
    challenged_count: int = 0
    pending_count: int = 0
    matched_judgment_ids: list[str] = field(default_factory=list)


class JudgmentFeedbackScorer:
    """Score reviewed judgments that map to a thread group."""

    def __init__(self, policy: JudgmentLifecyclePolicy | None = None):
        self.policy = policy or JudgmentLifecyclePolicy()

    def score_group(
        self,
        group: dict[str, Any],
        judgments: list[dict[str, Any]] | None,
    ) -> JudgmentFeedback:
        judgments = judgments or []
        group_threads = self._group_thread_ids(group)
        group_entities = self._group_entity_ids(group)
        supported = 0
        challenged = 0
        pending = 0
        confidence_effect = 0
        matched_ids: list[str] = []

        for judgment in judgments:
            if not self._matches_group(judgment, group_threads, group_entities):
                continue
            matched_ids.append(str(judgment.get("id") or ""))
            review = self.policy.review_state(judgment)
            confidence_effect += review.confidence_effect
            if review.state == "supported":
                supported += 1
            elif review.state in {"challenged", "invalidated"}:
                challenged += 1
            elif review.state == "partial":
                supported += 1
                challenged += 1
            else:
                pending += 1

        score = max(-6, min(4, confidence_effect))
        return JudgmentFeedback(
            score=score,
            status=self._status(supported, challenged, pending),
            supported_count=supported,
            challenged_count=challenged,
            pending_count=pending,
            matched_judgment_ids=[judgment_id for judgment_id in matched_ids if judgment_id],
        )

    def _matches_group(
        self,
        judgment: dict[str, Any],
        group_threads: set[str],
        group_entities: set[str],
    ) -> bool:
        judgment_threads = {str(value) for value in _jsonish_list(judgment.get("target_thread_ids")) if value}
        if judgment_threads & group_threads:
            return True
        judgment_entities = {str(value) for value in _jsonish_list(judgment.get("target_entity_ids")) if value}
        return bool(judgment_entities and judgment_entities & group_entities)

    def _group_thread_ids(self, group: dict[str, Any]) -> set[str]:
        return {
            str(value)
            for event in group.get("events", [])
            for value in [group.get("thread_id"), event.get("thread_id")]
            if value
        }

    def _group_entity_ids(self, group: dict[str, Any]) -> set[str]:
        return {
            str(entity_id)
            for event in group.get("events", [])
            for entity_id in _jsonish_list(event.get("entity_ids"))
            if entity_id
        }

    def _status(self, supported: int, challenged: int, pending: int) -> str:
        if supported and challenged:
            return "mixed"
        if challenged:
            return "challenged"
        if supported:
            return "supported"
        if pending:
            return "pending"
        return "none"


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
