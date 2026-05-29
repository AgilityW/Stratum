"""
Evolution engine — score, filter, upgrade graph nodes and edges.

Takes the current graph + today's candidate extractions,
applies scoring and upgrade policies, produces the evolved graph.

Policy rules:
  - SEED nodes: never auto-downgraded
  - watch → active: ≥3 observations across ≥7 days, score ≥0.2
  - active → dormant: 0 observations for ≥30 days
  - dormant → watch: 1 new observation after dormant
  - dormant → pruned: ≥90 days dormant

Channel auto-upgrade REQUIRES confirmation (held for human).
Entity alias merge is candidate-only (held for human).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, timedelta
from math import log
from typing import Optional
from urllib.parse import urlparse

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus, Edge,
)
from extractor import (
    SearchItem, EntityCandidate, TermCandidate, ChannelCandidate,
    EntityExtractor, TermExtractor, ChannelExtractor,
)

# ── Scoring ────────────────────────────────────────────────

def score_entity_candidate(c: EntityCandidate, all_candidates: dict) -> float:
    """Score: normalized frequency × source reliability factor."""
    max_occ = max((x.occurrences for x in all_candidates.values()), default=1)
    freq_score = c.occurrences / max_occ

    # Source reliability: A=1.0, B=0.7, C=0.4, D=0.15
    tier_weights = {"A": 1.0, "B": 0.7, "C": 0.4, "D": 0.15}
    max_tier_weight = max((tier_weights.get(t, 0.15) for t in c.source_tiers), default=0.15)
    reliability = max_tier_weight * min(len(c.source_tiers) / 2, 1.0)

    # Diversity bonus: appearing in ≥3 independent sources
    diversity_bonus = 1.2 if len(c.source_urls) >= 3 else 1.0

    return round(freq_score * reliability * diversity_bonus, 4)


def score_term_candidate(c: TermCandidate, all_candidates: dict) -> float:
    """Score: co-occurrence density with known terms × source diversity."""
    max_occ = max((x.occurrences for x in all_candidates.values()), default=1)
    freq_score = c.occurrences / max_occ

    # Co-occurrence: how many known terms appear alongside this one
    co_occur_score = min(len(c.co_occurring_known_terms) / 5, 1.0)

    # Source diversity
    source_diversity = min(len(c.source_urls) / 3, 1.0)

    return round(freq_score * 0.3 + co_occur_score * 0.5 + source_diversity * 0.2, 4)


def score_channel_candidate(c: ChannelCandidate, all_candidates: dict) -> float:
    """Score: article frequency normalized to weekly pace × uniqueness."""
    max_articles = max((x.article_count for x in all_candidates.values()), default=1)
    freq_score = c.article_count / max_articles

    # Uniqueness: prefer domains with original content vs aggregators
    uniqueness = 0.8  # default; could be refined with content analysis

    return round(freq_score * 0.6 + uniqueness * 0.4, 4)


# ── Upgrade Policy ─────────────────────────────────────────

def compute_upgrade(entity_id: str, node: EntityNode,
                    candidate: EntityCandidate,
                    graph: SourceGraph,
                    history: dict,
                    run_date: date) -> Optional[str]:
    """Determine if a node should be upgraded/downgraded. Returns new status or None."""

    if node.status == NodeStatus.SEED:
        return None  # never touch seeds

    if node.status == NodeStatus.WATCH:
        obs = _count_observations(entity_id, "entity", graph, history)
        days = _days_since_first_seen(node, run_date)
        score = score_entity_candidate(candidate, {})
        if obs >= 3 and days >= 7 and score >= 0.2:
            return NodeStatus.ACTIVE.value
        return None

    if node.status == NodeStatus.ACTIVE:
        obs = _count_observations(entity_id, "entity", graph, history)
        if obs == 0 and _days_since_last_seen(node, run_date) >= 30:
            return NodeStatus.DORMANT.value
        return None

    if node.status == NodeStatus.DORMANT:
        obs = _count_observations(entity_id, "entity", graph, history)
        if obs >= 1:
            return NodeStatus.WATCH.value
        if _days_since_last_seen(node, run_date) >= 90:
            return NodeStatus.PRUNED.value
        return None

    return None


def compute_term_action(term_id: str, node: TermNode,
                        candidate: TermCandidate,
                        graph: SourceGraph,
                        history: dict,
                        run_date: date) -> Optional[str]:
    """Independent upgrade logic for terms — uses term-specific scoring."""
    if node.status == NodeStatus.SEED:
        return None

    if node.status == NodeStatus.WATCH:
        obs = _count_observations(term_id, "term", graph, history)
        days = _days_since_first_seen(node, run_date)
        score = score_term_candidate(candidate, {})
        if obs >= 3 and days >= 7 and score >= 0.2:
            return NodeStatus.ACTIVE.value
        return None

    if node.status == NodeStatus.ACTIVE:
        obs = _count_observations(term_id, "term", graph, history)
        if obs == 0 and _days_since_last_seen(node, run_date) >= 30:
            return NodeStatus.DORMANT.value
        return None

    if node.status == NodeStatus.DORMANT:
        obs = _count_observations(term_id, "term", graph, history)
        if obs >= 1:
            return NodeStatus.WATCH.value
        if _days_since_last_seen(node, run_date) >= 90:
            return NodeStatus.PRUNED.value
        return None

    return None


def compute_channel_action(channel_id: str, node: ChannelNode,
                           candidate: ChannelCandidate,
                           graph: SourceGraph,
                           history: dict,
                           run_date: date) -> Optional[str]:
    """Channel upgrade has extra guard: auto-upgrade to WATCH only.
    WATCH→ACTIVE requires human confirmation."""

    if node.status == NodeStatus.SEED:
        return None

    if node.status == NodeStatus.WATCH:
        # Channels: auto-upgrade is NOT allowed.
        # Return a special marker that means "confirmation required"
        obs = _count_observations(channel_id, "channel", graph, history)
        score = score_channel_candidate(candidate, {})
        if obs >= 2 and score >= 0.3:
            return "CONFIRMATION_REQUIRED"  # human must approve
        return None

    if node.status == NodeStatus.ACTIVE:
        obs = _count_observations(channel_id, "channel", graph, history)
        if obs == 0 and _days_since_last_seen(node, run_date) >= 30:
            return NodeStatus.DORMANT.value
        return None

    if node.status == NodeStatus.DORMANT:
        obs = _count_observations(channel_id, "channel", graph, history)
        if obs >= 1:
            return NodeStatus.WATCH.value
        if _days_since_last_seen(node, run_date) >= 90:
            return NodeStatus.PRUNED.value
        return None

    return None


# ── Edge Evolution ─────────────────────────────────────────

def update_edges(graph: SourceGraph, items: list[SearchItem],
                 new_entity_ids: set[str], new_term_ids: set[str],
                 run_date: date) -> None:
    """Build/update edges between entities, terms, and channels from today's articles."""
    today_str = _to_date_str(run_date)

    # Group items by article (rough dedup by URL domain+path)
    articles: dict[str, SearchItem] = {}
    for item in items:
        parsed = urlparse(item.url)
        key = parsed.netloc + parsed.path
        if key not in articles:
            articles[key] = item

    for article in articles.values():
        text = f"{article.title} {article.snippet}"

        # Entity → Term mentions
        for eid in list(graph.entities.keys()) + list(new_entity_ids):
            node = graph.get_entity(eid)
            if not node:
                continue
            for alias in node.aliases.values():
                if alias.lower() in text.lower():
                    for tid in list(graph.terms.keys()) + list(new_term_ids):
                        tnode = graph.get_term(tid)
                        if not tnode:
                            continue
                        for talias in tnode.aliases.values():
                            if talias.lower() in text.lower() and talias.lower() != alias.lower():
                                _upsert_edge(graph.mentions, eid, tid,
                                             weight=1.0, date_str=today_str)
                                break
                    break

        # Term → Term co-occurrence
        found_terms = []
        for tid in list(graph.terms.keys()) + list(new_term_ids):
            tnode = graph.get_term(tid)
            if not tnode:
                continue
            for talias in tnode.aliases.values():
                if talias.lower() in text.lower():
                    found_terms.append(tid)
                    break
        for i, t1 in enumerate(found_terms):
            for t2 in found_terms[i+1:]:
                _upsert_edge(graph.co_occurs, t1, t2,
                             weight=1.0, date_str=today_str)


