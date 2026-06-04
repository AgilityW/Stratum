"""Topic normalization and record classification for signal awareness."""

from __future__ import annotations

import re
from typing import Any


def normalize_topic_rules(topic_rules: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize caller-provided topic rules into a stable internal shape."""
    normalized: list[dict[str, Any]] = []
    for raw in topic_rules or []:
        if isinstance(raw, str):
            normalized.append({
                "id": _slug(raw),
                "label": raw,
                "keywords": sorted({_normalize_text(raw)}),
            })
            continue
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("id") or raw.get("topic") or "").strip()
        if not label:
            continue
        keywords: set[str] = set()
        for value in raw.get("keywords", []):
            if value:
                keywords.add(_normalize_text(str(value)))
        for value in raw.get("aliases", []):
            if value:
                keywords.add(_normalize_text(str(value)))
        keywords.add(_normalize_text(label))
        normalized.append({
            "id": _slug(str(raw.get("id") or label)),
            "label": label,
            "keywords": sorted(keyword for keyword in keywords if keyword),
        })
    return normalized


def classify_records_by_topic(
    records: list[dict[str, Any]],
    topic_rules: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Return per-topic counts and records annotated with matched topic ids."""
    counts = {rule["id"]: 0 for rule in topic_rules}
    annotated: list[dict[str, Any]] = []
    for record in records:
        text = _record_text(record)
        matched_topics = [
            rule["id"]
            for rule in topic_rules
            if any(keyword and keyword in text for keyword in rule["keywords"])
        ]
        for topic_id in matched_topics:
            counts[topic_id] += 1
        enriched = dict(record)
        enriched["matched_topic_ids"] = matched_topics
        annotated.append(enriched)
    return counts, annotated


def _record_text(record: dict[str, Any]) -> str:
    parts = [
        record.get("title", ""),
        record.get("snippet", ""),
        record.get("description", ""),
        record.get("summary", ""),
        " ".join(record.get("terms", []) or []),
        " ".join(record.get("entities", []) or []),
    ]
    return _normalize_text(" ".join(part for part in parts if isinstance(part, str)))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "topic"
