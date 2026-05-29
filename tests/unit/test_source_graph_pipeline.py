"""Integration tests for pipeline.py — end-to-end evolution cycles."""

import json
import os
import yaml
from datetime import date, timedelta
from pathlib import Path

import pytest

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    NodeStatus, EntityType, TermType, ChannelType,
)
from extractor import SearchItem
from pipeline import evolve


@pytest.fixture
def domain_yaml(tmp_path):
    """Create a realistic domain.yaml for testing."""
    content = {
        "companies": [
            {"id": "samsung", "type": "COMPANY", "aliases": {"en": "Samsung Electronics", "zh-CN": "三星电子"}},
            {"id": "skhynix", "type": "COMPANY", "aliases": {"en": "SK hynix", "zh-CN": "SK海力士"}},
        ],
        "terms": [
            {"id": "hbm4", "type": "TECHNOLOGY", "aliases": {"en": "HBM4"}},
            {"id": "ddr5", "type": "TECHNOLOGY", "aliases": {"en": "DDR5"}},
        ],
        "channels": [
            {"id": "semiconductor_today", "type": "MEDIA", "url": "https://semiconductor-today.com", "reliability": 0.8},
        ],
    }
    path = tmp_path / "domain.yaml"
    with open(path, "w") as f:
        yaml.dump(content, f)
    return str(path)


@pytest.fixture
def graph_path(tmp_path):
    return str(tmp_path / "graph-state.json")


class TestPipelineFirstRun:
    """First-ever evolution run: graph initialized from seed."""

    def test_initializes_from_seed(self, domain_yaml, graph_path, tmp_path):
        items = [
            SearchItem(
                title="Samsung ships HBM4 to NVIDIA",
                url="https://semiconductor-today.com/samsung-hbm4",
                snippet="Samsung shipped HBM4 samples to NVIDIA Corp.",
                date="2025-06-15", engine="tavily", source_tier="B",
            ),
        ]
        result = evolve(
            domain="storage",
            domain_yaml_path=domain_yaml,
            graph_path=graph_path,
            search_items=items,
            run_date=date(2025, 6, 15),
            log_dir=str(tmp_path / "logs"),
        )

        graph = result["graph"]
        report = result["report"]

        # Seed entities should be present
        assert graph.has_entity("samsung")
        assert graph.has_entity("skhynix")
        assert graph.has_term("hbm4")
        assert graph.has_channel("semiconductor_today")

        # Seed nodes should be SEED status
        assert graph.get_entity("samsung").status == NodeStatus.SEED
        assert graph.get_term("hbm4").status == NodeStatus.SEED

        # Report should have extracted counts
        assert report["entities_extracted"] >= 0
        assert report["terms_extracted"] >= 0

        # Graph should be saved
        assert os.path.exists(graph_path)

        # Logs should be written
        assert os.path.exists(os.path.join(str(tmp_path), "logs", "discovery-report.ndjson"))

    def test_graph_persists_across_runs(self, domain_yaml, graph_path, tmp_path):
        """Second run loads saved graph, doesn't re-initialize."""
        run_date = date(2025, 6, 15)

        # First run
        items1 = [
            SearchItem(title="Samsung HBM4", url="https://a.com/1",
                       snippet="Samsung HBM4 production.", date="2025-06-15",
                       engine="tavily", source_tier="A"),
        ]
        evolve("storage", domain_yaml, graph_path, items1, run_date=run_date,
               log_dir=str(tmp_path / "logs"))

        # Second run — should load existing graph
        items2 = [
            SearchItem(title="SK hynix DDR5", url="https://b.com/1",
                       snippet="SK hynix DDR5 sampling.", date="2025-06-16",
                       engine="tavily", source_tier="A"),
        ]
        result = evolve("storage", domain_yaml, graph_path, items2,
                        run_date=date(2025, 6, 16), log_dir=str(tmp_path / "logs2"))

        # Should still have seed entities
        assert result["graph"].has_entity("samsung")


