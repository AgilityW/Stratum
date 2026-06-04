"""Cross-layer evidence lifecycle conversion traces."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_conversion_trace(
    watchlist_observations: list[dict[str, Any]],
    discovery_observations: list[dict[str, Any]],
    watchlist_candidates: list[dict[str, Any]],
    discovery_candidates: list[dict[str, Any]],
    watchlist_results: list[dict[str, Any]],
    raw_results: list[dict[str, Any]],
    *,
    db_context: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Join observation, candidate, result, raw, and optional DB layers."""
    db_context = db_context or {}
    traces: dict[str, dict[str, Any]] = defaultdict(_empty_trace)

    _mark(traces, watchlist_observations, "watchlist_observed")
    _mark(traces, discovery_observations, "discovery_observed")
    _mark_candidates(traces, watchlist_candidates, "watchlist_candidate")
    _mark_candidates(traces, discovery_candidates, "discovery_candidate")
    _mark(traces, watchlist_results, "watchlist_result")
    _mark(traces, raw_results, "raw_consumed")
    _mark(traces, db_context.get("articles", []), "article")
    _mark(traces, db_context.get("persisted_articles", []), "persisted")

    rows = []
    for canonical, trace in traces.items():
        trace["canonical_url"] = canonical
        trace["miss_type"] = _miss_type(trace)
        rows.append(trace)
    return {
        "items": sorted(rows, key=lambda item: item["canonical_url"]),
        "totals": _totals(rows),
    }


def _empty_trace() -> dict[str, Any]:
    return {
        "canonical_url": "",
        "title": "",
        "sources": set(),
        "watchlist_observed": False,
        "discovery_observed": False,
        "watchlist_candidate": False,
        "discovery_candidate": False,
        "candidate_statuses": set(),
        "watchlist_result": False,
        "raw_consumed": False,
        "article": False,
        "persisted": False,
    }


def _mark(traces: dict[str, dict[str, Any]], records: list[dict[str, Any]], field: str) -> None:
    for record in records:
        canonical = _canonical(record)
        if not canonical:
            continue
        trace = traces[canonical]
        trace[field] = True
        trace["title"] = trace["title"] or str(record.get("title") or "")
        trace["sources"].add(str(record.get("source") or record.get("source_domain") or "unknown"))


def _mark_candidates(
    traces: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    field: str,
) -> None:
    for record in records:
        canonical = _canonical(record)
        if not canonical:
            continue
        trace = traces[canonical]
        trace[field] = True
        trace["title"] = trace["title"] or str(record.get("title") or "")
        trace["sources"].add(str(record.get("source") or record.get("source_domain") or "unknown"))
        trace["candidate_statuses"].add(str(record.get("status") or "unknown"))


def _miss_type(trace: dict[str, Any]) -> str:
    observed = trace["watchlist_observed"] or trace["discovery_observed"]
    judged = trace["watchlist_candidate"] or trace["discovery_candidate"]
    consumed = trace["raw_consumed"]
    later = trace["article"] or trace["persisted"]
    if observed and not judged and later:
        return "unjudged_miss"
    if judged and not consumed and later:
        return "rejected_or_pruned_miss"
    if consumed and not later:
        return "downstream_drop"
    return ""


def _totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "items": len(rows),
        "observed": sum(1 for row in rows if row["watchlist_observed"] or row["discovery_observed"]),
        "judged": sum(1 for row in rows if row["watchlist_candidate"] or row["discovery_candidate"]),
        "consumed": sum(1 for row in rows if row["raw_consumed"]),
        "persisted": sum(1 for row in rows if row["persisted"]),
        "unjudged_misses": sum(1 for row in rows if row["miss_type"] == "unjudged_miss"),
        "rejected_or_pruned_misses": sum(1 for row in rows if row["miss_type"] == "rejected_or_pruned_miss"),
    }


def _canonical(record: dict[str, Any]) -> str:
    return str(record.get("canonical_url") or record.get("url") or record.get("article_url") or "")
