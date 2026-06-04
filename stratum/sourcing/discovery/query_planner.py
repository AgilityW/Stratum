"""Search query planning algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from stratum.sourcing.discovery.models import normalize_include_domains
from stratum.sourcing.discovery.models import canonicalize_url


@dataclass(frozen=True)
class QueryCoverageDecision:
    """Decision for a query considered against existing higher-priority raw evidence."""

    query_id: str
    include_domains: list[str]
    skipped: bool
    reason: str


@dataclass(frozen=True)
class QuerySelectionDecision:
    """Decision for a query considered against historical performance."""

    query_id: str
    action: str
    recommendation: str
    reason: str


@dataclass(frozen=True)
class QueryPerformance:
    """Historical yield and reliability features for one query."""

    query_id: str
    attempts: int
    successes: int
    no_results: int
    failures: int
    total_results: int
    yield_rate: float
    recommendation: str
    reason: str
    rewrite_hint: str = ""


class QueryPlanner:
    """Plan which search queries should run after higher-priority acquisition."""

    def __init__(self, existing_results: list[dict] | None = None):
        self.existing_results = existing_results or []
        self.covered_domains = covered_domains(self.existing_results)

    def split_covered_queries(self, queries: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split active and skipped domain-scoped queries."""
        active: list[dict] = []
        skipped: list[dict] = []
        for query in queries:
            decision = self.coverage_decision(query)
            if decision.skipped:
                skipped.append(query)
            else:
                active.append(query)
        return active, skipped

    def apply_performance(
        self,
        queries: list[dict],
        performance_records: list[Any] | dict[str, Any] | None = None,
        *,
        retire_low_yield: bool = False,
    ) -> tuple[list[dict], list[dict], list[QuerySelectionDecision]]:
        """Order or optionally retire queries using historical performance."""
        if not performance_records:
            return list(queries), [], [
                QuerySelectionDecision(str(query.get("id", "")), "run", "unknown", "no_history")
                for query in queries
            ]

        performance = performance_by_query(performance_records)
        active: list[tuple[tuple[int, float, int], dict]] = []
        retired: list[dict] = []
        decisions: list[QuerySelectionDecision] = []
        for index, query in enumerate(queries):
            query_id = str(query.get("id", ""))
            record = performance.get(query_id)
            recommendation = str(_field(record, "recommendation", "keep_collecting"))
            reason = str(_field(record, "reason", "no_history"))
            yield_rate = float(_field(record, "yield_rate", 0.0) or 0.0)
            if retire_low_yield and recommendation == "retire_or_rewrite":
                retired.append(query)
                decisions.append(QuerySelectionDecision(query_id, "retire", recommendation, reason))
                continue
            active.append(((recommendation_rank(recommendation), -yield_rate, index), query))
            action = "defer" if recommendation in {"retire_or_rewrite", "expand_or_replace"} else "run"
            decisions.append(QuerySelectionDecision(query_id, action, recommendation, reason))

        active.sort(key=lambda item: item[0])
        return [query for _sort_key, query in active], retired, decisions

    def coverage_decision(self, query: dict) -> QueryCoverageDecision:
        domains = query_include_domains(query)
        skipped = bool(domains) and all(
            domain_is_covered(domain, self.covered_domains)
            for domain in domains
        )
        return QueryCoverageDecision(
            query_id=str(query.get("id", "")),
            include_domains=domains,
            skipped=skipped,
            reason="covered_by_higher_priority_raw" if skipped else "run_search",
        )


