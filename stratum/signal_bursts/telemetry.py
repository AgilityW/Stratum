"""Term telemetry stage for signal burst detection."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from .terms import match_terms


TEXT_FIELDS = ("title", "snippet", "description", "summary", "body", "name")


def compute_term_telemetry(
    records_by_layer: dict[str, list[dict[str, Any]]],
    db_context: dict[str, list[dict[str, Any]]] | None,
    terms: list[dict[str, Any]],
    *,
    run_date: str | None = None,
) -> dict[str, Any]:
    """Count term hits across SourceTrace layers and DB context."""
    db_context = db_context or {}
    db_context_available = any(bool(records) for records in db_context.values())
    telemetry_mode = "context_aware" if db_context_available else "acquisition_only"
    rows: dict[str, dict[str, Any]] = {
        term["id"]: _empty_term(term, telemetry_mode=telemetry_mode, db_context_available=db_context_available)
        for term in terms
    }
    matched_records = []

    for layer, records in records_by_layer.items():
        for record in records:
            hits = match_terms(_record_text(record), terms)
            if not hits:
                continue
            matched_records.append(_matched_record(layer, record, hits))
            for term_id in hits:
                _add_hit(rows[term_id], layer, record, run_date=run_date)

    for db_layer, records in db_context.items():
        for record in records:
            hits = match_terms(_record_text(record), terms)
            if not hits:
                continue
            layer = f"db_{db_layer}"
            matched_records.append(_matched_record(layer, record, hits))
            for term_id in hits:
                _add_hit(rows[term_id], layer, record, run_date=run_date)

    telemetry = [_finalize(row) for row in rows.values()]
    return {
        "telemetry_mode": telemetry_mode,
        "db_context_available": db_context_available,
        "terms": sorted(telemetry, key=lambda item: (-item["weighted_count"], item["term"])),
        "matched_records": matched_records,
        "totals": {
            "terms": len(terms),
            "matched_terms": sum(1 for row in telemetry if row["total_count"] > 0),
            "matched_records": len(matched_records),
            "db_records": sum(len(records) for records in db_context.values()) if db_context_available else 0,
        },
    }


def _empty_term(
    term: dict[str, Any],
    *,
    telemetry_mode: str,
    db_context_available: bool,
) -> dict[str, Any]:
    return {
        "term": term["id"],
        "label": term.get("label", term["id"]),
        "telemetry_mode": telemetry_mode,
        "db_context_available": db_context_available,
        "total_count": 0,
        "weighted_count": 0.0,
        "layer_counts": defaultdict(int),
        "sources": set(),
        "engines": set(),
        "official_count": 0,
        "fresh_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "raw_count": 0,
        "db_count": 0,
        "event_count": 0,
        "thread_count": 0,
        "report_item_count": 0,
        "judgment_count": 0,
    }


def _add_hit(row: dict[str, Any], layer: str, record: dict[str, Any], *, run_date: str | None) -> None:
    row["total_count"] += 1
    row["weighted_count"] += _layer_weight(layer)
    row["layer_counts"][layer] += 1
    row["sources"].add(_source(record))
    engine = str(record.get("engine") or "")
    if engine:
        row["engines"].add(engine)
    if str(record.get("source_type_hint") or "").lower() == "official":
        row["official_count"] += 1
    if _is_fresh(record, run_date):
        row["fresh_count"] += 1
    status = str(record.get("status") or record.get("query_dimension") or "")
    if record.get("accepted") or record.get("selected") or status in {"accept", "weak_signal", "selected"}:
        row["accepted_count"] += 1
    if status in {"reject", "rejected"} or record.get("accepted") is False:
        row["rejected_count"] += 1
    if layer == "raw":
        row["raw_count"] += 1
    if layer.startswith("db_"):
        row["db_count"] += 1
        if layer == "db_events":
            row["event_count"] += 1
        elif layer == "db_threads":
            row["thread_count"] += 1
        elif layer == "db_report_items":
            row["report_item_count"] += 1
        elif layer == "db_judgments":
            row["judgment_count"] += 1


def _finalize(row: dict[str, Any]) -> dict[str, Any]:
    total = max(row["total_count"], 1)
    return {
        "term": row["term"],
        "label": row["label"],
        "telemetry_mode": row["telemetry_mode"],
        "db_context_available": row["db_context_available"],
        "total_count": row["total_count"],
        "weighted_count": round(row["weighted_count"], 4),
        "layer_counts": dict(sorted(row["layer_counts"].items())),
        "source_count": len(row["sources"]),
        "sources": sorted(row["sources"]),
        "engine_count": len(row["engines"]),
        "engines": sorted(row["engines"]),
        "official_count": row["official_count"],
        "fresh_count": row["fresh_count"],
        "accepted_count": row["accepted_count"],
        "rejected_count": row["rejected_count"],
        "raw_count": row["raw_count"],
        "db_count": row["db_count"],
        "event_count": row["event_count"],
        "thread_count": row["thread_count"],
        "report_item_count": row["report_item_count"],
        "judgment_count": row["judgment_count"],
        "acceptance_rate": round(row["accepted_count"] / total, 4),
    }


def _matched_record(layer: str, record: dict[str, Any], hits: list[str]) -> dict[str, Any]:
    return {
        "layer": layer,
        "terms": sorted(hits),
        "url": record.get("canonical_url") or record.get("url") or "",
        "title": record.get("title") or record.get("name") or "",
        "source": _source(record),
        "engine": record.get("engine", ""),
        "published_at": record.get("published_at") or record.get("datePublished") or record.get("date") or "",
        "source_type_hint": record.get("source_type_hint", ""),
        "status": record.get("status") or record.get("query_dimension") or "",
    }


def _record_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(field) or "") for field in TEXT_FIELDS)


def _source(record: dict[str, Any]) -> str:
    source = str(record.get("source") or "")
    if source:
        return source
    engine = str(record.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(record.get("source_domain") or "unknown")


def _layer_weight(layer: str) -> float:
    if layer.endswith("observations"):
        return 0.5
    if layer.endswith("candidates"):
        return 0.8
    if layer == "watchlist_results":
        return 1.0
    if layer == "raw":
        return 1.2
    if layer.startswith("db_events") or layer.startswith("db_threads"):
        return 1.5
    if layer.startswith("db_report"):
        return 1.7
    return 1.0


def _is_fresh(record: dict[str, Any], run_date: str | None) -> bool:
    if not run_date:
        return False
    value = record.get("published_at") or record.get("datePublished") or record.get("date")
    if not value:
        return False
    try:
        current = datetime.fromisoformat(run_date[:10]).date()
        published = datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return False
    return (current - published).days <= 2
