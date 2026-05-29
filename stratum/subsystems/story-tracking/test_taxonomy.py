"""Tests for taxonomy loader."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import tempfile
import pytest
import yaml

from taxonomy import Taxonomy, load_taxonomy


@pytest.fixture
def sample_taxonomy():
    """Create a temporary taxonomy.yaml."""
    data = {
        "topics": [
            {"id": "hbm", "label": "HBM", "aliases": ["HBM3", "HBM4", "High Bandwidth Memory"]},
            {"id": "ddr5", "label": "DDR5", "aliases": ["DDR5 SDRAM"]},
            {"id": "memory-interface", "label": "Memory Interface", "aliases": ["DRAM interface"],
             "parent": None, "description": "parent node"},
        ],
        "entities": [
            {"id": "samsung", "label": "Samsung", "type": "company",
             "aliases": ["SEC", "三星", "三星电子"]},
            {"id": "sk-hynix", "label": "SK Hynix", "type": "company",
             "aliases": ["SK하이닉스", "海力士"]},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    yield path
    os.unlink(path)


class TestTaxonomy:
    def test_normalize_topic_known(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.normalize_topic("HBM3") == "hbm"
        assert tax.normalize_topic("High Bandwidth Memory") == "hbm"

    def test_normalize_topic_unknown(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.normalize_topic("bogus-topic") == "bogus-topic"

    def test_normalize_entity_known(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.normalize_entity("三星") == "samsung"
        assert tax.normalize_entity("海力士") == "sk-hynix"

    def test_normalize_entity_unknown(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.normalize_entity("Unknown Corp") == "Unknown Corp"

    def test_case_insensitive(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.normalize_topic("hbm3") == "hbm"
        assert tax.normalize_topic("Hbm4") == "hbm"

    def test_is_known(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.is_known_topic("hbm") is True
        assert tax.is_known_topic("bogus") is False
        assert tax.is_known_entity("SEC") is True

    def test_unknown_detection(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        unknown_t = tax.unknown_topics(["hbm", "unknown-topic", "ddr5"])
        assert unknown_t == ["unknown-topic"]
        unknown_e = tax.unknown_entities(["samsung", "Intel"])
        assert unknown_e == ["Intel"]

    def test_missing_file(self):
        tax = Taxonomy("/nonexistent/path.yaml")
        assert tax.is_known_topic("hbm") is False
        assert tax.normalize_topic("hbm") == "hbm"

    def test_topic_parent_not_set(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        # hbm and ddr5 don't have parent in test data
        assert tax.topic_parent("hbm") is None

    def test_topic_ancestors(self, sample_taxonomy):
        tax = Taxonomy(sample_taxonomy)
        assert tax.topic_ancestors("hbm") == []
