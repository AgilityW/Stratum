"""Coverage Monitor — Post-clustering gap detection.

Deterministic core: source type/locale gap detection in story clusters,
follow-up query generation for high-severity gaps.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

IDEAL_TYPES = {"official", "analyst", "media"}
CORE_LOCALES = {"zh-CN", "en"}


def detect_gaps(clusters: list[dict], source_records: list[dict]) -> list[dict]:
    """Find clusters missing source types or locale coverage.

    Args:
        clusters: StoryCluster objects from cluster stage
        source_records: SourceRecords for today

    Returns:
        List of gap objects with severity and followup queries
    """
    # Build cluster → {types, locales, sources} map
    cluster_info = defaultdict(lambda: {"types": set(), "locales": set(), "sources": []})
    for r in source_records:
        cid = r.get("cluster_id")
        if cid:
            cluster_info[cid]["types"].add(r.get("source_type", "unknown"))
            cluster_info[cid]["locales"].add(r.get("source_locale", "en"))
            cluster_info[cid]["sources"].append(r.get("source", ""))

    gaps = []
    for cluster in clusters:
        cid = cluster.get("id", "")
        info = cluster_info.get(cid, {"types": set(), "locales": set(), "sources": []})

        gap = {
            "cluster_id": cid,
            "title": cluster.get("canonical_title", ""),
            "confidence": cluster.get("confidence", "C"),
            "current_types": sorted(info["types"]),
            "current_locales": sorted(info["locales"]),
            "current_sources": info["sources"],
        }

        missing_types = IDEAL_TYPES - info["types"]
        if missing_types:
            gap["missing_types"] = sorted(missing_types)

        missing_locales = CORE_LOCALES - info["locales"]
        if missing_locales:
            gap["missing_locales"] = sorted(missing_locales)

        if "missing_types" in gap or "missing_locales" in gap:
            confidence = cluster.get("confidence", "C")
            is_high = confidence in ("C", "D") and len(info["sources"]) <= 2
            gap["severity"] = "high" if is_high else "medium"
        else:
            continue  # No gap — skip

        gaps.append(gap)

    return gaps


def generate_followup_queries(gaps: list[dict], max_per_gap: int = 3) -> list[dict]:
    """Generate verification queries for high-severity gaps."""
    queries = []
    for gap in gaps:
        if gap.get("severity") != "high":
            continue
        title = gap.get("title", "")[:60]
        entities = gap.get("entities", [])

        gap_queries = []
        if "missing_types" in gap:
            if "analyst" in gap["missing_types"]:
                gap_queries.append(f"{title} analysis report")
            if "official" in gap["missing_types"] and entities:
                gap_queries.append(f"{entities[0]} {title[:30]} official")

        if "missing_locales" in gap:
            for loc in gap["missing_locales"]:
                if loc == "zh-CN":
                    gap_queries.append(f"{title[:30]} 中文")
                elif loc == "en":
                    gap_queries.append(f"{title[:40]} english")

        for q in gap_queries[:max_per_gap]:
            queries.append({
                "query": q,
                "locale": gap.get("missing_locales", ["en"])[0] if gap.get("missing_locales") else "en",
                "source": "coverage_monitor",
                "cluster_id": gap["cluster_id"],
            })

    return queries


def run_coverage_check(
    clusters: list[dict],
    source_records: list[dict],
    run_date: str,
    output_dir: str,
) -> dict:
    """Full coverage check: detect gaps, generate queries, write output.

    Returns: {date, total_clusters, gaps_found, high_severity, gaps, followup_queries}
    """
    gaps = detect_gaps(clusters, source_records)
    followup = generate_followup_queries(gaps)

    result = {
        "date": run_date,
        "generated": datetime.now(CST).isoformat(),
        "total_clusters": len(clusters),
        "gaps_found": len(gaps),
        "high_severity": len([g for g in gaps if g.get("severity") == "high"]),
        "gaps": gaps,
        "followup_queries": followup,
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "gap-alerts.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if followup:
        with open(os.path.join(output_dir, "gap-queries.json"), "w") as f:
            json.dump(followup, f, indent=2, ensure_ascii=False)

    return result
