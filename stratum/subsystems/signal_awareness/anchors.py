"""Conference-anchor normalization and evidence matching."""

from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any


EVENT_CLUES = {
    "booth",
    "keynote",
    "preview",
    "expected",
    "expect",
    "agenda",
    "exhibitor",
    "summit",
    "conference",
    "expo",
    "forum",
    "live coverage",
    "trade show",
}


def normalize_anchor_registry(anchors: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize signal anchors provided by callers."""
    normalized: list[dict[str, Any]] = []
    for raw in anchors or []:
        name = str(raw.get("name") or raw.get("id") or "").strip()
        if not name:
            continue
        aliases = sorted({
            _normalize_text(name),
            *(_normalize_text(str(alias)) for alias in raw.get("aliases", []) if alias),
        })
        locations = sorted({
            _normalize_text(str(location))
            for location in raw.get("locations", []) or raw.get("location_aliases", [])
            if location
        })
        normalized.append({
            "id": str(raw.get("id") or _slug(name)),
            "name": name,
            "aliases": aliases,
            "topics": list(raw.get("topics", []) or raw.get("domains", []) or []),
            "locations": locations,
            "start_date": raw.get("start_date"),
            "end_date": raw.get("end_date"),
            "lead_days": int(raw.get("lead_days", 14)),
            "teardown_days": int(raw.get("teardown_days", 3)),
            "query_terms": list(raw.get("query_terms", []) or []),
            "temporary_sources": list(raw.get("temporary_sources", []) or []),
            "direct_fetch_targets": list(raw.get("direct_fetch_targets", []) or []),
            "daily_target_min": int(raw.get("daily_target_min", 16)),
            "daily_target_max": int(raw.get("daily_target_max", 24)),
            "min_mentions": int(raw.get("min_mentions", 2)),
        })
    return normalized


def summarize_anchor_mentions(
    records: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    *,
    run_date: str | None,
) -> list[dict[str, Any]]:
    """Summarize anchor-level evidence, coherence, and detection readiness."""
    summary: list[dict[str, Any]] = []
    for anchor in anchors:
        matching_records: list[dict[str, Any]] = []
        location_hits = 0
        event_clue_hits = 0
        official_hits = 0
        companies: set[str] = set()
        sources: set[str] = set()
        year_hits = 0
        year_tokens = _anchor_year_tokens(anchor, run_date)
        for record in records:
            text = _record_text(record)
            if not any(alias in text for alias in anchor["aliases"]):
                continue
            matching_records.append(record)
            sources.add(str(record.get("source") or record.get("source_domain") or "unknown"))
            if any(location in text for location in anchor["locations"]):
                location_hits += 1
            if any(clue in text for clue in EVENT_CLUES):
                event_clue_hits += 1
            if record.get("source_type_hint") == "official":
                official_hits += 1
            companies.update(_extract_companies(record))
            if any(token and token in text for token in year_tokens):
                year_hits += 1
        mention_count = len(matching_records)
        source_count = len(sources)
        company_diversity = len(companies)
        mention_score = min(1.0, mention_count / max(anchor["min_mentions"], 1))
        coherence_score = 0.0
        if mention_count:
            coherence_score = (
                (location_hits / mention_count) * 0.35
                + (event_clue_hits / mention_count) * 0.35
                + (year_hits / mention_count) * 0.20
                + (1.0 if official_hits else 0.0) * 0.10
            )
        diversity_score = min(1.0, company_diversity / 3.0)
        source_diversity_score = min(1.0, source_count / 3.0)
        confidence = min(
            1.0,
            mention_score * 0.40
            + coherence_score * 0.35
            + diversity_score * 0.15
            + source_diversity_score * 0.10,
        )
        detected = (
            mention_count >= anchor["min_mentions"]
            and (coherence_score >= 0.25 or official_hits > 0)
            and confidence >= 0.45
        )
        summary.append({
            "anchor_id": anchor["id"],
            "anchor_name": anchor["name"],
            "topics": anchor["topics"],
            "mention_count": mention_count,
            "source_count": source_count,
            "company_diversity": company_diversity,
            "official_hits": official_hits,
            "location_hits": location_hits,
            "event_clue_hits": event_clue_hits,
            "year_hits": year_hits,
            "coherence_score": round(coherence_score, 4),
            "confidence": round(confidence, 4),
            "detected": detected,
            "window_status": _window_status(anchor, run_date),
            "representative_titles": [record.get("title", "") for record in matching_records[:5]],
            "temporary_sources": anchor["temporary_sources"],
            "direct_fetch_targets": anchor["direct_fetch_targets"],
            "query_terms": anchor["query_terms"],
            "daily_target_min": anchor["daily_target_min"],
            "daily_target_max": anchor["daily_target_max"],
        })
    return summary


def _window_status(anchor: dict[str, Any], run_date: str | None) -> str:
    if not run_date or not anchor.get("start_date"):
        return "none"
    current = date.fromisoformat(run_date)
    start = date.fromisoformat(anchor["start_date"])
    end = date.fromisoformat(anchor.get("end_date") or anchor["start_date"])
    lead_start = start - timedelta(days=anchor["lead_days"])
    teardown_end = end + timedelta(days=anchor["teardown_days"])
    if lead_start <= current < start:
        return "lead_window"
    if start <= current <= end:
        return "live_window"
    if end < current <= teardown_end:
        return "teardown_window"
    return "none"


def _anchor_year_tokens(anchor: dict[str, Any], run_date: str | None) -> set[str]:
    tokens: set[str] = set()
    if anchor.get("start_date"):
        year = date.fromisoformat(anchor["start_date"]).year
        tokens.add(str(year))
    if run_date:
        tokens.add(str(date.fromisoformat(run_date).year))
    return tokens


def _extract_companies(record: dict[str, Any]) -> set[str]:
    companies: set[str] = set()
    for key in ("company", "vendor", "entity", "brand"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            companies.add(value.strip().lower())
    for value in record.get("entities", []) or []:
        if isinstance(value, str) and value.strip():
            companies.add(value.strip().lower())
    return companies


def _record_text(record: dict[str, Any]) -> str:
    parts = [
        record.get("title", ""),
        record.get("snippet", ""),
        record.get("description", ""),
        record.get("summary", ""),
    ]
    return _normalize_text(" ".join(str(part) for part in parts if part))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "anchor"
