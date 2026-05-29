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
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def cluster_articles(articles: list[dict], threshold: float = 0.25) -> list[list[int]]:
    """Group articles by entity/term overlap using Jaccard similarity."""
    n = len(articles)
    if n < 2:
        return []

    article_sets = []
    for a in articles:
        entities = set(a.get("entities", []))
        terms = set(a.get("terms", []))
        article_sets.append(entities | terms)

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(article_sets[i], article_sets[j])
            if sim >= threshold:
                pairs.append((sim, i, j))

    pairs.sort(reverse=True)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[py] = px

    for sim, i, j in pairs:
        union(i, j)

    clusters_map = defaultdict(list)
    for i in range(n):
        root = find(i)
        clusters_map[root].append(i)

    clusters = [sorted(indices) for indices in clusters_map.values()
                if len(indices) >= 2]

    return clusters


def build_cluster_object(cluster_indices: list[int], articles: list[dict],
                         domain_id: str, seq: int) -> dict:
    """Build a StoryCluster object from article indices."""
    cluster_articles = [articles[i] for i in cluster_indices]

    titles = [a["title"] for a in cluster_articles]
    entities = set()
    terms = set()
    source_types = set()
    locales = set()
    article_ids = []

    for a in cluster_articles:
        entities.update(a.get("entities", []))
        terms.update(a.get("terms", []))
        source_types.add(a.get("source_type", "unknown"))
        locales.add(a.get("source_locale", "unknown"))
        article_ids.append(a["id"])

    num_articles = len(cluster_articles)
    num_source_types = len(source_types)
    num_locales = len(locales)

    if num_source_types >= 3 and num_articles >= 5:
        confidence = "high"
    elif num_source_types >= 2 and num_articles >= 3:
        confidence = "medium"
    elif num_articles >= 2:
        confidence = "low"
    else:
        confidence = "low"

    confidence_score = min(1.0,
                           0.3 * min(num_articles / 10, 1.0) +
                           0.3 * min(num_source_types / 3, 1.0) +
                           0.2 * min(num_locales / 3, 1.0) +
                           0.2 * min(len(entities) / 10, 1.0))

    best_title = max(titles, key=lambda t: sum(1 for e in entities if e.lower() in t.lower()))
    if len(best_title) > 100:
        best_title = best_title[:97] + "..."

    snippets = [a.get("snippet", "")[:200] for a in cluster_articles[:3] if a.get("snippet")]
    canonical_summary = " ".join(snippets)[:500]

    return {
        "id": f"sc-{domain_id}-{seq:04d}",
        "canonical_title": best_title,
        "canonical_summary": canonical_summary,
        "confidence": confidence,
        "confidence_score": round(confidence_score, 3),
        "article_ids": article_ids,
        "article_count": num_articles,
        "source_types": sorted(source_types),
        "locales": sorted(locales),
        "entities": sorted(entities),
        "terms": sorted(terms),
        "created": datetime.now(CST).strftime("%Y-%m-%d"),
    }


def main():
    parser = argparse.ArgumentParser(description="Deterministic story clustering")
    parser.add_argument("--input", "-i", required=True, help="Input articles.jsonl")
    parser.add_argument("--output", "-o", required=True, help="Output clusters.json")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml (for domain_id)")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--threshold", "-t", type=float, default=0.25,
                        help="Jaccard similarity threshold (default: 0.25)")
    args = parser.parse_args()

    # Extract domain_id from domain path: domains/storage/domain.yaml → storage
    domain_id = os.path.basename(os.path.dirname(os.path.dirname(args.domain)))

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
        clusters_indices = cluster_articles(articles, args.threshold)

        clusters = []
        clustered_ids = set()
        for seq, indices in enumerate(clusters_indices, 1):
            cluster_obj = build_cluster_object(indices, articles, domain_id, seq)
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
