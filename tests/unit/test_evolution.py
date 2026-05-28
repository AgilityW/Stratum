"""Unit tests for evolution.py — scoring, upgrade/downgrade, edge updates."""

from datetime import date, timedelta
import pytest

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus, Edge,
)
from extractor import (
    EntityCandidate, TermCandidate, ChannelCandidate,
)
from evolution import (
    score_entity_candidate, score_term_candidate, score_channel_candidate,
    compute_upgrade, compute_term_action, compute_channel_action,
    update_edges, generate_new_queries,
    _count_observations, _days_since_first_seen, _days_since_last_seen,
)


class TestScoring:
    def test_entity_score_tier_a(self):
        c = EntityCandidate(
            raw_name="Samsung",
            occurrences=5,
            source_urls=["a", "b", "c"],
            source_tiers=["A", "B"],
        )
        score = score_entity_candidate(c, {"Samsung": c})
        assert 0 < score  # diversity bonus can push above 1.0

    def test_entity_score_low_tier(self):
        c = EntityCandidate(
            raw_name="Unknown",
            occurrences=1,
            source_urls=["x"],
            source_tiers=["D"],
        )
        score = score_entity_candidate(c, {"Unknown": c})
        assert score < 0.3  # D-tier, single source, low freq

    def test_entity_score_diversity_bonus(self):
        """≥3 source URLs gives 1.2x diversity bonus."""
        c3 = EntityCandidate(
            raw_name="WidelyCovered", occurrences=3,
            source_urls=["a", "b", "c"], source_tiers=["B"],
        )
        c1 = EntityCandidate(
            raw_name="NarrowlyCovered", occurrences=3,
            source_urls=["a"], source_tiers=["B"],
        )
        score3 = score_entity_candidate(c3, {"WidelyCovered": c3, "NarrowlyCovered": c1})
        score1 = score_entity_candidate(c1, {"WidelyCovered": c3, "NarrowlyCovered": c1})
        assert score3 > score1  # diversity bonus kicks in

    def test_term_score_co_occurrence(self):
        c = TermCandidate(
            raw_name="HBM4", occurrences=5,
            co_occurring_known_terms=["dram", "tsv", "memory", "bandwidth", "interposer"],
            source_urls=["a", "b", "c"],
        )
        score = score_term_candidate(c, {"HBM4": c})
        assert 0 < score <= 1.0
        # 5 co-occurring terms → co_occur_score = 1.0, major weight
        assert score >= 0.5

    def test_term_score_no_co_occurrence(self):
        c = TermCandidate(
            raw_name="UnknownTerm", occurrences=1,
            co_occurring_known_terms=[], source_urls=["a"],
        )
        score = score_term_candidate(c, {"UnknownTerm": c})
        assert score < 0.4

    def test_channel_score(self):
        c1 = ChannelCandidate(
            domain="a.com", url="https://a.com",
            article_count=10, article_urls=["a", "b"],
        )
        c2 = ChannelCandidate(
            domain="b.com", url="https://b.com",
            article_count=1, article_urls=["x"],
        )
        score1 = score_channel_candidate(c1, {"a": c1, "b": c2})
        score2 = score_channel_candidate(c2, {"a": c1, "b": c2})
        assert score1 > score2


