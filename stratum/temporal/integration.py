"""Integration of fresh evidence with persisted DB memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from stratum.temporal.exploring import Exploring


@dataclass(frozen=True)
class IntegrationDecision:
    """Structured decision for combining DB memory and same-scale fresh evidence."""

    timescale: str
    enabled: bool
    status: str
    fresh_articles: int
    db_reports: int
    db_events: int
    include_same_scale_fresh: bool
    use_db_memory: bool
    role: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timescale": self.timescale,
            "enabled": self.enabled,
            "status": self.status,
            "fresh_articles": self.fresh_articles,
            "db_reports": self.db_reports,
            "db_events": self.db_events,
            "include_same_scale_fresh": self.include_same_scale_fresh,
            "use_db_memory": self.use_db_memory,
            "role": self.role,
            "reason": self.reason,
        }


class Integration:
    """Integrate fresh exploring results into DB-native synthesis inputs."""

    def __init__(self, exploring: "Exploring | None" = None):
        if exploring is None:
            from stratum.temporal.exploring import Exploring

            exploring = Exploring()
        self.exploring = exploring

    def include_same_scale_fresh(self, timescale: str, result: dict[str, Any]) -> bool:
        return self.decide(timescale, result).include_same_scale_fresh

    def decide(
        self,
        timescale: str,
        result: dict[str, Any],
        *,
        db_memory: dict[str, Any] | None = None,
    ) -> IntegrationDecision:
        """Decide how exploring results participate with persisted DB memory."""
        db_reports = int((db_memory or {}).get("source_reports") or 0)
        db_events = int((db_memory or {}).get("source_events") or 0)
        db_memory_available = db_reports > 0 or db_events > 0
        enabled = self.exploring.enabled_for(timescale)
        status = str(result.get("status") or "unknown")
        fresh_count = int(result.get("articles") or 0)
        fresh_available = enabled and status == "success" and fresh_count > 0

        if not enabled:
            role = "not_applicable"
            reason = f"exploring is not enabled for {timescale}"
        elif fresh_available and db_memory_available:
            role = "fresh_supplements_db_memory"
            reason = "fresh evidence and persisted DB memory are both available"
        elif fresh_available:
            role = "fresh_only_watch"
            reason = "fresh evidence is available but DB memory has no supporting lower-scale records"
        elif db_memory_available and status == "success":
            role = "db_memory_only_no_fresh_hits"
            reason = "exploring succeeded with no accepted same-scale articles"
        elif db_memory_available:
            role = "db_memory_only_fresh_failed"
            reason = f"exploring status={status}; use persisted DB memory only"
        else:
            role = "insufficient_evidence"
            reason = f"exploring status={status}; no DB memory counts supplied"

        return IntegrationDecision(
            timescale=timescale,
            enabled=enabled,
            status=status,
            fresh_articles=fresh_count,
            db_reports=db_reports,
            db_events=db_events,
            include_same_scale_fresh=fresh_available,
            use_db_memory=db_memory_available,
            role=role,
            reason=reason,
        )
