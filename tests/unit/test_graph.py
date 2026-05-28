"""Unit tests for graph.py — data structures, CRUD, serialization."""

import json
import pytest
from datetime import date

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus, Edge,
)


class TestNodeStatus:
    def test_status_values(self):
        assert NodeStatus.SEED.value == "seed"
        assert NodeStatus.ACTIVE.value == "active"
        assert NodeStatus.WATCH.value == "watch"
        assert NodeStatus.DORMANT.value == "dormant"
        assert NodeStatus.PRUNED.value == "pruned"


class TestEntityNode:
    def test_create_minimal(self):
        node = EntityNode(id="nvidia")
        assert node.id == "nvidia"
        assert node.type == EntityType.COMPANY
        assert node.aliases == {}
        assert node.score == 0.0
        assert node.status == NodeStatus.WATCH

    def test_create_full(self, week_ago):
        node = EntityNode(
            id="cxmt", type=EntityType.COMPANY,
            aliases={"en": "CXMT", "zh-CN": "长鑫存储"},
            first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
            score=0.8, status=NodeStatus.ACTIVE,
        )
        assert node.id == "cxmt"
        assert node.aliases["zh-CN"] == "长鑫存储"
        assert node.score == 0.8
        assert node.status == NodeStatus.ACTIVE

    def test_to_dict(self):
        node = EntityNode(id="cxmt", aliases={"en": "CXMT"}, score=0.7)
        d = node.to_dict()
        assert d["aliases"] == {"en": "CXMT"}
        assert d["score"] == 0.7
        assert d["status"] == "watch"

    def test_from_dict(self):
        d = {"type": "COMPANY", "aliases": {"en": "CXMT"}, "score": 0.7, "status": "active"}
        node = EntityNode.from_dict("cxmt", d)
        assert node.id == "cxmt"
        assert node.type == EntityType.COMPANY
        assert node.score == 0.7
        assert node.status == NodeStatus.ACTIVE

    def test_from_dict_defaults(self):
        node = EntityNode.from_dict("test", {})
        assert node.status == NodeStatus.WATCH
        assert node.score == 0.0


class TestTermNode:
    def test_create_with_children(self):
        node = TermNode(
            id="hbm", type=TermType.TECHNOLOGY,
            aliases={"en": "HBM"},
            children=["hbm3", "hbm4"],
        )
        assert len(node.children) == 2
        assert "hbm4" in node.children

    def test_to_dict_includes_children(self):
        node = TermNode(id="dram", children=["ddr5", "ddr6"])
        d = node.to_dict()
        assert d["children"] == ["ddr5", "ddr6"]

    def test_to_dict_omits_empty_children(self):
        node = TermNode(id="dram")
        d = node.to_dict()
        assert "children" not in d

    def test_from_dict_with_children(self):
        d = {"type": "TECHNOLOGY", "aliases": {}, "children": ["hbm4"]}
        node = TermNode.from_dict("hbm", d)
        assert "hbm4" in node.children


class TestChannelNode:
    def test_create(self):
        node = ChannelNode(
            id="semiconductor_today", type=ChannelType.MEDIA,
            url="https://semiconductor-today.com", reliability=0.8,
        )
        assert node.reliability == 0.8
        assert node.js_rendered is False
        assert node.last_200 is True

    def test_to_dict(self):
        node = ChannelNode(id="test", url="https://example.com", reliability=0.6)
        d = node.to_dict()
        assert d["reliability"] == 0.6
        assert d["last_200"] is True

    def test_from_dict_defaults(self):
        node = ChannelNode.from_dict("test", {})
        assert node.reliability == 0.5
        assert node.last_200 is True


class TestEdge:
    def test_create(self):
        edge = Edge(source="samsung", target="hbm4", weight=0.8,
                    first_observed="2025-06-01", last_observed="2025-06-15")
        assert edge.weight == 0.8
        assert edge.source == "samsung"

    def test_to_dict(self):
        edge = Edge(source="a", target="b", weight=0.5)
        d = edge.to_dict()
        assert d["weight"] == 0.5

    def test_from_dict(self):
        d = {"source": "a", "target": "b", "weight": 0.5, "first_observed": "", "last_observed": ""}
        edge = Edge.from_dict(d)
        assert edge.weight == 0.5