class TestWATCHToActiveUpgrade:
    """Verify WATCH→ACTIVE upgrade happens over multiple days."""

    def test_upgrade_after_sufficient_observations(self, domain_yaml, graph_path, tmp_path):
        """Run 3 days of observations → WATCH entity should become ACTIVE."""
        day1 = date(2025, 6, 1)

        # Day 1: initial run seeds graph — use a company name the regex extracts
        items = [
            SearchItem(title="Acme Corp HBM4 entry", url="https://a.com/1",
                       snippet="Acme Corp enters HBM4 market.",
                       date=day1.isoformat(), engine="tavily", source_tier="B"),
        ]
        result1 = evolve("storage", domain_yaml, graph_path, items,
                         run_date=day1, log_dir=str(tmp_path / "logs"))
        g1 = result1["graph"]

        newco_id = None
        for eid, node in g1.entities.items():
            if "Acme" in node.aliases.get("en", ""):
                newco_id = eid
                assert node.status == NodeStatus.WATCH
                break
        assert newco_id is not None, "Acme Corp entity should have been created"

        day2 = day1 + timedelta(days=1)
        items2 = [
            SearchItem(title="Acme Corp HBM4 update", url="https://a.com/2",
                       snippet="Acme Corp HBM4 sampling.", date=day2.isoformat(),
                       engine="tavily", source_tier="A"),
        ]
        evolve("storage", domain_yaml, graph_path, items2,
               run_date=day2, log_dir=str(tmp_path / "logs"))

        # Days 0-7: keep observing. On day 7 provide 3 articles for upgrade.
        for i in range(8):
            day = day1 + timedelta(days=i)
            if i >= 7:
                # Day 7+: provide 3 distinct URLs to trigger upgrade (obs ≥ 3)
                items_day = [
                    SearchItem(title=f"Acme Corp update {i}a", url=f"https://a.com/day{i}a",
                               snippet="Acme Corp HBM4 progress.", date=day.isoformat(),
                               engine="tavily", source_tier="B"),
                    SearchItem(title=f"Acme Corp update {i}b", url=f"https://b.com/day{i}b",
                               snippet="Acme Corp HBM4 milestone.", date=day.isoformat(),
                               engine="tavily", source_tier="B"),
                    SearchItem(title=f"Acme Corp update {i}c", url=f"https://c.com/day{i}c",
                               snippet="Acme Corp HBM4 sampling.", date=day.isoformat(),
                               engine="tavily", source_tier="A"),
                ]
            else:
                items_day = [
                    SearchItem(title=f"Acme Corp update {i}", url=f"https://a.com/day{i}",
                               snippet="Acme Corp HBM4 progress.", date=day.isoformat(),
                               engine="tavily", source_tier="B"),
                ]
            evolve("storage", domain_yaml, graph_path, items_day,
                   run_date=day, log_dir=str(tmp_path / "logs"))

        # After day 8, Acme Corp should be ACTIVE (≥7 days since first_seen, ≥3 obs)
        final_graph = SourceGraph.load(graph_path)
        newco = final_graph.get_entity(newco_id)
        assert newco.status == NodeStatus.ACTIVE, \
            f"Expected ACTIVE, got {newco.status.value}"


class TestEdgeBuilding:
    def test_builds_entity_term_edges(self, domain_yaml, graph_path, tmp_path):
        items = [
            SearchItem(title="Samsung HBM4 breakthrough", url="https://a.com/1",
                       snippet="Samsung Electronics announced HBM4 production milestone.",
                       date="2025-06-15", engine="tavily", source_tier="A"),
        ]
        result = evolve("storage", domain_yaml, graph_path, items,
                        run_date=date(2025, 6, 15), log_dir=str(tmp_path / "logs"))

        # Should have mention edge: samsung → hbm4
        mentions = [e for e in result["graph"].mentions
                    if e.source == "samsung" and e.target == "hbm4"]
        assert len(mentions) == 1


class TestChannelTracking:
    def test_new_channel_discovered(self, domain_yaml, graph_path, tmp_path):
        items = [
            SearchItem(title="HBM4 news", url="https://newoutlet.com/article1",
                       snippet="HBM4 production news.", date="2025-06-15",
                       engine="tavily", source_tier="B"),
            SearchItem(title="HBM4 more", url="https://newoutlet.com/article2",
                       snippet="HBM4 updates.", date="2025-06-15",
                       engine="tavily", source_tier="B"),
        ]
        result = evolve("storage", domain_yaml, graph_path, items,
                        run_date=date(2025, 6, 15), log_dir=str(tmp_path / "logs"))

        report = result["report"]
        assert report["channels_extracted"] >= 1

    def test_channel_requires_confirmation(self, domain_yaml, graph_path, tmp_path):
        """Channels auto-upgrade to WATCH; WATCH→ACTIVE needs confirmation."""
        items = []
        for i in range(5):
            items.append(SearchItem(
                title=f"New channel article {i}",
                url=f"https://newblog.com/article{i}",
                snippet="Tech news content.",
                date="2025-06-15", engine="tavily", source_tier="B",
            ))
        result = evolve("storage", domain_yaml, graph_path, items,
                        run_date=date(2025, 6, 15), log_dir=str(tmp_path / "logs"))

        # Channel should be pending confirmation, not auto-activated
        report = result["report"]
        # New channels start as WATCH and never auto-upgrade to ACTIVE
        for c_added in report["channels_added"]:
            node = result["graph"].get_channel(c_added["id"])
            assert node.status != NodeStatus.ACTIVE  # must be WATCH


class TestReportStructure:
    def test_report_has_all_fields(self, domain_yaml, graph_path, tmp_path):
        items = [
            SearchItem(title="Samsung HBM4", url="https://a.com/1",
                       snippet="Samsung HBM4.", date="2025-06-15",
                       engine="tavily", source_tier="A"),
        ]
        result = evolve("storage", domain_yaml, graph_path, items,
                        run_date=date(2025, 6, 15), log_dir=str(tmp_path / "logs"))

        report = result["report"]
        required = [
            "entities_extracted", "terms_extracted", "channels_extracted",
            "entities_upgraded", "entities_added",
            "terms_upgraded", "terms_added",
            "channels_upgraded", "channels_added",
            "channels_pending_confirmation", "queries_generated",
        ]
        for key in required:
            assert key in report, f"Missing report field: {key}"

    def test_graph_and_queries_returned(self, domain_yaml, graph_path, tmp_path):
        items = [
            SearchItem(title="Samsung HBM4", url="https://a.com/1",
                       snippet="Samsung HBM4.", date="2025-06-15",
                       engine="tavily", source_tier="A"),
        ]
        result = evolve("storage", domain_yaml, graph_path, items,
                        run_date=date(2025, 6, 15))

        assert "graph" in result
        assert "new_queries" in result
        assert "report" in result
        assert isinstance(result["graph"], SourceGraph)
        assert isinstance(result["new_queries"], list)