def _upsert_edge(edges: list[Edge], source: str, target: str,
                 weight: float = 1.0, date_str: str = "") -> None:
    """Update existing edge or add new one. Applies exponential decay."""
    half_life_days = 14  # MENTIONS edges
    if edges is not None:
        # Determine half-life based on edge type context
        pass  # half-life set above

    for e in edges:
        if e.source == source and e.target == target:
            # Apply exponential decay to historical weight
            if e.last_observed and date_str:
                try:
                    ld = date.fromisoformat(e.last_observed)
                    nd = date.fromisoformat(date_str)
                    days = (nd - ld).days
                    decay = 0.5 ** (days / half_life_days) if days > 0 else 1.0
                    e.weight = round(e.weight * decay, 4)
                except (ValueError, TypeError):
                    pass
            # Merge new observation via exponential moving average
            e.weight = round(e.weight * 0.7 + weight * 0.3, 4)
            e.last_observed = date_str
            return

    edges.append(Edge(
        source=source, target=target,
        weight=weight, first_observed=date_str, last_observed=date_str))


def _decay_all_edges(graph: SourceGraph, run_date: date) -> None:
    """Apply time-based decay to all edges. Called once per evolution cycle."""

    for edge_list, half_life in [
        (graph.mentions, 14),
        (graph.co_occurs, 30),
        (graph.publishes_on, 30),
        (graph.covers, 14),
    ]:
        for e in edge_list:
            if e.last_observed:
                try:
                    ld = date.fromisoformat(e.last_observed)
                    days = (run_date - ld).days
                    if days > 0:
                        decay = 0.5 ** (days / half_life)
                        e.weight = round(e.weight * decay, 4)
                except (ValueError, TypeError):
                    pass


