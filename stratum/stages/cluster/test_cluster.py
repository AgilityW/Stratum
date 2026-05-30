"""Tests for cluster stage — Jaccard similarity clustering."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from stratum.stages.cluster.cluster import (
    jaccard_similarity, weighted_overlap_similarity, cluster_articles,
    build_cluster_object, extract_domain_id
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


class TestWeightedOverlapSimilarity:
    def test_entity_and_term_overlap_scores_high(self):
        a = {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM4", "DRAM"]}
        b = {"entities": ["Samsung"], "terms": ["HBM4", "DDR5"]}

        assert weighted_overlap_similarity(a, b) >= 0.35

    def test_single_generic_term_scores_low(self):
        a = {"entities": ["Samsung"], "terms": ["HBM4", "DRAM"]}
        b = {"entities": ["SK hynix"], "terms": ["HBM4", "NAND"]}

        assert weighted_overlap_similarity(a, b) < 0.2

    def test_primary_entity_overlap_scores_above_secondary_only_overlap(self):
        primary_match_a = {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM4"]}
        primary_match_b = {"entities": ["Samsung", "AMD"], "terms": ["HBM4"]}
        secondary_only_a = {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM4"]}
        secondary_only_b = {"entities": ["SK hynix", "NVIDIA"], "terms": ["HBM4"]}

        assert weighted_overlap_similarity(primary_match_a, primary_match_b) > (
            weighted_overlap_similarity(secondary_only_a, secondary_only_b)
        )


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

    def test_shared_generic_term_does_not_overmerge(self):
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM4", "qualification"]},
            {"entities": ["Micron"], "terms": ["HBM4", "earnings"]},
        ]
        clusters = cluster_articles(articles, threshold=0.2)
        assert clusters == []

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

    def test_thread_anchored_cluster_not_split_by_max_size(self):
        """Event-thread continuity wins over generic oversized-cluster splitting."""
        articles = [
            {"entities": [f"Entity {i}"], "terms": [f"Term {i}"], "event_thread_id": "et-001"}
            for i in range(4)
        ]
        clusters = cluster_articles(articles, threshold=0.99, max_size=2)
        assert clusters == [[0, 1, 2, 3]]

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

    def test_bridge_article_does_not_merge_distinct_primary_entities(self):
        """A bridge article should not collapse separate subject clusters."""
        articles = [
            {"entities": ["Samsung"], "terms": ["HBM4", "qualification"]},
            {"entities": ["Samsung", "Micron"], "terms": ["HBM4", "qualification"]},
            {"entities": ["Micron"], "terms": ["HBM4", "pricing"]},
            {"entities": ["Micron"], "terms": ["HBM4", "pricing"]},
        ]

        clusters = cluster_articles(articles, threshold=0.2)

        assert [set(c) for c in clusters] == [{0, 1}, {2, 3}]

    def test_cluster_with_common_entity_survives_primary_entity_differences(self):
        """Different primary entities can still cluster around a shared subject."""
        articles = [
            {"entities": ["Samsung", "NVIDIA"], "terms": ["HBM4"]},
            {"entities": ["SK hynix", "NVIDIA"], "terms": ["HBM4"]},
            {"entities": ["Micron", "NVIDIA"], "terms": ["HBM4"]},
        ]

        clusters = cluster_articles(articles, threshold=0.2)

        assert clusters == [[0, 1, 2]]


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
                "source": "reuters.com",
                "canonical_url": "https://reuters.com/tech/samsung-hbm4",
            },
            {
                "id": "def456",
                "title": "SK hynix HBM4 sampling",
                "snippet": "SK hynix begins HBM4 sampling for NVIDIA.",
                "entities": ["SK hynix", "NVIDIA"],
                "terms": ["HBM", "HBM4"],
                "source_type": "official",
                "source_locale": "en",
                "source": "skhynix.com",
                "canonical_url": "https://skhynix.com/news/hbm4-sampling",
            },
        ]
        result = build_cluster_object([0, 1], articles, "storage", 1, "2026-05-30")
        assert result["id"] == "sc-storage-0001"
        assert result["created"] == "2026-05-30"
        assert result["article_count"] == 2
        assert "NVIDIA" in result["entities"]
        assert "HBM" in result["terms"]
        assert result["confidence"] in ("low", "medium", "high")
        assert 0 <= result["confidence_score"] <= 1
        assert result["source_domains"] == ["reuters.com", "skhynix.com"]
        assert result["canonical_urls"] == [
            "https://reuters.com/tech/samsung-hbm4",
            "https://skhynix.com/news/hbm4-sampling",
        ]

    def test_build_cluster_id_preserves_domain_id_shape(self):
        """Cluster IDs follow the provided domain directory id."""
        articles = [
            {
                "id": "a1", "title": "AI storage update", "snippet": "...",
                "entities": ["NVIDIA"], "terms": ["SSD"],
                "source_type": "media", "source_locale": "en",
                "source": "example.com", "canonical_url": "https://example.com/a",
            },
            {
                "id": "a2", "title": "AI storage update", "snippet": "...",
                "entities": ["NVIDIA"], "terms": ["SSD"],
                "source_type": "media", "source_locale": "en",
                "source": "example.org", "canonical_url": "https://example.org/b",
            },
        ]

        result = build_cluster_object([0, 1], articles, "ai-storage2", 1, "2026-05-30")

        assert result["id"] == "sc-ai-storage2-0001"

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

    def test_builds_cluster_accepts_run_date_for_backfills(self):
        articles = [
            {
                "id": "a1", "title": "NAND price", "snippet": "...",
                "entities": ["Kioxia"], "terms": ["NAND"],
                "source_type": "media", "source_locale": "en",
            },
            {
                "id": "a2", "title": "Kioxia NAND supply", "snippet": "...",
                "entities": ["Kioxia"], "terms": ["NAND"],
                "source_type": "analyst", "source_locale": "zh-CN",
            },
        ]
        result = build_cluster_object([0, 1], articles, "storage", 4, "2026-01-15")
        assert result["created"] == "2026-01-15"

    def test_builds_cluster_audit_fields_from_source_domain_and_url_fallbacks(self):
        articles = [
            {
                "id": "a1",
                "title": "Samsung HBM update",
                "snippet": "...",
                "entities": ["Samsung"],
                "terms": ["HBM"],
                "source_type": "media",
                "source_locale": "en",
                "source_domain": "reuters.com",
                "url": "https://www.reuters.com/technology/story?utm_source=search",
            },
            {
                "id": "a2",
                "title": "Samsung HBM qualification",
                "snippet": "...",
                "entities": ["Samsung"],
                "terms": ["HBM"],
                "source_type": "official",
                "source_locale": "ko",
                "source_domain": "samsung.com",
                "url": "https://m.samsung.com/news/story/",
            },
        ]

        result = build_cluster_object([0, 1], articles, "storage", 5, "2026-05-30")

        assert result["source_domains"] == ["reuters.com", "samsung.com"]
        assert result["canonical_urls"] == [
            "https://reuters.com/technology/story",
            "https://samsung.com/news/story",
        ]


class TestDomainId:
    def test_extracts_domain_id_from_domain_yaml_path(self):
        assert extract_domain_id("domains/storage/domain.yaml") == "storage"
        assert extract_domain_id("/repo/domains/robot/domain.yaml") == "robot"

    def test_accepts_plain_domain_id(self):
        assert extract_domain_id("storage") == "storage"
