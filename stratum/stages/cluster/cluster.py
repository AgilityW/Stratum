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
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from stratum.subsystems.search.models import canonicalize_url

CST = timezone(timedelta(hours=8))


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def weighted_overlap_similarity(article_a: dict, article_b: dict) -> float:
    """Weighted entity/term overlap for story clustering.

    Entities are more specific than terms, and the first entity is treated as
    the article's best available subject hint. This reduces over-merging on
    broad terms like HBM/NAND while still clustering cross-source reports about
    the same entity + topic.
    """
    entities_a = set(article_a.get("entities", []))
    entities_b = set(article_b.get("entities", []))
    terms_a = set(article_a.get("terms", []))
    terms_b = set(article_b.get("terms", []))
    primary_a = _primary_entity(article_a)
    primary_b = _primary_entity(article_b)

    entity_sim = jaccard_similarity(entities_a, entities_b)
    term_sim = jaccard_similarity(terms_a, terms_b)
    primary_sim = 1.0 if primary_a and primary_a == primary_b else 0.0

    if not entities_a and not entities_b:
        return round(term_sim * 0.7, 3)
    if not terms_a and not terms_b:
        return round(entity_sim * 0.45 + primary_sim * 0.25, 3)

    score = entity_sim * 0.35 + primary_sim * 0.2 + term_sim * 0.3
    if entities_a & entities_b and not primary_sim:
        score -= 0.08
    return round(max(0.0, score), 3)


def _cluster_by_jaccard(articles: list[dict], threshold: float) -> list[list[int]]:
    """Union-Find clustering by weighted entity/term overlap.

    Internal helper — called by cluster_articles for Phase 1 (orphans)
    and Phase 2 (oversized split). Always returns only groups with ≥2 articles.
    """
    n = len(articles)
    if n < 2:
        return []

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = weighted_overlap_similarity(articles[i], articles[j])
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


def _primary_entity(article: dict) -> str | None:
    entities = article.get("entities") or []
    return str(entities[0]) if entities else None


def _shared_entities(articles: list[dict]) -> set:
    entity_sets = [set(a.get("entities") or []) for a in articles if a.get("entities")]
    if not entity_sets:
        return set()
    common = set(entity_sets[0])
    for entity_set in entity_sets[1:]:
        common &= entity_set
    return common


def _split_bridge_cluster(cluster_indices: list[int], articles: list[dict]) -> list[list[int]]:
    """Split orphan clusters that only exist through bridge articles.

    Union-Find is intentionally good at recall, but it can connect A-B-C when
    B overlaps both A and C while A and C are actually different subjects. If
    a cluster has no entity shared by every article, primary-entity groups keep
    adjacent topics from collapsing into one story.
    """
    if len(cluster_indices) <= 2:
        return [cluster_indices]

    cluster_articles = [articles[i] for i in cluster_indices]
    if _shared_entities(cluster_articles):
        return [cluster_indices]

    groups: dict[str, list[int]] = defaultdict(list)
    ungrouped: list[int] = []
    for idx in cluster_indices:
        primary = _primary_entity(articles[idx])
        if primary:
            groups[primary].append(idx)
        else:
            ungrouped.append(idx)

    split = [sorted(indices) for indices in groups.values() if len(indices) >= 2]
    if len(ungrouped) >= 2:
        split.append(sorted(ungrouped))
    return split or [cluster_indices]


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

    # Combine: thread_groups + orphan_clusters. Thread-anchored clusters are a
    # continuity contract with Story Tracking, so they stay intact even when
    # they exceed the generic orphan-cluster display size.
    clusters = []
    anchored_clusters = set()
    for tid, indices in thread_groups.items():
        if len(indices) >= 2:
            clusters.append(sorted(indices))
            anchored_clusters.add(len(clusters) - 1)
        else:
            remaining_singletons.extend(indices)
    for cluster in orphan_clusters:
        clusters.extend(_split_bridge_cluster(cluster, articles))
    # Singletons (1-article) are NOT clusters — silently excluded

    # Phase 2: Split oversized clusters recursively
    if max_size > 0:
        final_clusters = []
        for cluster_pos, cluster_indices in enumerate(clusters):
            if len(cluster_indices) > max_size and cluster_pos not in anchored_clusters:
                sub_articles = [articles[i] for i in cluster_indices]
                split_threshold = max(threshold + 0.1, 0.35)
                sub_clusters = _cluster_by_jaccard(sub_articles, split_threshold)
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