# ── Query Generation ───────────────────────────────────────

def generate_new_queries(graph: SourceGraph,
                         new_entities: set[str],
                         new_terms: set[str],
                         max_queries: int = 5) -> list[dict]:
    """Generate search queries for newly activated nodes."""

    queries = []
    active_entities = [eid for eid in new_entities
                       if graph.get_entity(eid) and
                       graph.get_entity(eid).status in (NodeStatus.SEED, NodeStatus.ACTIVE)]
    active_terms = [tid for tid in new_terms
                    if graph.get_term(tid) and
                    graph.get_term(tid).status in (NodeStatus.SEED, NodeStatus.ACTIVE)]

    for eid in active_entities[:3]:
        node = graph.get_entity(eid)
        en_name = node.aliases.get("en", eid)
        # Pair with top 2 co-occurring terms
        related_terms = []
        for edge in graph.mentions:
            if edge.source == eid:
                related_terms.append((edge.target, edge.weight))
        related_terms.sort(key=lambda x: x[1], reverse=True)
        top_terms = [t[0] for t in related_terms[:2]]
        term_str = " ".join(top_terms) if top_terms else ""
        queries.append({
            "query": f"{en_name} {term_str} latest".strip(),
            "locale": "en",
            "source": "auto-generated",
            "reason": f"new entity: {eid}",
        })

    for tid in active_terms[:2]:
        node = graph.get_term(tid)
        en_name = node.aliases.get("en", tid)
        queries.append({
            "query": f"{en_name} latest",
            "locale": "en",
            "source": "auto-generated",
            "reason": f"new term: {tid}",
        })

    return queries[:max_queries]


# ── Helpers ────────────────────────────────────────────────

def _count_observations(node_id: str, node_type: str,
                        graph: SourceGraph, history: dict) -> int:
    """Count how many independent articles mention this node today."""
    return history.get(f"{node_type}_{node_id}", 0)


def _days_since_first_seen(node: EntityNode | TermNode | ChannelNode,
                            run_date: date) -> int:
    if not node.first_seen:
        return 0
    try:
        fd = date.fromisoformat(node.first_seen)
        return (run_date - fd).days
    except (ValueError, TypeError):
        return 0


def _days_since_last_seen(node: EntityNode | TermNode | ChannelNode,
                           run_date: date) -> int:
    if not node.last_seen:
        return 999
    try:
        ld = date.fromisoformat(node.last_seen)
        return (run_date - ld).days
    except (ValueError, TypeError):
        return 999


def _to_date_str(d: date) -> str:
    return d.isoformat()
