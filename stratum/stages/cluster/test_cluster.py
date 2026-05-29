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
