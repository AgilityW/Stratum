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


def _cluster_by_jaccard(articles: list[dict], threshold: float) -> list[list[int]]:
    """Pure Union-Find Jaccard clustering. No thread anchoring, no max_size split.

    Internal helper — called by cluster_articles for Phase 1 (orphans)
    and Phase 2 (oversized split). Always returns only groups with ≥2 articles.
    """
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

    return [sorted(indices) for indices in clusters_map.values()
            if len(indices) >= 2]


def cluster_articles(articles: list[dict], threshold: float = 0.35,
                     max_size: int = 10) -> list[list[int]]:
    """Group articles by entity/term overlap using Jaccard similarity (Union-Find).

    Three-phase clustering:
      Phase 0: Same event_thread_id → forced merge (thread anchoring).
      Phase 1: Remaining orphans → Union-Find Jaccard ≥ threshold.
      Phase 2: Oversized clusters (>max_size) → re-split at threshold+0.1.

    Args:
        threshold: Minimum Jaccard similarity to connect articles (default 0.35).
                   Higher = tighter clusters. Storage domain tuned at 0.35.
        max_size: Maximum articles per cluster. Oversized clusters are re-split
                  at threshold + 0.1 recursively. 0 = no limit.
    """
    n = len(articles)
    if n < 2:
        return []

    # Phase 0: thread_id anchoring — same event_thread_id → forced merge
    thread_groups = defaultdict(list)
    orphan_indices = []
    for i, a in enumerate(articles):
        tid = a.get("event_thread_id")
        if tid:
            thread_groups[tid].append(i)
        else:
            orphan_indices.append(i)

    # Phase 1: Union-Find on remaining (orphan) articles
    orphan_clusters = []
    remaining_singletons = []
    if len(orphan_indices) >= 2:
        orphans = [articles[i] for i in orphan_indices]
        orphan_result = _cluster_by_jaccard(orphans, threshold)
        accounted = set()
        for oc in orphan_result:
            orphan_clusters.append([orphan_indices[idx] for idx in oc])
            accounted.update(oc)
        remaining_singletons = [orphan_indices[i] for i in range(len(orphan_indices))
                                if i not in accounted]
    else:
        remaining_singletons = list(orphan_indices)

    # Combine: thread_groups + orphan_clusters
    clusters = []
    for tid, indices in thread_groups.items():
        if len(indices) >= 2:
            clusters.append(sorted(indices))
        else:
            remaining_singletons.extend(indices)
    clusters.extend(orphan_clusters)
    # Singletons (1-article) are NOT clusters — silently excluded

    # Phase 2: Split oversized clusters recursively
    if max_size > 0:
        final_clusters = []
        for cluster_indices in clusters:
            if len(cluster_indices) > max_size:
                sub_articles = [articles[i] for i in cluster_indices]
                sub_clusters = _cluster_by_jaccard(sub_articles, threshold + 0.1)
                if sub_clusters:
                    for sub in sub_clusters:
                        final_clusters.append([cluster_indices[i] for i in sub])
                else:
                    final_clusters.append(cluster_indices)
            else:
                final_clusters.append(cluster_indices)
        clusters = final_clusters

    return clusters


def build_cluster_object(cluster_indices: list[int], articles: list[dict],
                         domain_id: str, seq: int) -> dict:
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
    article_ids = []
    thread_ids = []

    for a in cluster_articles:
        entities.update(a.get("entities", []))
        terms.update(a.get("terms", []))
        source_types.add(a.get("source_type", "unknown"))
        locales.add(a.get("source_locale", "unknown"))
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

    result = {
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
    if thread_id:
        result["thread_id"] = thread_id
    if is_continuation:
        result["is_continuation"] = True

    return result


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
        clusters_indices = cluster_articles(articles, args.threshold, args.max_size)

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
