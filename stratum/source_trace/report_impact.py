"""Source impact scoring from report evidence links."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def compute_report_impact(
    report_items: list[dict[str, Any]],
    evidence_links: list[dict[str, Any]],
    articles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score how much each source contributes to report items and judgments."""
    articles_by_id = {
        str(article.get("id") or article.get("article_id") or ""): article
        for article in articles
    }
    items_by_id = {
        str(item.get("id") or item.get("item_id") or ""): item
        for item in report_items
    }
    rows: dict[str, dict[str, Any]] = defaultdict(_row)

    for link in evidence_links:
        article = articles_by_id.get(str(link.get("article_id") or link.get("evidence_id") or ""))
        item = items_by_id.get(str(link.get("item_id") or link.get("report_item_id") or ""))
        source = _source(article or link)
        row = rows[source]
        row["source"] = source
        row["evidence_links"] += 1
        if item:
            row["report_items"].add(str(item.get("id") or item.get("item_id")))
            signal_type = str(item.get("signal_type") or item.get("section_key") or "general")
            row["signal_types"][signal_type] += 1
        if link.get("support_level") in {"primary", "core", "strong"}:
            row["primary_support"] += 1

    sources = []
    for row in rows.values():
        item_count = len(row["report_items"])
        impact_score = min(1.0, 0.1 * row["evidence_links"] + 0.2 * item_count + 0.15 * row["primary_support"])
        sources.append({
            "source": row["source"],
            "impact_score": round(impact_score, 4),
            "evidence_links": row["evidence_links"],
            "report_item_count": item_count,
            "primary_support": row["primary_support"],
            "signal_types": dict(sorted(row["signal_types"].items())),
        })
    return {"sources": sorted(sources, key=lambda item: (-item["impact_score"], item["source"]))}


def _row() -> dict[str, Any]:
    return {
        "source": "",
        "evidence_links": 0,
        "report_items": set(),
        "primary_support": 0,
        "signal_types": defaultdict(int),
    }


def _source(item: dict[str, Any] | None) -> str:
    item = item or {}
    engine = str(item.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(item.get("source") or item.get("source_domain") or "unknown")
