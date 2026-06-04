"""Project-level evidence acquisition policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_ACCESS_PRIORITY = {
    "rss": 10,
    "direct_fetch": 20,
    "browser": 30,
    "discovery": 40,
    "search": 40,
    "database": 50,
}

DEFAULT_ACCESS_COST = {
    "rss": 1.0,
    "direct_fetch": 2.0,
    "browser": 5.0,
    "discovery": 8.0,
    "search": 8.0,
    "database": 0.5,
}


@dataclass(frozen=True)
class AcquisitionStep:
    """A planned acquisition step with its policy tier."""

    name: str
    tier: int
    reason: str


@dataclass(frozen=True)
class SourcePriorityScore:
    """Health-adjusted priority features for one configured source."""

    source_id: str
    access_tier: int
    health_penalty: int
    contribution_score: float
    reason: str


class SourcePriorityScorer:
    """Score configured sources within the project-level acquisition order."""

    def __init__(self, access_priority: dict[str, int] | None = None):
        self.access_priority = dict(DEFAULT_ACCESS_PRIORITY)
        if access_priority:
            self.access_priority.update(access_priority)

    def score(self, source: dict[str, Any], source_health: dict[str, dict[str, Any]] | None = None) -> SourcePriorityScore:
        """Return a source score; lower health penalty runs earlier within a tier."""
        source_id = str(source.get("id") or source.get("source") or "")
        health = (source_health or {}).get(source_id, {})
        access = str(source.get("access") or "")
        penalty = self.health_penalty(health)
        contribution_score = float(health.get("selected_rate") or health.get("hit_rate") or 0.0)
        return SourcePriorityScore(
            source_id=source_id,
            access_tier=self.access_priority.get(access, 100),
            health_penalty=penalty,
            contribution_score=contribution_score,
            reason=self.reason(health, penalty),
        )

    def health_penalty(self, health: dict[str, Any]) -> int:
        """Compute an explainable penalty from source health statistics."""
        if not health:
            return 0
        penalty = 0
        penalty += min(int(health.get("http_error_streak") or 0), 5) * 4
        penalty += min(int(health.get("selected_dry_streak") or 0), 5) * 2
        penalty += min(int(health.get("dry_streak") or 0), 5)
        dated_rate = health.get("dated_rate")
        if dated_rate is not None and float(dated_rate) < 0.5:
            penalty += 2
        return penalty

    def reason(self, health: dict[str, Any], penalty: int) -> str:
        if not health:
            return "no prior source health"
        if penalty == 0:
            return "healthy prior source contribution"
        return (
            "penalized by source health: "
            f"http_error_streak={int(health.get('http_error_streak') or 0)}, "
            f"selected_dry_streak={int(health.get('selected_dry_streak') or 0)}, "
            f"dry_streak={int(health.get('dry_streak') or 0)}"
        )


class SourceBudgetPolicy:
    """Apply cost-aware source budgets after priority scoring."""

    def __init__(
        self,
        budget: dict[str, Any] | None = None,
        access_priority: dict[str, int] | None = None,
        access_cost: dict[str, float] | None = None,
    ):
        self.budget = budget or {}
        self.access_priority = dict(DEFAULT_ACCESS_PRIORITY)
        if access_priority:
            self.access_priority.update(access_priority)
        self.access_cost = dict(DEFAULT_ACCESS_COST)
        if access_cost:
            self.access_cost.update({key: float(value) for key, value in access_cost.items()})
        configured_costs = self.budget.get("access_costs", {}) or {}
        self.access_cost.update({key: float(value) for key, value in configured_costs.items()})

    def apply(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return sources that fit the configured acquisition budget."""
        if not self.budget:
            return [dict(source) for source in sources]

        max_sources = self._optional_int("max_sources")
        max_cost = self._optional_float("max_total_cost")
        max_per_access = {
            str(access): int(limit)
            for access, limit in (self.budget.get("max_per_access", {}) or {}).items()
        }
        min_per_access = {
            str(access): int(limit)
            for access, limit in (self.budget.get("min_per_access", {}) or {}).items()
        }

        selected: list[dict[str, Any]] = []
        selected_ids: set[int] = set()
        access_counts: dict[str, int] = {}
        total_cost = 0.0

        def try_add(index: int, source: dict[str, Any]) -> bool:
            nonlocal total_cost
            access = str(source.get("access") or "")
            source_cost = self.source_cost(source)
            if max_sources is not None and len(selected) >= max_sources:
                return False
            if max_cost is not None and total_cost + source_cost > max_cost:
                return False
            if access in max_per_access and access_counts.get(access, 0) >= max_per_access[access]:
                return False
            selected.append(dict(source))
            selected_ids.add(index)
            access_counts[access] = access_counts.get(access, 0) + 1
            total_cost += source_cost
            return True

        for access, minimum in self._ordered_minimums(min_per_access):
            for index, source in enumerate(sources):
                if index in selected_ids or str(source.get("access") or "") != access:
                    continue
                if access_counts.get(access, 0) >= minimum:
                    break
                try_add(index, source)

        for index, source in enumerate(sources):
            if index in selected_ids:
                continue
            try_add(index, source)

        return selected

    def source_cost(self, source: dict[str, Any]) -> float:
        """Return acquisition cost for one source."""
        if "acquisition_cost" in source:
            return float(source["acquisition_cost"])
        access = str(source.get("access") or "")
        return float(self.access_cost.get(access, 1.0))

    def _ordered_minimums(self, minimums: dict[str, int]) -> list[tuple[str, int]]:
        return sorted(
            minimums.items(),
            key=lambda item: (self.access_priority.get(item[0], 100), item[0]),
        )

    def _optional_int(self, key: str) -> int | None:
        value = self.budget.get(key)
        return int(value) if value is not None else None

    def _optional_float(self, key: str) -> float | None:
        value = self.budget.get(key)
        return float(value) if value is not None else None