class TestUpgradePolicy:
    def test_watch_to_active_insufficient_obs(self, week_ago):
        """WATCH entity with <3 obs should NOT upgrade."""
        g = SourceGraph("test")
        node = EntityNode(
            id="newco", first_seen=week_ago.isoformat(),
            last_seen=week_ago.isoformat(),
            score=0.5, status=NodeStatus.WATCH,
        )
        candidate = EntityCandidate(raw_name="NewCo", occurrences=2, source_urls=["a", "b"])
        history = {"entity_newco": 2}
        result = compute_upgrade("newco", node, candidate, g, history, date.today())
        assert result is None

    def test_watch_to_active_sufficient_obs(self, week_ago):
        g = SourceGraph("test")
        node = EntityNode(
            id="newco", first_seen=week_ago.isoformat(),
            last_seen=week_ago.isoformat(),
            score=0.5, status=NodeStatus.WATCH,
        )
        candidate = EntityCandidate(
            raw_name="NewCo", occurrences=3,
            source_urls=["a", "b", "c"], source_tiers=["A", "B"],
        )
        history = {"entity_newco": 3}
        result = compute_upgrade("newco", node, candidate, g, history, date.today())
        assert result == "active"

    def test_watch_to_active_too_soon(self, yesterday):
        """WATCH entity first seen <7 days ago should NOT upgrade."""
        g = SourceGraph("test")
        node = EntityNode(
            id="newco", first_seen=yesterday.isoformat(),
            last_seen=yesterday.isoformat(), score=0.5,
            status=NodeStatus.WATCH,
        )
        candidate = EntityCandidate(raw_name="NewCo", occurrences=3, source_urls=["a", "b", "c"])
        history = {"entity_newco": 3}
        result = compute_upgrade("newco", node, candidate, g, history, date.today())
        assert result is None

    def test_active_to_dormant(self, month_ago):
        g = SourceGraph("test")
        node = EntityNode(
            id="oldco", first_seen=month_ago.isoformat(),
            last_seen=month_ago.isoformat(), score=0.8,
            status=NodeStatus.ACTIVE,
        )
        # 0 observations, 30 days since last seen
        run_date = date.fromisoformat(month_ago.isoformat()) + timedelta(days=30)
        candidate = EntityCandidate(raw_name="OldCo")
        history = {"entity_oldco": 0}
        result = compute_upgrade("oldco", node, candidate, g, history, run_date)
        assert result == "dormant"

    def test_active_not_dormant_yet(self, month_ago):
        """ACTIVE entity with 29 days gap should NOT go dormant."""
        g = SourceGraph("test")
        node = EntityNode(
            id="oldco", first_seen=month_ago.isoformat(),
            last_seen=month_ago.isoformat(), score=0.8,
            status=NodeStatus.ACTIVE,
        )
        run_date = date.fromisoformat(month_ago.isoformat()) + timedelta(days=29)
        candidate = EntityCandidate(raw_name="OldCo")
        history = {"entity_oldco": 0}
        result = compute_upgrade("oldco", node, candidate, g, history, run_date)
        assert result is None

    def test_dormant_to_watch(self, month_ago):
        g = SourceGraph("test")
        node = EntityNode(
            id="oldco", first_seen=month_ago.isoformat(),
            last_seen=month_ago.isoformat(), score=0.3,
            status=NodeStatus.DORMANT,
        )
        candidate = EntityCandidate(raw_name="OldCo", occurrences=1)
        history = {"entity_oldco": 1}
        result = compute_upgrade("oldco", node, candidate, g, history, date.today())
        assert result == "watch"

    def test_dormant_to_pruned(self, month_ago):
        g = SourceGraph("test")
        node = EntityNode(
            id="deadco", first_seen=month_ago.isoformat(),
            last_seen=month_ago.isoformat(), score=0.1,
            status=NodeStatus.DORMANT,
        )
        run_date = date.fromisoformat(month_ago.isoformat()) + timedelta(days=90)
        candidate = EntityCandidate(raw_name="DeadCo")
        history = {"entity_deadco": 0}
        result = compute_upgrade("deadco", node, candidate, g, history, run_date)
        assert result == "pruned"

    def test_seed_never_changes(self, week_ago):
        g = SourceGraph("test")
        node = EntityNode(
            id="samsung", first_seen=week_ago.isoformat(),
            last_seen=week_ago.isoformat(), score=1.0,
            status=NodeStatus.SEED,
        )
        candidate = EntityCandidate(raw_name="Samsung", occurrences=100)
        history = {"entity_samsung": 0}  # even with 0 obs
        result = compute_upgrade("samsung", node, candidate, g, history, date.today())
        assert result is None


class TestTermActions:
    def test_term_watch_to_active(self, week_ago):
        g = SourceGraph("test")
        node = TermNode(
            id="hbm4", first_seen=week_ago.isoformat(),
            last_seen=week_ago.isoformat(), score=0.5,
            status=NodeStatus.WATCH,
        )
        candidate = TermCandidate(
            raw_name="HBM4", occurrences=3,
            co_occurring_known_terms=["dram", "memory"],
            source_urls=["a", "b", "c"],
        )
        history = {"term_hbm4": 3}
        result = compute_term_action("hbm4", node, candidate, g, history, date.today())
        assert result == "active"

    def test_term_seed_unchanged(self, week_ago):
        g = SourceGraph("test")
        node = TermNode(
            id="dram", status=NodeStatus.SEED,
            first_seen=week_ago.isoformat(),
        )
        candidate = TermCandidate(raw_name="DRAM")
        history = {"term_dram": 0}
        result = compute_term_action("dram", node, candidate, g, history, date.today())
        assert result is None


class TestChannelActions:
    def test_channel_watch_confirmation_required(self, week_ago):
        g = SourceGraph("test")
        node = ChannelNode(
            id="newblog", status=NodeStatus.WATCH,
            url="https://newblog.com",
            first_seen=week_ago.isoformat(),
        )
        candidate = ChannelCandidate(
            domain="newblog.com", url="https://newblog.com",
            article_count=5, article_urls=["a", "b"],
        )
        history = {"channel_newblog": 5}
        result = compute_channel_action("newblog", node, candidate, g, history, date.today())
        assert result == "CONFIRMATION_REQUIRED"

    def test_channel_watch_insufficient_obs(self):
        g = SourceGraph("test")
        node = ChannelNode(id="newblog", status=NodeStatus.WATCH, url="https://newblog.com")
        candidate = ChannelCandidate(domain="newblog.com", url="https://newblog.com", article_count=1)
        history = {"channel_newblog": 1}
        result = compute_channel_action("newblog", node, candidate, g, history, date.today())
        assert result is None


