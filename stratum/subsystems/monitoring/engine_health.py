"""Search engine health scoring algorithms."""

from __future__ import annotations

FAILED_ATTEMPT_STATUSES = {
    "failed",
    "rate_limited",
    "rate_limiter_timeout",
    "not_configured",
    "unsupported",
    "provider_exhausted",
}


class EngineHealthScorer:
    """Aggregate search attempt chains into per-engine health decisions."""

    def score(self, query_stats: list[dict]) -> dict[str, dict]:
        health: dict[str, dict] = {}
        for stat in query_stats:
            attempts = stat.get("engine_attempts") or [legacy_attempt_from_query_stat(stat)]
            for attempt in attempts:
                engine = str(attempt.get("engine") or stat.get("engine_used") or "unknown")
                status = str(attempt.get("status") or stat.get("status") or "unknown")
                entry = health.setdefault(engine, {
                    "engine": engine,
                    "attempts": 0,
                    "successes": 0,
                    "no_results": 0,
                    "failures": 0,
                    "rate_limited": 0,
                    "not_configured": 0,
                    "unsupported": 0,
                    "provider_exhausted": 0,
                    "errors": [],
                })
                self._record_attempt(entry, attempt, status)

        for entry in health.values():
            attempts = max(1, entry["attempts"])
            useful = entry["successes"] + (0.5 * entry["no_results"])
            entry["health_score"] = round(useful / attempts, 3)
            entry["failure_rate"] = round(entry["failures"] / attempts, 3)
            entry["recommendation"] = self.recommend(entry)
        return health

    def _record_attempt(self, entry: dict, attempt: dict, status: str) -> None:
        entry["attempts"] += 1
        if status in {"success", "fallback"}:
            entry["successes"] += 1
        elif status == "no_results":
            entry["no_results"] += 1
        else:
            if status in FAILED_ATTEMPT_STATUSES:
                entry["failures"] += 1
            if status == "rate_limited":
                entry["rate_limited"] += 1
            if status == "not_configured":
                entry["not_configured"] += 1
            if status == "unsupported":
                entry["unsupported"] += 1
            if status == "provider_exhausted":
                entry["provider_exhausted"] += 1
        error = attempt.get("error")
        if error and error not in entry["errors"]:
            entry["errors"].append(str(error))

    def recommend(self, entry: dict) -> str:
        if (
            entry.get("provider_exhausted", 0)
            or entry["not_configured"] == entry["attempts"]
            or entry["health_score"] == 0
        ):
            return "avoid"
        if entry["rate_limited"] or entry["failure_rate"] >= 0.5:
            return "deprioritize"
        if entry["health_score"] < 0.75:
            return "watch"
        return "healthy"


def score_search_engine_health(query_stats: list[dict]) -> dict[str, dict]:
    """Aggregate per-engine health from Search query stats attempt chains."""
    return EngineHealthScorer().score(query_stats)


def legacy_attempt_from_query_stat(stat: dict) -> dict:
    return {
        "engine": stat.get("engine_used") or "unknown",
        "status": stat.get("status") or "unknown",
        "error": stat.get("error"),
        "results_count": stat.get("results_count", 0),
    }
