"""Mine rejected source candidates that later became meaningful signals."""

from __future__ import annotations

from typing import Any


def find_missed_signals(
    candidates: list[dict[str, Any]],
    later_records: list[dict[str, Any]],
    *,
    min_overlap: int = 2,
) -> list[dict[str, Any]]:
    """Link rejected candidates to later DB/report records by token overlap."""
    later_index = [
        (record, _tokens(_text(record)))
        for record in later_records
    ]
    misses = []
    for candidate in candidates:
        if candidate.get("accepted") or candidate.get("status") != "reject":
            continue
        candidate_tokens = _tokens(_text(candidate))
        if not candidate_tokens:
            continue
        matches = []
        for record, record_tokens in later_index:
            overlap = sorted(candidate_tokens & record_tokens)
            if len(overlap) >= min_overlap:
                matches.append({
                    "record_id": record.get("id") or record.get("event_id") or record.get("thread_id") or "",
                    "title": record.get("title") or record.get("name") or "",
                    "overlap_terms": overlap,
                    "record_type": record.get("type") or record.get("record_type") or "unknown",
                })
        if matches:
            misses.append({
                "source": candidate.get("source", "unknown"),
                "url": candidate.get("url", ""),
                "title": candidate.get("title", ""),
                "reason": candidate.get("reason", ""),
                "score": candidate.get("score", 0.0),
                "matched_later_records": matches,
            })
    return sorted(misses, key=lambda item: (-len(item["matched_later_records"]), item["source"]))


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(field) or "") for field in ("title", "snippet", "body", "summary"))


def _tokens(text: str) -> set[str]:
    tokens = set()
    for raw in text.lower().replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 3:
            tokens.add(token)
    return tokens