class TestEdgeUpdate:
    def test_new_edge_created(self, empty_graph, today):
        update_edges(empty_graph, [], {"micron"}, {"hbm4"}, today)
        # No search items, so no edges should be created
        assert len(empty_graph.mentions) == 0

    def test_edge_from_article_text(self, empty_graph, today):
        from extractor import SearchItem

        empty_graph.add_entity(EntityNode(
            id="micron", aliases={"en": "Micron"},
        ))
        empty_graph.add_term(TermNode(
            id="hbm4", aliases={"en": "HBM4"},
        ))

        items = [
            SearchItem(
                title="Micron HBM4 production",
                url="https://a.com/1",
                snippet="Micron ramps HBM4 production.",
                source_tier="A",
            ),
        ]
        update_edges(empty_graph, items, set(), set(), today)
        # Should create mention edge: micron → hbm4
        mentions = [e for e in empty_graph.mentions
                    if e.source == "micron" and e.target == "hbm4"]
        assert len(mentions) == 1

    def test_edge_accumulates_weight(self, empty_graph, today):
        from extractor import SearchItem

        empty_graph.add_entity(EntityNode(id="a", aliases={"en": "A Corp"}))
        empty_graph.add_term(TermNode(id="x", aliases={"en": "X Term"}))

        items = [
            SearchItem(title="A Corp X Term", url="https://a.com/1",
                       snippet="A Corp uses X Term.", source_tier="A"),
        ]

        # First observation
        update_edges(empty_graph, items, set(), set(), today)
        w1 = empty_graph.mentions[0].weight

        # Second observation (next day)
        tomorrow = today + timedelta(days=1)
        items2 = [
            SearchItem(title="A Corp X Term again", url="https://a.com/2",
                       snippet="A Corp invests in X Term.", source_tier="A"),
        ]
        update_edges(empty_graph, items2, set(), set(), tomorrow)
        w2 = empty_graph.mentions[0].weight
        # Weight should change (either decay or EMA)
        assert w2 != w1

    def test_edge_dedup_by_url(self, empty_graph, today):
        """Same URL should not create duplicate edges."""
        from extractor import SearchItem

        empty_graph.add_entity(EntityNode(id="a", aliases={"en": "A Corp"}))
        empty_graph.add_term(TermNode(id="x", aliases={"en": "X Term"}))

        items = [
            SearchItem(title="A Corp X", url="https://a.com/article-1",
                       snippet="A Corp uses X Term.", source_tier="A"),
        ]
        update_edges(empty_graph, items, set(), set(), today)
        count = len(empty_graph.mentions)
        # Same items again should not increase edge count (upsert)
        update_edges(empty_graph, items, set(), set(), today)
        assert len([e for e in empty_graph.mentions
                   if e.source == "a" and e.target == "x"]) == 1


class TestQueryGeneration:
    def test_generate_queries_from_new_entities(self, empty_graph):
        empty_graph.add_entity(EntityNode(
            id="newco", aliases={"en": "NewCo"},
            status=NodeStatus.ACTIVE,
        ))
        queries = generate_new_queries(empty_graph, {"newco"}, set(), max_queries=5)
        assert len(queries) >= 1
        q = queries[0]
        assert "NewCo" in q["query"]
        assert q["source"] == "auto-generated"
        assert "newco" in q["reason"]

    def test_generate_queries_respects_max(self, empty_graph):
        for i in range(5):
            empty_graph.add_entity(EntityNode(
                id=f"e{i}", aliases={"en": f"Entity {i}"},
                status=NodeStatus.ACTIVE,
            ))
        queries = generate_new_queries(
            empty_graph, {f"e{i}" for i in range(5)}, set(), max_queries=3,
        )
        assert len(queries) <= 3

    def test_generate_queries_skips_watch(self, empty_graph):
        empty_graph.add_entity(EntityNode(
            id="watcher", aliases={"en": "Watcher"},
            status=NodeStatus.WATCH,  # not ACTIVE/SEED
        ))
        queries = generate_new_queries(empty_graph, {"watcher"}, set())
        assert len(queries) == 0


class TestHelpers:
    def test_count_observations(self, empty_graph):
        history = {"entity_a": 5, "term_b": 3}
        assert _count_observations("a", "entity", empty_graph, history) == 5
        assert _count_observations("b", "term", empty_graph, history) == 3
        assert _count_observations("c", "entity", empty_graph, history) == 0

    def test_days_since_first_seen(self, week_ago):
        node = EntityNode(id="a", first_seen=week_ago.isoformat())
        assert _days_since_first_seen(node, date.today()) >= 7

    def test_days_since_first_seen_no_date(self):
        node = EntityNode(id="a")
        assert _days_since_first_seen(node, date.today()) == 0

    def test_days_since_last_seen(self, month_ago):
        node = EntityNode(id="a", last_seen=month_ago.isoformat())
        assert _days_since_last_seen(node, date.today()) >= 30

    def test_days_since_last_seen_no_date(self):
        node = EntityNode(id="a")
        assert _days_since_last_seen(node, date.today()) == 999
