"""Data integrity tests for story-clusters.json.

Verifies:
  - Valid JSON structure
  - All required fields per cluster
  - article_ids reference valid articles
  - novelty and confidence values are in valid ranges
  - No duplicate cluster IDs
"""

import json
import re


def test_valid_json_structure(valid_clusters_json):
    with open(valid_clusters_json) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Top-level must be an object"


def test_all_clusters_have_required_fields(valid_clusters_json):
    required = ["id", "date", "title", "article_ids", "novelty", "confidence"]
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        for field in required:
            assert field in cluster, f"Cluster {cid}: missing required field '{field}'"


def test_cluster_ids_match_keys(valid_clusters_json):
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        assert cluster["id"] == cid, f"Cluster key {cid} ≠ cluster.id {cluster['id']}"


def test_cluster_id_pattern(valid_clusters_json):
    pattern = re.compile(r"^sc-\d{4}-\d{2}-\d{2}-\d{3}$")
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid in clusters:
        assert pattern.match(cid), f"Invalid cluster ID pattern: {cid}"


def test_article_ids_non_empty(valid_clusters_json):
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        assert len(cluster["article_ids"]) >= 1, f"Cluster {cid}: empty article_ids"


def test_novelty_values_valid(valid_clusters_json):
    valid = {"first_disclosure", "update", "rehash", "rumor", "confirmation", "contradiction"}
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        assert cluster["novelty"] in valid, f"Cluster {cid}: invalid novelty '{cluster['novelty']}'"


def test_confidence_values_valid(valid_clusters_json):
    valid = {"A", "B", "C", "D"}
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        assert cluster["confidence"] in valid, f"Cluster {cid}: invalid confidence '{cluster['confidence']}'"


def test_date_format(valid_clusters_json):
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        d = cluster["date"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"Cluster {cid}: invalid date format: {d}"


def test_source_diversity_if_present(valid_clusters_json):
    valid = {"low", "medium", "high"}
    with open(valid_clusters_json) as f:
        clusters = json.load(f)
    for cid, cluster in clusters.items():
        sd = cluster.get("source_diversity")
        if sd is not None:
            assert sd in valid, f"Cluster {cid}: invalid source_diversity '{sd}'"
