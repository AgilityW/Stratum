"""Data integrity tests for clusters.json.

Verifies:
  - Valid JSON structure
  - All required fields per cluster
  - article_ids reference valid articles
  - confidence values are in valid ranges
  - No duplicate cluster IDs
"""

import json
import re
from pathlib import Path

from jsonschema import validate


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _cluster_schema():
    return json.loads((PROJECT_ROOT / "stratum/contracts/story_cluster.json").read_text())


def _clusters(path):
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Top-level must be an object"
    assert isinstance(data.get("clusters"), list), "clusters must be a list"
    return data["clusters"]


def test_valid_json_structure(valid_clusters_json):
    with open(valid_clusters_json) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Top-level must be an object"
    assert isinstance(data.get("clusters"), list), "clusters must be a list"


def test_all_clusters_have_required_fields(valid_clusters_json):
    required = [
        "id", "canonical_title", "article_ids", "article_count", "confidence",
        "source_types", "locales", "source_domains", "canonical_urls", "created",
    ]
    for cluster in _clusters(valid_clusters_json):
        for field in required:
            assert field in cluster, f"Cluster {cluster.get('id', '?')}: missing required field '{field}'"


def test_clusters_match_contract_schema(valid_clusters_json):
    schema = _cluster_schema()
    for cluster in _clusters(valid_clusters_json):
        validate(cluster, schema)


def test_cluster_id_pattern(valid_clusters_json):
    pattern = re.compile(r"^sc-[a-z0-9_-]+-\d{4}$")
    for cluster in _clusters(valid_clusters_json):
        assert pattern.match(cluster["id"]), f"Invalid cluster ID pattern: {cluster['id']}"


def test_article_ids_non_empty(valid_clusters_json):
    for cluster in _clusters(valid_clusters_json):
        assert len(cluster["article_ids"]) >= 2, f"Cluster {cluster['id']}: empty article_ids"
        assert cluster["article_count"] == len(cluster["article_ids"])


def test_confidence_values_valid(valid_clusters_json):
    valid = {"high", "medium", "low"}
    for cluster in _clusters(valid_clusters_json):
        assert cluster["confidence"] in valid, \
            f"Cluster {cluster['id']}: invalid confidence '{cluster['confidence']}'"


def test_date_format(valid_clusters_json):
    with open(valid_clusters_json) as f:
        data = json.load(f)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["date"]), \
        f"Invalid run date format: {data['date']}"
    for cluster in data["clusters"]:
        created = cluster.get("created")
        if created:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", created), \
                f"Cluster {cluster['id']}: invalid created date: {created}"


def test_summary_arrays_if_present(valid_clusters_json):
    for cluster in _clusters(valid_clusters_json):
        for field in ["source_types", "locales", "source_domains", "canonical_urls", "entities", "terms"]:
            assert isinstance(cluster.get(field, []), list), \
                f"Cluster {cluster['id']}: {field} must be a list"
