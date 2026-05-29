"""Tests for cluster stage — Jaccard similarity clustering."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.cluster.cluster import (
    jaccard_similarity, cluster_articles, build_cluster_object
)


class TestJaccardSimilarity:
    def test_identical(self):
        assert jaccard_similarity({"A", "B"}, {"A", "B"}) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"A"}, {"B"}) == 0.0

    def test_partial(self):
        sim = jaccard_similarity({"A", "B", "C"}, {"B", "C", "D"})
        assert sim == 2/4  # intersection={B,C}, union={A,B,C,D}

    def test_empty_sets(self):
        assert jaccard_similarity(set(), {"A"}) == 0.0
        assert jaccard_similarity(set(), set()) == 0.0


class TestClusterArticles:
    def test_two_similar_articles_clustered(self):
        articles = [
            {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM", "DRAM"]},
            {"entities": ["Samsung"], "terms": ["HBM", "DDR5"]},
        ]
        clusters = cluster_articles(articles, threshold=0.2)
        assert len(clusters) == 1
        assert clusters[0] == [0, 1]

    def test_disjoint_articles_not_clustered(self):
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM"]},
            {"entities": ["Apple"], "terms": ["iPhone"]},
        ]
        clusters = cluster_articles(articles, threshold=0.2)
        assert len(clusters) == 0

    def test_single_article_returns_empty(self):
        articles = [{"entities": ["Samsung"], "terms": ["HBM"]}]
        clusters = cluster_articles(articles)
        assert len(clusters) == 0

    def test_three_articles_two_clustered(self):
        articles = [
            {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM"]},
            {"entities": ["Samsung"], "terms": ["HBM", "DDR5"]},
            {"entities": ["Apple"], "terms": ["iPhone"]},
        ]
        clusters = cluster_articles(articles, threshold=0.2)
        assert len(clusters) == 1
        assert 2 in clusters[0] or len(clusters[0]) == 2

    # --- Phase 0: thread anchoring ---
    def test_thread_anchored_forced_merge(self):
        """Same event_thread_id → forced merge, regardless of entity overlap."""
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM"], "event_thread_id": "et-001"},
            {"entities": ["Apple"], "terms": ["iPhone"], "event_thread_id": "et-001"},
        ]
        clusters = cluster_articles(articles, threshold=0.99)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1]

    def test_thread_anchor_split_with_orphans(self):
        """Thread-anchored group + unrelated orphan → only thread group clusters."""
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM"], "event_thread_id": "et-001"},
            {"entities": ["NVIDIA"], "terms": ["GPU"], "event_thread_id": "et-001"},
            {"entities": ["Apple"], "terms": ["iPhone"]},  # orphan
        ]
        clusters = cluster_articles(articles, threshold=0.2)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1]

    def test_thread_anchor_multiple_threads(self):
        """Two distinct threads → two separate clusters."""
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM"], "event_thread_id": "et-001"},
            {"entities": ["SK hynix"], "terms": ["HBM"], "event_thread_id": "et-001"},
            {"entities": ["NAND"], "terms": ["price"], "event_thread_id": "et-002"},
            {"entities": ["NAND"], "terms": ["supply"], "event_thread_id": "et-002"},
        ]
        clusters = cluster_articles(articles, threshold=0.99)
        assert len(clusters) == 2
        cluster_sets = [set(c) for c in clusters]
        assert {0, 1} in cluster_sets
        assert {2, 3} in cluster_sets

    # --- max_size split ---
    def test_max_size_split(self):
        """Cluster > max_size gets split at higher threshold.

        Uses 4 articles: all share 'X' (merge at 0.10), but split into
        two pairs at 0.20 because each pair also shares a second token.
        """
        articles = [
            {"entities": ["X", "Y"], "terms": ["a1", "a2"]},
            {"entities": ["X", "Y"], "terms": ["b1", "b2"]},
            {"entities": ["X", "Z"], "terms": ["c1", "c2"]},
            {"entities": ["X", "Z"], "terms": ["d1", "d2"]},
        ]
        # At 0.10: all merge via shared "X" (Jaccard ≈ 0.14 between pairs)
        # At 0.20: split into (0,1) and (2,3) — each pair shares {X,Y} or {X,Z}
        clusters = cluster_articles(articles, threshold=0.10, max_size=2)
        # Every cluster must be ≤ max_size
        for c in clusters:
            assert len(c) <= 2, f"cluster {c} exceeds max_size=2"
        assert len(clusters) == 2
        # Verify the split groups: {0,1} and {2,3}
        cluster_sets = [set(c) for c in clusters]
        assert {0, 1} in cluster_sets
        assert {2, 3} in cluster_sets

    def test_max_size_zero_no_limit(self):
        """max_size=0 → no split, all pass through."""
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM"]},
            {"entities": ["Samsung"], "terms": ["DRAM"]},
            {"entities": ["Samsung"], "terms": ["NAND"]},
            {"entities": ["Samsung"], "terms": ["DDR5"]},
        ]
        clusters = cluster_articles(articles, threshold=0.01, max_size=0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 4


class TestBuildClusterObject:
    def test_builds_cluster(self):
        articles = [
            {
                "id": "abc123",
                "title": "Samsung ships HBM4 to NVIDIA",
                "snippet": "Samsung Electronics announced HBM4 production.",
                "entities": ["Samsung", "NVIDIA"],
                "terms": ["HBM", "HBM4"],
                "source_type": "media",
                "source_locale": "en",
            },
            {
                "id": "def456",
                "title": "SK hynix HBM4 sampling",
                "snippet": "SK hynix begins HBM4 sampling for NVIDIA.",
                "entities": ["SK hynix", "NVIDIA"],
                "terms": ["HBM", "HBM4"],
                "source_type": "official",
                "source_locale": "en",
            },
        ]
        result = build_cluster_object([0, 1], articles, "storage", 1)
        assert result["id"] == "sc-storage-0001"
        assert result["article_count"] == 2
        assert "NVIDIA" in result["entities"]
        assert "HBM" in result["terms"]
        assert result["confidence"] in ("low", "medium", "high")
        assert 0 <= result["confidence_score"] <= 1

    def test_builds_cluster_with_thread_id(self):
        """Cluster with event_thread_id gets thread_id and is_continuation."""
        articles = [
            {
                "id": "a1", "title": "HBM4 ramp", "snippet": "...",
                "entities": ["Samsung"], "terms": ["HBM4"],
                "source_type": "media", "source_locale": "en",
                "event_thread_id": "et-001",
            },
            {
                "id": "a2", "title": "HBM4 volume", "snippet": "...",
                "entities": ["SK hynix"], "terms": ["HBM4"],
                "source_type": "official", "source_locale": "ko",
                "event_thread_id": "et-001",
            },
        ]
        result = build_cluster_object([0, 1], articles, "storage", 2)
        assert result["thread_id"] == "et-001"
        assert result["is_continuation"] is True

    def test_builds_cluster_no_thread_id(self):
        """Cluster without event_thread_id has no thread_id/is_continuation."""
        articles = [
            {
                "id": "a1", "title": "NAND price", "snippet": "...",
                "entities": ["Kioxia"], "terms": ["NAND"],
                "source_type": "media", "source_locale": "en",
            },
        ]
        result = build_cluster_object([0], articles, "storage", 3)
        assert "thread_id" not in result
        assert "is_continuation" not in result
