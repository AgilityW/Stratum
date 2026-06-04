#!/usr/bin/env python3
"""cluster.py — Deterministic story clustering.

Domain-agnostic. Groups articles by entity/term overlap using Jaccard similarity (Union-Find).
Minimum 2 articles per cluster. Assigns confidence scores based on source diversity + article count.

Input:  JSONL — normalized ArticleRecords with {entities, terms, source_type, source_locale, ...}
Output: JSON — {date, domain, total_articles, clustered_articles, clusters: [StoryCluster], unclustered}
Side effects: None. Pure function — reads input, writes output.
Invariants:  Articles with < 2 total → empty clusters array, unclustered = total_articles.
             < 2 articles per group → silently excluded (not a cluster).
Error behavior: Empty input → empty result with total_articles=0.

Usage:
    python3 cluster.py --input articles.jsonl --output clusters.json \
        --domain domains/storage/domain.yaml --date 2026-05-28
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

from stratum.sourcing.discovery import canonicalize_url
try:
    from .story_clusterer import (
        ClusterConfidenceScorer,
        StoryClusterer,
        cluster_articles,
        jaccard_similarity,
        weighted_overlap_similarity,
    )
except ImportError:  # pragma: no cover - direct script/test fallback
    from stratum.stages.cluster.story_clusterer import (
        ClusterConfidenceScorer,
        StoryClusterer,
        cluster_articles,
        jaccard_similarity,
        weighted_overlap_similarity,
    )

CST = timezone(timedelta(hours=8))


def build_cluster_object(cluster_indices: list[int], articles: list[dict],
                         domain_id: str, seq: int,
                         created_date: Optional[str] = None) -> dict:
    """Build a StoryCluster object from article indices.

    Derives thread_id (most common event_thread_id in cluster) and
    is_continuation (True if any article carries an event_thread_id).
    """
    cluster_articles = [articles[i] for i in cluster_indices]

    titles = [a["title"] for a in cluster_articles]
    entities = set()
    terms = set()
    source_types = set()
    locales = set()
    source_domains = set()
    canonical_urls = []
    article_ids = []
    thread_ids = []

    for a in cluster_articles:
        entities.update(a.get("entities", []))
        terms.update(a.get("terms", []))
        source_types.add(a.get("source_type", "unknown"))
        locales.add(a.get("source_locale", "unknown"))
        source_domain = a.get("source") or a.get("source_domain")
        if source_domain:
            source_domains.add(source_domain)
        canonical_url = a.get("canonical_url") or canonicalize_url(a.get("url", ""))
        if canonical_url and canonical_url not in canonical_urls:
            canonical_urls.append(canonical_url)
        article_ids.append(a["id"])
        tid = a.get("event_thread_id")
        if tid:
            thread_ids.append(tid)

    # Derive thread_id: most common across articles in this cluster
    thread_id = None
    is_continuation = False
    if thread_ids:
        is_continuation = True
        # Pick most frequent thread_id
        from collections import Counter
        thread_id = Counter(thread_ids).most_common(1)[0][0]

    num_articles = len(cluster_articles)
    num_source_types = len(source_types)
    num_locales = len(locales)

    confidence = ClusterConfidenceScorer().score(
        article_count=num_articles,
        source_type_count=num_source_types,
        locale_count=num_locales,
        entity_count=len(entities),
    )

    best_title = max(titles, key=lambda t: sum(1 for e in entities if e.lower() in t.lower()))
    if len(best_title) > 100:
        best_title = best_title[:97] + "..."

    snippets = [a.get("snippet", "")[:200] for a in cluster_articles[:3] if a.get("snippet")]
    canonical_summary = " ".join(snippets)[:500]

    result = {
        "id": f"sc-{domain_id}-{seq:04d}",
        "canonical_title": best_title,
        "canonical_summary": canonical_summary,
        "confidence": confidence.label,
        "confidence_score": confidence.score,
        "article_ids": article_ids,
        "article_count": num_articles,
        "source_types": sorted(source_types),
        "locales": sorted(locales),
        "source_domains": sorted(source_domains),
        "canonical_urls": canonical_urls,
        "entities": sorted(entities),
        "terms": sorted(terms),
        "created": created_date or datetime.now(CST).strftime("%Y-%m-%d"),
    }
    if thread_id:
        result["thread_id"] = thread_id
    if is_continuation:
        result["is_continuation"] = True

    return result


def extract_domain_id(domain_path: str) -> str:
    """Extract domain id from a domain.yaml path or return the value unchanged."""
    normalized = os.path.normpath(domain_path)
    if os.path.basename(normalized) == "domain.yaml":
        return os.path.basename(os.path.dirname(normalized))
    return os.path.basename(normalized)


def main():
    parser = argparse.ArgumentParser(description="Deterministic story clustering")
    parser.add_argument("--input", "-i", required=True, help="Input articles.jsonl")
    parser.add_argument("--output", "-o", required=True, help="Output clusters.json")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml (for domain_id)")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--threshold", "-t", type=float, default=0.35,
                        help="Jaccard similarity threshold (default: 0.35)")
    parser.add_argument("--max-size", type=int, default=10,
                        help="Max articles per cluster, oversized re-split (default: 10, 0=unlimited)")
    args = parser.parse_args()

    domain_id = extract_domain_id(args.domain)

    articles = []
    with open(args.input) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))

    if len(articles) < 2:
        result = {
            "date": args.date,
            "domain": domain_id,
            "total_articles": len(articles),
            "clusters": [],
            "unclustered": len(articles),
        }
    else:
        clusters_indices = cluster_articles(articles, args.threshold, args.max_size)

        clusters = []
        clustered_ids = set()
        for seq, indices in enumerate(clusters_indices, 1):
            cluster_obj = build_cluster_object(indices, articles, domain_id, seq, args.date)
            clusters.append(cluster_obj)
            clustered_ids.update(cluster_obj["article_ids"])

        all_ids = {a["id"] for a in articles}
        unclustered_ids = all_ids - clustered_ids

        result = {
            "date": args.date,
            "domain": domain_id,
            "total_articles": len(articles),
            "clustered_articles": len(clustered_ids),
            "clusters": clusters,
            "unclustered": len(unclustered_ids),
        }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Clustering complete:", file=sys.stderr)
    print(f"   Articles:       {result['total_articles']}", file=sys.stderr)
    print(f"   Clusters:       {len(result['clusters'])}", file=sys.stderr)
    print(f"   Clustered:      {result.get('clustered_articles', 0)}", file=sys.stderr)
    print(f"   Unclustered:    {result.get('unclustered', 0)}", file=sys.stderr)
    for c in result["clusters"]:
        print(f"     [{c['confidence']}] {c['canonical_title'][:70]} "
              f"({c['article_count']} articles, {len(c['source_types'])} types, "
              f"{len(c['locales'])} locales)", file=sys.stderr)


if __name__ == "__main__":
    main()
