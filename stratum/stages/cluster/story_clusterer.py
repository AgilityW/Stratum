"""Story clustering algorithms."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterConfidence:
    """Confidence label and score for a story cluster."""

    label: str
    score: float


class StoryClusterer:
    """Cluster articles by thread anchors and weighted entity/term overlap."""

    def __init__(self, threshold: float = 0.35, max_size: int = 10):
        self.threshold = threshold
        self.max_size = max_size

    def cluster(self, articles: list[dict]) -> list[list[int]]:
        n = len(articles)
        if n < 2:
            return []

        thread_groups = defaultdict(list)
        orphan_indices = []
        for index, article in enumerate(articles):
            thread_id = article.get("event_thread_id")
            if thread_id:
                thread_groups[thread_id].append(index)
            else:
                orphan_indices.append(index)

        orphan_clusters = []
        remaining_singletons = []
        if len(orphan_indices) >= 2:
            orphans = [articles[index] for index in orphan_indices]
            orphan_result = self.cluster_by_overlap(orphans, self.threshold)
            accounted = set()
            for orphan_cluster in orphan_result:
                orphan_clusters.append([orphan_indices[index] for index in orphan_cluster])
                accounted.update(orphan_cluster)
            remaining_singletons = [
                orphan_indices[index]
                for index in range(len(orphan_indices))
                if index not in accounted
            ]
        else:
            remaining_singletons = list(orphan_indices)

        clusters = []
        anchored_clusters = set()
        for _thread_id, indices in thread_groups.items():
            if len(indices) >= 2:
                clusters.append(sorted(indices))
                anchored_clusters.add(len(clusters) - 1)
            else:
                remaining_singletons.extend(indices)
        for cluster in orphan_clusters:
            clusters.extend(split_bridge_cluster(cluster, articles))

        if self.max_size > 0:
            clusters = self._split_oversized_clusters(clusters, anchored_clusters, articles)

        return clusters

    def cluster_by_overlap(self, articles: list[dict], threshold: float) -> list[list[int]]:
        n = len(articles)
        if n < 2:
            return []

        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                similarity = weighted_overlap_similarity(articles[i], articles[j])
                if similarity >= threshold:
                    pairs.append((similarity, i, j))

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

        for _similarity, left, right in pairs:
            union(left, right)

        clusters_map = defaultdict(list)
        for index in range(n):
            root = find(index)
            clusters_map[root].append(index)

        return [
            sorted(indices)
            for indices in clusters_map.values()
            if len(indices) >= 2
        ]

    def _split_oversized_clusters(
        self,
        clusters: list[list[int]],
        anchored_clusters: set[int],
        articles: list[dict],
    ) -> list[list[int]]:
        final_clusters = []
        for cluster_pos, cluster_indices in enumerate(clusters):
            if len(cluster_indices) > self.max_size and cluster_pos not in anchored_clusters:
                sub_articles = [articles[index] for index in cluster_indices]
                split_threshold = max(self.threshold + 0.1, 0.35)
                sub_clusters = self.cluster_by_overlap(sub_articles, split_threshold)
                if sub_clusters:
                    for sub_cluster in sub_clusters:
                        final_clusters.append([cluster_indices[index] for index in sub_cluster])
                else:
                    final_clusters.append(cluster_indices)
            else:
                final_clusters.append(cluster_indices)
        return final_clusters


class ClusterConfidenceScorer:
    """Score cluster confidence from source diversity and article coverage."""

    def score(
        self,
        *,
        article_count: int,
        source_type_count: int,
        locale_count: int,
        entity_count: int,
    ) -> ClusterConfidence:
        if source_type_count >= 3 and article_count >= 5:
            label = "high"
        elif source_type_count >= 2 and article_count >= 3:
            label = "medium"
        elif article_count >= 2:
            label = "low"
        else:
            label = "low"

        score = min(
            1.0,
            0.3 * min(article_count / 10, 1.0)
            + 0.3 * min(source_type_count / 3, 1.0)
            + 0.2 * min(locale_count / 3, 1.0)
            + 0.2 * min(entity_count / 10, 1.0),
        )
        return ClusterConfidence(label=label, score=round(score, 3))


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def weighted_overlap_similarity(article_a: dict, article_b: dict) -> float:
    """Weighted entity/term overlap for story clustering."""
    entities_a = set(article_a.get("entities", []))
    entities_b = set(article_b.get("entities", []))
    terms_a = set(article_a.get("terms", []))
    terms_b = set(article_b.get("terms", []))
    primary_a = primary_entity(article_a)
    primary_b = primary_entity(article_b)

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


def primary_entity(article: dict) -> str | None:
    entities = article.get("entities") or []
    return str(entities[0]) if entities else None


def shared_entities(articles: list[dict]) -> set:
    entity_sets = [set(article.get("entities") or []) for article in articles if article.get("entities")]
    if not entity_sets:
        return set()
    common = set(entity_sets[0])
    for entity_set in entity_sets[1:]:
        common &= entity_set
    return common


def split_bridge_cluster(cluster_indices: list[int], articles: list[dict]) -> list[list[int]]:
    """Split orphan clusters that only exist through bridge articles."""
    if len(cluster_indices) <= 2:
        return [cluster_indices]

    cluster_articles = [articles[index] for index in cluster_indices]
    if shared_entities(cluster_articles):
        return [cluster_indices]

    groups: dict[str, list[int]] = defaultdict(list)
    ungrouped: list[int] = []
    for index in cluster_indices:
        primary = primary_entity(articles[index])
        if primary:
            groups[primary].append(index)
        else:
            ungrouped.append(index)

    split = [sorted(indices) for indices in groups.values() if len(indices) >= 2]
    if len(ungrouped) >= 2:
        split.append(sorted(ungrouped))
    return split or [cluster_indices]


def cluster_articles(articles: list[dict], threshold: float = 0.35, max_size: int = 10) -> list[list[int]]:
    """Compatibility wrapper for existing cluster-stage callers."""
    return StoryClusterer(threshold=threshold, max_size=max_size).cluster(articles)