class SearchSupplementPolicy:
    """Plan and merge broad Search as a supplement to higher-priority raw evidence."""

    def __init__(self, existing_results: list[dict] | None = None):
        self.existing_results = existing_results or []
        self.query_planner = QueryPlanner(self.existing_results)

    def prepare_queries(
        self,
        queries: list[dict],
        *,
        skip_covered_domain_queries: bool = False,
    ) -> tuple[list[dict], list[dict]]:
        """Return active and skipped queries for supplemental Search execution."""
        if not skip_covered_domain_queries or not self.existing_results:
            return list(queries), []
        return self.query_planner.split_covered_queries(queries)

    def merge_results(self, search_results: list[dict]) -> list[dict]:
        """Merge higher-priority raw evidence before broad Search supplements."""
        merged: list[dict] = []
        seen: set[str] = set()
        for item in [*self.existing_results, *search_results]:
            url = item.get("url", "")
            canonical = item.get("canonical_url") or canonicalize_url(url)
            if not url or canonical in seen:
                continue
            item["canonical_url"] = canonical
            seen.add(canonical)
            merged.append(item)
        return merged

    def skipped_query_stats(self, skipped_queries: list[dict]) -> list[dict]:
        """Build stats rows for queries skipped by higher-priority raw coverage."""
        rows = []
        for query in skipped_queries:
            rows.append({
                "query_id": query.get("id", ""),
                "engine_used": "collector",
                "status": "skipped_covered",
                "results_count": 0,
                "locale": query.get("locale", ""),
                "intent": query.get("intent", "detection"),
                "dimension": query.get("dimension", "general"),
                "query_text": query.get("text", ""),
                "retries": 0,
                "latency_ms": 0.0,
                "error": None,
                "include_domains": query_include_domains(query),
            })
        return rows

    def zero_query_stats_payload(
        self,
        *,
        run_date: str,
        merged_results: list[dict],
        skipped_queries: list[dict],
    ) -> dict[str, Any]:
        """Build raw.stats.json when Search has no active supplement queries."""
        return {
            "date": run_date,
            "total_raw": len(merged_results),
            "total_curated": 0,
            "by_engine": {},
            "by_locale": {},
            "by_source_type": {},
            "diagnostics": {
                "existing_raw": len(self.existing_results),
                "search_raw": 0,
                "skipped_covered_queries": len(skipped_queries),
            },
            "queries": self.skipped_query_stats(skipped_queries),
        }


class QueryPerformanceScorer:
    """Score query history for future pruning, expansion, and diagnostics."""

    def __init__(self, *, min_attempts: int = 3, low_yield_rate: float = 0.25):
        self.min_attempts = min_attempts
        self.low_yield_rate = low_yield_rate

    def score(self, query_stats: list[Any]) -> list[QueryPerformance]:
        """Aggregate query stats into per-query performance records."""
        grouped: dict[str, dict[str, Any]] = {}
        for stat in query_stats:
            query_id = str(_field(stat, "query_id", ""))
            if not query_id:
                continue
            entry = grouped.setdefault(query_id, {
                "query_id": query_id,
                "attempts": 0,
                "successes": 0,
                "no_results": 0,
                "failures": 0,
                "total_results": 0,
            })
            status = str(_field(stat, "status", "unknown"))
            results_count = int(_field(stat, "results_count", 0) or 0)
            entry["attempts"] += 1
            entry["total_results"] += results_count
            if status in {"success", "fallback"} and results_count > 0:
                entry["successes"] += 1
            elif status in {"failed", "rate_limited", "error", "not_configured", "unsupported"}:
                entry["failures"] += 1
            elif status == "no_results" or results_count == 0:
                entry["no_results"] += 1
            else:
                entry["failures"] += 1

        return [
            self._to_performance(entry)
            for entry in sorted(grouped.values(), key=lambda item: item["query_id"])
        ]

    def diagnostics(self, query_stats: list[Any]) -> dict[str, Any]:
        """Return JSON-safe performance diagnostics for raw.stats.json."""
        records = self.score(query_stats)
        return {
            "records": [record.__dict__ for record in records],
            "low_yield_retirement_candidates": [
                record.__dict__
                for record in records
                if record.recommendation == "retire_or_rewrite"
            ],
            "gap_expansion_candidates": [
                record.__dict__
                for record in records
                if record.recommendation == "expand_or_replace"
            ],
        }

    def _to_performance(self, entry: dict[str, Any]) -> QueryPerformance:
        attempts = int(entry["attempts"])
        total_results = int(entry["total_results"])
        yield_rate = round(total_results / max(1, attempts), 3)
        recommendation, reason = self._recommend(
            attempts=attempts,
            successes=int(entry["successes"]),
            no_results=int(entry["no_results"]),
            failures=int(entry["failures"]),
            yield_rate=yield_rate,
        )
        return QueryPerformance(
            query_id=str(entry["query_id"]),
            attempts=attempts,
            successes=int(entry["successes"]),
            no_results=int(entry["no_results"]),
            failures=int(entry["failures"]),
            total_results=total_results,
            yield_rate=yield_rate,
            recommendation=recommendation,
            reason=reason,
            rewrite_hint=rewrite_hint(recommendation, reason),
        )

    def _recommend(
        self,
        *,
        attempts: int,
        successes: int,
        no_results: int,
        failures: int,
        yield_rate: float,
    ) -> tuple[str, str]:
        if attempts < self.min_attempts:
            return "keep_collecting", "insufficient_history"
        if failures >= attempts:
            return "expand_or_replace", "all_attempts_failed"
        if no_results >= attempts:
            return "expand_or_replace", "all_attempts_no_results"
        if successes == 0 or yield_rate < self.low_yield_rate:
            return "retire_or_rewrite", "low_historical_yield"
        return "keep", "healthy_yield"