class TestSourceGraph:
    def test_init(self):
        g = SourceGraph(domain="storage")
        assert g.domain == "storage"
        assert g.entities == {}
        assert g.terms == {}
        assert g.channels == {}

    def test_add_entity(self):
        g = SourceGraph("test")
        node = EntityNode(id="nvidia", aliases={"en": "NVIDIA"})
        g.add_entity(node)
        assert g.has_entity("nvidia")
        assert g.get_entity("nvidia").aliases["en"] == "NVIDIA"

    def test_add_term(self):
        g = SourceGraph("test")
        g.add_term(TermNode(id="hbm4", aliases={"en": "HBM4"}))
        assert g.has_term("hbm4")

    def test_add_channel(self):
        g = SourceGraph("test")
        g.add_channel(ChannelNode(id="techcrunch", url="https://techcrunch.com"))
        assert g.has_channel("techcrunch")

    def test_get_missing_returns_none(self, empty_graph):
        assert empty_graph.get_entity("nonexistent") is None
        assert empty_graph.get_term("nonexistent") is None
        assert empty_graph.get_channel("nonexistent") is None

    def test_find_entity_by_alias(self):
        g = SourceGraph("test")
        g.add_entity(EntityNode(id="samsung", aliases={"en": "Samsung Electronics", "zh-CN": "三星电子"}))
        assert g.find_entity_by_alias("Samsung Electronics") == "samsung"
        assert g.find_entity_by_alias("samSUNG electroNICS") == "samsung"  # case-insensitive
        assert g.find_entity_by_alias("三星电子") == "samsung"

    def test_find_entity_by_alias_not_found(self, empty_graph):
        assert empty_graph.find_entity_by_alias("NVIDIA") is None

    def test_find_term_by_alias(self):
        g = SourceGraph("test")
        g.add_term(TermNode(id="hbm4", aliases={"en": "HBM4"}))
        assert g.find_term_by_alias("HBM4") == "hbm4"

    def test_find_term_by_alias_exact_match_only(self):
        """find_term_by_alias uses exact match, not substring."""
        g = SourceGraph("test")
        g.add_term(TermNode(id="hbm4", aliases={"en": "HBM4"}))
        assert g.find_term_by_alias("HBM4 memory") is None

    def test_add_edge_mention(self, empty_graph, today):
        empty_graph.add_edge_mention("samsung", "hbm4", weight=0.8, date_str=today.isoformat())
        assert len(empty_graph.mentions) == 1
        edge = empty_graph.mentions[0]
        assert edge.source == "samsung"
        assert edge.target == "hbm4"
        assert edge.weight == 0.8

    def test_add_edge_co_occur(self, empty_graph):
        empty_graph.add_edge_co_occur("hbm4", "cowos", weight=0.5)
        assert len(empty_graph.co_occurs) == 1

    def test_add_edge_publishes(self, empty_graph):
        empty_graph.add_edge_publishes("samsung", "samsung_newsroom")
        assert len(empty_graph.publishes_on) == 1

    def test_add_edge_covers(self, empty_graph):
        empty_graph.add_edge_covers("semiconductor_today", "hbm4")
        assert len(empty_graph.covers) == 1

    def test_active_entities(self):
        g = SourceGraph("test")
        g.add_entity(EntityNode(id="seed", status=NodeStatus.SEED))
        g.add_entity(EntityNode(id="active", status=NodeStatus.ACTIVE))
        g.add_entity(EntityNode(id="watch", status=NodeStatus.WATCH))
        active = g.active_entities
        assert len(active) == 2
        assert {e.id for e in active} == {"seed", "active"}

    def test_watch_entities(self):
        g = SourceGraph("test")
        g.add_entity(EntityNode(id="active", status=NodeStatus.ACTIVE))
        g.add_entity(EntityNode(id="watch1", status=NodeStatus.WATCH))
        g.add_entity(EntityNode(id="watch2", status=NodeStatus.WATCH))
        watches = g.watch_entities
        assert len(watches) == 2

    def test_active_terms(self):
        g = SourceGraph("test")
        g.add_term(TermNode(id="seed", status=NodeStatus.SEED))
        g.add_term(TermNode(id="watch", status=NodeStatus.WATCH))
        assert len(g.active_terms) == 1

    def test_summary(self, empty_graph):
        empty_graph.add_entity(EntityNode(id="a"))
        empty_graph.add_term(TermNode(id="b"))
        s = empty_graph.summary()
        assert "storage" in s
        assert "1E/1T/0C" in s

    # ── Serialization ────────────────────────────────────

    def test_to_dict_empty(self):
        g = SourceGraph("test")
        d = g.to_dict()
        assert d["domain"] == "test"
        assert d["nodes"]["entities"] == {}
        assert d["edges"]["mentions"] == []

    def test_to_dict_full(self, seeded_graph):
        d = seeded_graph.to_dict()
        assert len(d["nodes"]["entities"]) >= 3
        assert len(d["nodes"]["terms"]) >= 2
        assert d["meta"]["total_entities"] >= 3

    def test_save_and_load(self, seeded_graph, tmp_dir):
        path = str(tmp_dir / "graph-test.json")
        seeded_graph.save(path)
        loaded = SourceGraph.load(path)
        assert loaded.domain == seeded_graph.domain
        assert loaded.has_entity("samsung")
        assert loaded.has_term("hbm4")
        assert loaded.get_entity("samsung").status == NodeStatus.SEED

    def test_load_nonexistent_raises(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            SourceGraph.load(str(tmp_dir / "does_not_exist.json"))

    def test_empty_classmethod(self):
        g = SourceGraph.empty("ai")
        assert g.domain == "ai"
        assert g.entities == {}

    def test_roundtrip_preserves_edge_weights(self, empty_graph, today):
        empty_graph.add_edge_mention("a", "b", weight=0.75, date_str=today.isoformat())
        path = str(empty_graph.save.__defaults__)  # can't use this
        # Use tmp path instead
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            empty_graph.save(f.name)
            loaded = SourceGraph.load(f.name)
        assert loaded.mentions[0].weight == 0.75
