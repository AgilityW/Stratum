"""Link signal bursts to DB events, threads, judgments, and report items."""

from __future__ import annotations

from typing import Any

from .terms import match_terms


def link_db_context(candidate: dict[str, Any], db_context: dict[str, list[dict[str, Any]]], normalized_terms: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach DB context records that contain candidate terms."""
    candidate_terms = set(candidate.get("terms", []))
    links = {
        "threads": _matches(db_context.get("threads", []), candidate_terms, normalized_terms),
        "events": _matches(db_context.get("events", []), candidate_terms, normalized_terms),
        "judgments": _matches(db_context.get("judgments", []), candidate_terms, normalized_terms),
        "report_items": _matches(db_context.get("report_items", []), candidate_terms, normalized_terms),
    }
    links["db_relevance_score"] = min(1.0, 0.15 * sum(len(value) for value in links.values() if isinstance(value, list)))
    return links


def _matches(records: list[dict[str, Any]], candidate_terms: set[str], normalized_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched = []
    for record in records:
        hits = set(match_terms(_text(record), normalized_terms))
        if not hits.intersection(candidate_terms):
            continue
        matched.append({
            "id": record.get("id") or record.get("thread_id") or record.get("event_id") or record.get("item_id") or "",
            "title": record.get("title") or record.get("name") or "",
            "matched_terms": sorted(hits.intersection(candidate_terms)),
            "status": record.get("status") or record.get("state") or "",
        })
        if len(matched) >= 5:
            break
    return matched


def _text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(field) or "") for field in ("title", "name", "summary", "body", "description"))
