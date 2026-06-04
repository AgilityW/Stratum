"""Temporal source profiles for freshness, delay, and decay analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import mean
from typing import Any


def build_temporal_profile(records: list[dict[str, Any]], *, run_date: str | None = None) -> dict[str, Any]:
    """Build source-level timing profiles from candidate/article records."""
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        rows[_source(record)].append(record)

    profiles = []
    for source, source_records in sorted(rows.items()):
        ages = [
            _age_days(record, run_date)
            for record in source_records
            if _age_days(record, run_date) is not None
        ]
        dated = len(ages)
        profiles.append({
            "source": source,
            "records": len(source_records),
            "dated": dated,
            "dated_rate": round(dated / max(len(source_records), 1), 4),
            "average_age_days": round(mean(ages), 2) if ages else None,
            "fresh_records": sum(1 for age in ages if age <= 2),
            "stale_records": sum(1 for age in ages if age > 14),
            "temporal_tier": _temporal_tier(ages),
        })
    return {"sources": profiles}


def _age_days(record: dict[str, Any], run_date: str | None) -> int | None:
    published = _parse_date(record.get("published_at") or record.get("datePublished") or record.get("date"))
    current = _parse_date(run_date) if run_date else date.today()
    if not published or not current:
        return None
    return (current - published).days


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _temporal_tier(ages: list[int]) -> str:
    if not ages:
        return "undated"
    avg = mean(ages)
    if avg <= 2:
        return "fast"
    if avg <= 7:
        return "current"
    if avg <= 30:
        return "slow"
    return "archive"


def _source(item: dict[str, Any]) -> str:
    engine = str(item.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(item.get("source") or item.get("source_domain") or "unknown")
