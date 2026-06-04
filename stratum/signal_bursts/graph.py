"""Term co-occurrence graph for Signal Bursts."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any


def build_co_occurrence(matched_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build weighted term-pair co-occurrence diagnostics."""
    pairs: dict[tuple[str, str], dict[str, Any]] = defaultdict(_pair)
    for record in matched_records:
        terms = sorted(set(record.get("terms", [])))
        for left, right in combinations(terms, 2):
            row = pairs[(left, right)]
            row["terms"] = [left, right]
            row["count"] += 1
            row["sources"].add(record.get("source", "unknown"))
            row["layers"].add(record.get("layer", "unknown"))
            if len(row["representative_titles"]) < 5 and record.get("title"):
                row["representative_titles"].append(record["title"])

    edges = []
    for row in pairs.values():
        edges.append({
            "terms": row["terms"],
            "count": row["count"],
            "source_count": len(row["sources"]),
            "layers": sorted(row["layers"]),
            "representative_titles": row["representative_titles"],
        })
    return {
        "edges": sorted(edges, key=lambda item: (-item["count"], item["terms"])),
        "totals": {
            "edges": len(edges),
            "records_with_multiple_terms": sum(1 for record in matched_records if len(set(record.get("terms", []))) >= 2),
        },
    }


def _pair() -> dict[str, Any]:
    return {
        "terms": [],
        "count": 0,
        "sources": set(),
        "layers": set(),
        "representative_titles": [],
    }
