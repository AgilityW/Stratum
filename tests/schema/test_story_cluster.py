"""Schema validation tests for StoryCluster."""

import json
import jsonschema
import pytest


@pytest.fixture
def cluster_schema(schemas_dir):
    schema_path = schemas_dir / "story-cluster.schema.json"
    with open(schema_path) as f:
        return json.load(f)


class TestStoryClusterRequired:
    def test_all_required_fields(self, cluster_schema):
        valid = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "HBM4 Production Update",
            "article_ids": ["a001", "a002"],
            "novelty": "update",
            "confidence": "A",
        }
        jsonschema.validate(valid, cluster_schema)

    def test_missing_id_fails(self, cluster_schema):
        invalid = {
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "first_disclosure",
            "confidence": "B",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, cluster_schema)

    def test_empty_article_ids_fails(self, cluster_schema):
        invalid = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": [],  # minItems: 1
            "novelty": "first_disclosure",
            "confidence": "B",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, cluster_schema)


class TestStoryClusterValidation:
    def test_valid_full_record(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "HBM4 Enters Mass Production at Multiple Vendors",
            "article_ids": ["a001", "a002", "a003"],
            "source_urls": [
                "https://news.skhynix.com/hbm4",
                "https://semiconductor-today.com/samsung-hbm4",
            ],
            "canonical_summary": "Samsung and SK hynix both advance HBM4 production.",
            "confirmed_claims": ["HBM4 is in mass production at SK hynix"],
            "disputed_claims": [],
            "repeated_claims": ["HBM4 has 1.5TB/s bandwidth"],
            "new_claims": ["Samsung 36GB HBM4 variant"],
            "novelty": "update",
            "confidence": "A",
            "impact_tags": ["supply", "technology"],
            "linked_entities": ["samsung", "skhynix"],
            "linked_terms": ["hbm4"],
            "source_diversity": "high",
            "update_type": "quantification",
            "linked_event_thread_id": None,
        }
        jsonschema.validate(record, cluster_schema)

    def test_invalid_id_pattern(self, cluster_schema):
        record = {
            "id": "cluster-001",  # doesn't match sc-YYYY-MM-DD-NNN
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "update",
            "confidence": "A",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, cluster_schema)

    def test_valid_novelty_values(self, cluster_schema):
        for nov in ["first_disclosure", "update", "rehash", "rumor", "confirmation", "contradiction"]:
            record = {
                "id": "sc-2025-06-15-001",
                "date": "2025-06-15",
                "title": "Test",
                "article_ids": ["a001"],
                "novelty": nov,
                "confidence": "B",
            }
            jsonschema.validate(record, cluster_schema)

    def test_invalid_novelty(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "breaking",  # not in enum
            "confidence": "B",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, cluster_schema)

    def test_valid_confidence_values(self, cluster_schema):
        for conf in ["A", "B", "C", "D"]:
            record = {
                "id": "sc-2025-06-15-001",
                "date": "2025-06-15",
                "title": "Test",
                "article_ids": ["a001"],
                "novelty": "update",
                "confidence": conf,
            }
            jsonschema.validate(record, cluster_schema)

    def test_invalid_confidence(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "update",
            "confidence": "E",  # not in enum
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, cluster_schema)

    def test_valid_impact_tags(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "update",
            "confidence": "B",
            "impact_tags": ["price", "customer", "supply", "technology",
                            "competitor", "capital", "policy"],
        }
        jsonschema.validate(record, cluster_schema)

    def test_invalid_impact_tag(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "update",
            "confidence": "B",
            "impact_tags": ["celebrity"],  # not in enum
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(record, cluster_schema)

    def test_valid_source_diversity(self, cluster_schema):
        for div in ["low", "medium", "high"]:
            record = {
                "id": "sc-2025-06-15-001",
                "date": "2025-06-15",
                "title": "Test",
                "article_ids": ["a001"],
                "novelty": "update",
                "confidence": "B",
                "source_diversity": div,
            }
            jsonschema.validate(record, cluster_schema)

    def test_valid_update_types(self, cluster_schema):
        for ut in ["new_claim", "confirmation", "contradiction", "quantification",
                    "second_order_signal", "rehash", "background"]:
            record = {
                "id": "sc-2025-06-15-001",
                "date": "2025-06-15",
                "title": "Test",
                "article_ids": ["a001"],
                "novelty": "update",
                "confidence": "B",
                "update_type": ut,
            }
            jsonschema.validate(record, cluster_schema)

    def test_nullable_thread_id(self, cluster_schema):
        record = {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "Test",
            "article_ids": ["a001"],
            "novelty": "update",
            "confidence": "B",
            "linked_event_thread_id": None,
        }
        jsonschema.validate(record, cluster_schema)
