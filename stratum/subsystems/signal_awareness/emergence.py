"""Detect unanchored event-like clusters from current records."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any


GENERIC_EVENT_TERMS = {
    "conference",
    "summit",
    "expo",
    "forum",
    "show",
    "booth",
    "keynote",
    "preview",
    "coverage",
    "event",
    "trade",
    "exhibitor",
    "agenda",
    "expected",
    "expect",
    "live",
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "after", "before", "amid", "during", "will", "2025", "2026", "2027",
}


def detect_unanchored_event_clusters(
    records: list[dict[str, Any]],
    anchor_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find event-like record clusters not already explained by anchor matches."""
    matched_titles = {
        title
        for signal in anchor_signals
        for title in signal.get("representative_titles", [])
    }
    candidate_records = [
        record for record in records
        if record.get("title")
        and record.get("title") not in matched_titles
        and _has_event_clue(record)
    ]
    token_frequency = Counter()
    tokenized_records: list[tuple[dict[str, Any], list[str]]] = []
    for record in candidate_records:
        tokens = _significant_tokens(record)
        tokenized_records.append((record, tokens))
        token_frequency.update(set(tokens))
    clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record, tokens in tokenized_records:
        ranked = sorted(
            (token for token in tokens if token_frequency[token] > 1),
            key=lambda token: (-token_frequency[token], token),
        )
        if not ranked:
            continue
        signature = tuple(ranked[:2])
        clusters[signature].append(record)
    output: list[dict[str, Any]] = []
    for signature, grouped in sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(grouped) < 2:
            continue
        output.append({
            "cluster_key": "-".join(signature),
            "label": " ".join(signature).title(),
            "record_count": len(grouped),
            "sources": sorted({record.get("source") or record.get("source_domain") or "unknown" for record in grouped}),
            "representative_titles": [record.get("title", "") for record in grouped[:5]],
        })
    return output


def _has_event_clue(record: dict[str, Any]) -> bool:
    text = _normalize_text(" ".join(str(record.get(key, "")) for key in ("title", "snippet", "description")))
    return any(term in text for term in GENERIC_EVENT_TERMS)


def _significant_tokens(record: dict[str, Any]) -> list[str]:
    text = _normalize_text(" ".join(str(record.get(key, "")) for key in ("title", "snippet", "description")))
    tokens = re.findall(r"[a-z0-9]+", text)
    return [
        token
        for token in tokens
        if len(token) >= 4 and token not in GENERIC_EVENT_TERMS and token not in STOPWORDS
    ]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
