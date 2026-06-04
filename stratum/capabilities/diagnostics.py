"""Capability wrappers for collection and discovery diagnostics."""

from __future__ import annotations

from typing import Any

from stratum.sourcing.discovery import build_diagnostics
from stratum.sourcing.discovery.config import load_search_config
from stratum.sourcing.discovery.models import Query, QueryStats, SearchResult
from stratum.sourcing.watchlist.source_expansion import evaluate_source_expansion


def discovery_diagnostics(
    *,
    domain: str,
    workspace: str,
    queries: list[dict[str, Any]],
    raw_results: list[dict[str, Any]],
    curated_results: list[dict[str, Any]],
    query_stats: list[dict[str, Any]],
    config_path: str | None = None,
) -> dict[str, Any]:
    """Build deterministic discovery diagnostics from explicit search payloads."""
    config = load_search_config(domain, workspace, config_path=config_path)
    return build_diagnostics(
        queries=[_query(item) for item in queries],
        raw_results=[_result(item) for item in raw_results],
        curated_results=[_result(item) for item in curated_results],
        query_stats=[_query_stats(item) for item in query_stats],
        config=config,
    )


def source_expansion(*, run_data_dir: str) -> dict[str, Any]:
    """Evaluate watchlist source-expansion signals from one completed run."""
    return evaluate_source_expansion(run_data_dir)


def _query(value: dict[str, Any] | Query) -> Query:
    if isinstance(value, Query):
        return value
    return Query(
        id=str(value["id"]),
        text=str(value["text"]),
        locale=str(value["locale"]),
        intent=str(value.get("intent") or "detection"),
        dimension=str(value.get("dimension") or "general"),
        include_domains=list(value.get("include_domains") or []),
    )


def _result(value: dict[str, Any] | SearchResult) -> SearchResult:
    if isinstance(value, SearchResult):
        return value
    result = SearchResult(
        url=str(value.get("url") or value.get("canonical_url") or ""),
        title=str(value.get("title") or ""),
        snippet=str(value.get("snippet") or value.get("description") or ""),
        locale=str(value.get("locale") or "unknown"),
        published_at=value.get("published_at") or value.get("datePublished"),
        source_domain=str(value.get("source_domain") or ""),
        source_type_hint=str(value.get("source_type_hint") or "media"),
        engine=str(value.get("engine") or ""),
        query_id=str(value.get("query_id") or value.get("query_used") or ""),
        query_dimension=str(value.get("query_dimension") or "general"),
        score=float(value.get("score") or 0.0),
        canonical_url=str(value.get("canonical_url") or ""),
    )
    if not result.source_domain or not result.canonical_url:
        result = result.with_domain()
    return result


def _query_stats(value: dict[str, Any] | QueryStats) -> QueryStats:
    if isinstance(value, QueryStats):
        return value
    return QueryStats(
        query_id=str(value["query_id"]),
        engine_used=str(value.get("engine_used") or ""),
        status=str(value.get("status") or "unknown"),
        results_count=int(value.get("results_count") or 0),
        locale=str(value.get("locale") or ""),
        intent=str(value.get("intent") or ""),
        dimension=str(value.get("dimension") or "general"),
        query_text=str(value.get("query_text") or ""),
        include_domains=list(value.get("include_domains") or []),
        retries=int(value.get("retries") or 0),
        latency_ms=float(value.get("latency_ms") or 0.0),
        error=value.get("error"),
        engine_attempts=list(value.get("engine_attempts") or []),
    )