def covered_domains(existing_results: list[dict]) -> set[str]:
    """Return source domains already covered by higher-priority acquisition."""
    domains = set()
    for item in existing_results:
        domain = item.get("source_domain") or domain_from_url(item.get("url", ""))
        if domain:
            domains.add(str(domain).lower())
    return domains


def domain_is_covered(domain: str, covered: set[str]) -> bool:
    target = str(domain or "").lower().removeprefix("www.").removeprefix("m.")
    return any(source == target or source.endswith(f".{target}") for source in covered)


def query_include_domains(query: dict) -> list[str]:
    domains = query.get("include_domains") or query.get("domains") or []
    return normalize_include_domains(domains)


def performance_by_query(performance_records: list[Any] | dict[str, Any]) -> dict[str, Any]:
    """Normalize query performance records into a query-id map."""
    if isinstance(performance_records, dict):
        if "records" in performance_records:
            performance_records = performance_records.get("records") or []
        else:
            return {str(key): value for key, value in performance_records.items()}
    return {
        str(_field(record, "query_id", "")): record
        for record in performance_records
        if str(_field(record, "query_id", ""))
    }


def recommendation_rank(recommendation: str) -> int:
    """Return execution priority for a historical recommendation."""
    return {
        "keep": 0,
        "keep_collecting": 1,
        "expand_or_replace": 2,
        "retire_or_rewrite": 3,
    }.get(str(recommendation or ""), 1)


def rewrite_hint(recommendation: str, reason: str) -> str:
    """Return a deterministic query rewrite or expansion hint for calibration."""
    if recommendation == "expand_or_replace":
        if reason == "all_attempts_failed":
            return "check_engine_route_or_replace_source_filters"
        return "broaden_terms_or_add_alternate_source_domains"
    if recommendation == "retire_or_rewrite":
        return "rewrite_query_or_retire_after_review"
    if recommendation == "keep_collecting":
        return "collect_more_history_before_changing"
    return ""


def split_queries_by_coverage(
    queries: list[dict],
    existing_results: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Compatibility helper for callers that do not need full planning details."""
    return QueryPlanner(existing_results).split_covered_queries(queries)


def domain_from_url(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def _field(stat: Any, name: str, default: Any = None) -> Any:
    if isinstance(stat, dict):
        return stat.get(name, default)
    return getattr(stat, name, default)