class AcquisitionPolicy:
    """Own project-level acquisition ordering across report scales."""

    def __init__(self, access_priority: dict[str, int] | None = None):
        self.access_priority = dict(DEFAULT_ACCESS_PRIORITY)
        if access_priority:
            self.access_priority.update(access_priority)
        self.source_scorer = SourcePriorityScorer(self.access_priority)

    def rank_access(self, access: str) -> int:
        """Return the project priority tier for an acquisition access type."""
        return self.access_priority.get(str(access or ""), 100)

    def order_sources(
        self,
        sources: list[dict[str, Any]],
        source_health: dict[str, dict[str, Any]] | None = None,
        source_budget: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return active source definitions in acquisition-priority order."""
        indexed = list(enumerate(sources))
        ordered = sorted(
            indexed,
            key=lambda item: (
                self.source_scorer.score(item[1], source_health).access_tier,
                self.source_scorer.score(item[1], source_health).health_penalty,
                -self.source_scorer.score(item[1], source_health).contribution_score,
                item[0],
            ),
        )
        ordered_sources = [
            self._apply_health_budget_adjustment(dict(source), source_health)
            for _index, source in ordered
        ]
        return SourceBudgetPolicy(
            source_budget,
            access_priority=self.access_priority,
        ).apply(ordered_sources)

    def _apply_health_budget_adjustment(
        self,
        source: dict[str, Any],
        source_health: dict[str, dict[str, Any]] | None,
    ) -> dict[str, Any]:
        source_id = str(source.get("id") or source.get("source") or "")
        health = (source_health or {}).get(source_id, {})
        if not health:
            return source
        max_articles = int(source.get("max_articles") or source.get("max_articles_per_url") or 0)
        selected_rate = float(health.get("selected_rate") or health.get("hit_rate") or 0.0)
        dry_streak = int(health.get("selected_dry_streak") or health.get("dry_streak") or 0)
        if max_articles > 0 and selected_rate >= 0.5 and dry_streak == 0:
            source["max_articles"] = min(max_articles * 2, 50)
            source["budget_reason"] = "expanded by healthy source yield"
        elif max_articles > 1 and dry_streak >= 3:
            source["max_articles"] = max(max_articles // 2, 1)
            source["budget_reason"] = "reduced by repeated dry source health"
        dated_rate = health.get("dated_rate")
        if dated_rate is not None and float(dated_rate) < 0.5 and source.get("access") in {"direct_fetch", "browser"}:
            source["resolve_article_dates"] = True
            source["date_quality_action"] = "detail_fetch_required"
        return source

    def watchlist_steps(self) -> list[AcquisitionStep]:
        """Return the project watchlist priority before broad search."""
        return [
            AcquisitionStep("rss", self.rank_access("rss"), "feed-based sources usually expose dated fresh items"),
            AcquisitionStep("direct_fetch", self.rank_access("direct_fetch"), "URL fetch sources are source-owned evidence"),
            AcquisitionStep("browser", self.rank_access("browser"), "browser fetch handles JS-heavy source-owned pages"),
        ]

    def full_pipeline_steps(self) -> list[AcquisitionStep]:
        """Return the default fresh-evidence acquisition sequence."""
        return [
            *self.watchlist_steps(),
            AcquisitionStep("discovery", self.rank_access("discovery"), "broad engines supplement uncovered watchlist gaps"),
            AcquisitionStep("database", self.rank_access("database"), "persisted memory is synthesized with fresh evidence"),
        ]
