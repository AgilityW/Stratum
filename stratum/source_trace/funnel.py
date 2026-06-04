"""SourceTrace funnel metrics from seen candidates to persisted evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def build_funnel(
    candidates: list[dict[str, Any]],
    watchlist_results: list[dict[str, Any]],
    raw_results: list[dict[str, Any]],
    *,
    verified_articles: list[dict[str, Any]] | None = None,
    normalized_articles: list[dict[str, Any]] | None = None,
    report_evidence: list[dict[str, Any]] | None = None,
    persisted_articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build per-source and total conversion metrics.

    The funnel accepts optional downstream DB/read-model records. Missing
    downstream layers simply stay at zero, so the same function works during
    early daily runs and after DB ingest.
    """
    verified_articles = verified_articles or []
    normalized_articles = normalized_articles or []
    report_evidence = report_evidence or []
    persisted_articles = persisted_articles or []

    rows: dict[str, dict[str, Any]] = defaultdict(_empty_row)
    canonical_to_sources: dict[str, set[str]] = defaultdict(set)

    for item in candidates:
        source = _source(item)
        row = rows[source]
        row["seen"] += 1
        status = str(item.get("status") or "")
        if item.get("accepted") or status in {"accept", "weak_signal"}:
            row["admitted"] += 1
        if status == "weak_signal":
            row["weak_signals"] += 1
        if status == "reject":
            row["rejected"] += 1
        canonical = _canonical(item)
        if canonical:
            canonical_to_sources[canonical].add(source)

    for item in watchlist_results:
        source = _source(item)
        rows[source]["watchlist_results"] += 1
        canonical = _canonical(item)
        if canonical:
            canonical_to_sources[canonical].add(source)

    for item in raw_results:
        canonical = _canonical(item)
        sources = canonical_to_sources.get(canonical) or {_source(item)}
        for source in sources:
            rows[source]["consumed"] += 1

    _count_downstream(rows, verified_articles, canonical_to_sources, "verified")
    _count_downstream(rows, normalized_articles, canonical_to_sources, "normalized")
    _count_downstream(rows, report_evidence, canonical_to_sources, "reported")
    _count_downstream(rows, persisted_articles, canonical_to_sources, "persisted")

    source_rows = [_finalize_row(source, row) for source, row in sorted(rows.items())]
    return {
        "sources": source_rows,
        "totals": _totals(source_rows),
    }


def _empty_row() -> dict[str, Any]:
    return {
        "seen": 0,
        "admitted": 0,
        "weak_signals": 0,
        "rejected": 0,
        "watchlist_results": 0,
        "consumed": 0,
        "verified": 0,
        "normalized": 0,
        "reported": 0,
        "persisted": 0,
    }


def _count_downstream(
    rows: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    canonical_to_sources: dict[str, set[str]],
    field: str,
) -> None:
    for item in records:
        canonical = _canonical(item)
        sources = canonical_to_sources.get(canonical) or {_source(item)}
        for source in sources:
            rows[source][field] += 1


def _finalize_row(source: str, row: dict[str, Any]) -> dict[str, Any]:
    out = {"source": source, **row}
    seen = max(out["seen"], 1)
    admitted = max(out["admitted"], 1)
    consumed = max(out["consumed"], 1)
    out["admission_rate"] = round(out["admitted"] / seen, 4)
    out["reject_rate"] = round(out["rejected"] / seen, 4)
    out["consumption_rate"] = round(out["consumed"] / admitted, 4)
    out["verified_rate"] = round(out["verified"] / consumed, 4)
    out["report_rate"] = round(out["reported"] / consumed, 4)
    return out


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "seen",
        "admitted",
        "weak_signals",
        "rejected",
        "watchlist_results",
        "consumed",
        "verified",
        "normalized",
        "reported",
        "persisted",
    )
    total = {field: sum(int(row.get(field, 0) or 0) for row in rows) for field in fields}
    total["source_count"] = len(rows)
    return total


def _source(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "")
    if source:
        return source
    engine = str(item.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(item.get("source_domain") or item.get("domain") or "unknown")


def _canonical(item: dict[str, Any]) -> str:
    value = str(item.get("canonical_url") or item.get("url") or item.get("article_url") or "")
    if not value:
        return ""
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = urlencode([
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ])
    return urlunparse((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", "", query, ""))
