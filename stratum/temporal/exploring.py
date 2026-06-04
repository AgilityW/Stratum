"""Same-scale evidence exploring for temporal reports."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from stratum.orchestrator.watchlist_runtime import run_watchlist
from stratum.db.persistence import upsert_articles
from stratum.temporal.integration import Integration
from stratum.temporal.profiles import get_timescale_profile


@dataclass(frozen=True)
class ExploringDecision:
    """Execution plan for same-scale fresh evidence exploring."""

    timescale: str
    should_explore: bool
    stale_days: int
    reason: str
    nonblocking: bool = True

    def to_dict(self) -> dict:
        return {
            "timescale": self.timescale,
            "should_explore": self.should_explore,
            "stale_days": self.stale_days,
            "reason": self.reason,
            "nonblocking": self.nonblocking,
        }


class Exploring:
    """Describe how a report scale acquires same-scale fresh evidence."""

    def enabled_for(self, timescale: str) -> bool:
        return get_timescale_profile(timescale).consumes_same_scale_fresh_evidence

    def stale_days(self, report_window) -> int:
        return _inclusive_days(report_window.start_date, report_window.end_date)

    def plan(self, timescale: str, report_window) -> ExploringDecision:
        stale_days = self.stale_days(report_window)
        if not self.enabled_for(timescale):
            return ExploringDecision(
                timescale=timescale,
                should_explore=False,
                stale_days=stale_days,
                reason=f"same-scale fresh evidence exploration is not enabled for {timescale}",
            )
        return ExploringDecision(
            timescale=timescale,
            should_explore=True,
            stale_days=stale_days,
            reason="same-scale fresh evidence exploring is required for this temporal profile",
        )

    def decide(self, timescale: str, report_window) -> ExploringDecision:
        return self.plan(timescale, report_window)


_EXPLORING = Exploring()
_INTEGRATION = Integration(_EXPLORING)


def run_exploring(
    domain_id: str,
    timescale: str,
    period: str,
    report_window,
    paths: dict[str, str],
    config_path: str,
    db_dir: str,
    services,
    record: Callable[[str, str, str | None, str | None], None],
) -> dict[str, Any]:
    """Search, verify, normalize, and persist same-scale fresh evidence.

    Exploring is best-effort. A failed network/API stage should not prevent
    DB-native synthesis from using already persisted lower-scale state.
    """
    exploring_plan = _EXPLORING.plan(timescale, report_window)
    if not exploring_plan.should_explore:
        record("exploring", "skipped", paths.get("articles"), f"not enabled for {timescale}")
        return _with_integration(
            timescale,
            {"status": "skipped", "articles": 0, "integration_point": "not_applicable"},
        )

    start_date = report_window.start_date
    end_date = report_window.end_date
    stale_days = exploring_plan.stale_days
    db_path = os.path.join(db_dir, domain_id, f"{domain_id}.db")
    queries_path = os.path.join(services.domains_dir, domain_id, "queries.yaml")
    workspace = os.path.dirname(services.domains_dir)

    watchlist_status = run_watchlist(
        domain_id,
        workspace,
        end_date,
        paths["raw"],
        paths.get("health_data_dir"),
        merge_existing=False,
    )

    search_args = [
        "--domain", domain_id,
        "--date", end_date,
        "--start-date", start_date,
        "--end-date", end_date,
        "--config", config_path,
        "--workspace", workspace,
        "--queries", queries_path,
        "--output", paths["raw"],
        "--stats", paths["search_stats"],
        "--existing-raw", paths["raw"],
        "--skip-covered-domain-queries",
    ]
    if os.path.exists(db_path):
        search_args.extend(["--db", db_path])

    if not services.run_stage("acquisition", search_args, f"Exploring acquisition ({timescale})", timeout=180):
        record("exploring", "failed_nonblocking", paths["raw"], "acquisition failed")
        return _with_integration(
            timescale,
            {"status": "failed_nonblocking", "articles": 0, "integration_point": "not_reached"},
        )
    if _all_search_queries_failed(paths["search_stats"]):
        record("exploring", "failed_nonblocking", paths["search_stats"], "all search queries failed")
        return _with_integration(
            timescale,
            {"status": "failed_nonblocking", "articles": 0, "integration_point": "not_reached"},
        )

    if not services.run_stage("enrich", [
        "--input", paths["raw"],
        "--output", paths["enriched"],
        "--date", end_date,
    ], f"Exploring enrich ({timescale})"):
        record("exploring", "failed_nonblocking", paths["enriched"], "enrich failed")
        return _with_integration(
            timescale,
            {"status": "failed_nonblocking", "articles": 0, "integration_point": "not_reached"},
        )

    if not services.run_stage("verify", [
        "--input", paths["enriched"],
        "--output", paths["verified"],
        "--stats", paths["verify_stats"],
        "--date", end_date,
        "--domain", paths["domain_config"],
        "--stale-days", str(stale_days),
    ], f"Exploring verify ({timescale})"):
        record("exploring", "failed_nonblocking", paths["verified"], "verify failed")
        return _with_integration(
            timescale,
            {"status": "failed_nonblocking", "articles": 0, "integration_point": "not_reached"},
        )

    if not services.run_stage("normalize", [
        "--input", paths["verified"],
        "--output", paths["articles"],
        "--domain", paths["domain_config"],
    ], f"Exploring normalize ({timescale})"):
        record("exploring", "failed_nonblocking", paths["articles"], "normalize failed")
        return _with_integration(
            timescale,
            {"status": "failed_nonblocking", "articles": 0, "integration_point": "not_reached"},
        )

    os.environ["STRATUM_DB_DIR"] = db_dir
    articles = _load_jsonl(paths["articles"])
    count = upsert_articles(
        domain_id,
        articles,
        period,
        artifact_path=paths["articles"],
        scale=timescale,
    )
    record("exploring", "success", paths["articles"], f"articles={count}")
    result = {
        "status": "success",
        "articles": count,
        "pipeline": ["watchlist", "acquisition", "enrich", "verify", "normalize", "db_persist"],
        "watchlist_status": watchlist_status.get("status", "unknown"),
        "integration_point": "after_normalize_db_persist_before_db_synthesis",
    }
    return _with_integration(timescale, result)


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _with_integration(timescale: str, result: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(result)
    enriched["integration"] = _INTEGRATION.decide(timescale, enriched).to_dict()
    return enriched


def _inclusive_days(start_date: str, end_date: str) -> int:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return max((end - start).days + 1, 1)


def _all_search_queries_failed(stats_path: str) -> bool:
    if not os.path.exists(stats_path):
        return False
    with open(stats_path) as f:
        stats = json.load(f)
    queries = stats.get("queries") or []
    if not queries:
        return False
    total_raw = int(stats.get("total_raw") or 0)
    return total_raw == 0 and all(query.get("status") == "failed" for query in queries)
