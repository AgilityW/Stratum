"""
Cross-domain pollination — share discovered entities/terms/edges between graphs.

When two domain graphs share overlapping nodes (e.g., "nvidia" in both
storage and AI graphs), discoveries in one domain enrich the other.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from graph import SourceGraph, NodeStatus, EntityNode, TermNode, ChannelNode


def pollinate(
    source_graph: SourceGraph,
    target_graph: SourceGraph,
) -> dict:
    """
    Cross-pollinate discoveries from source graph into target graph.

    For each shared entity:
      - Copy newly active entities (watch→active upgrades) as watch candidates
      - Copy new terms linked to shared entities as watch candidates
      - Copy new channels as watch candidates

    Returns a report of what was cross-pollinated.
    """

    report = {
        "entities_shared": [],
        "terms_shared": [],
        "channels_shared": [],
    }

    # Find shared entity IDs
    shared_ids = set(source_graph.entities.keys()) & set(target_graph.entities.keys())

    if not shared_ids:
        return report

    # 1. Share newly discovered entities connected to shared entities
    for eid, node in source_graph.entities.items():
        if eid in target_graph.entities:
            continue  # already known
        # Check if this entity is mentioned alongside shared entities
        is_connected = any(
            (e.source in shared_ids and e.target in source_graph.terms) or
            (e.target in shared_ids and e.source in source_graph.terms)
            for e in source_graph.mentions
            if e.source == eid or e.target == eid
        )
        if is_connected and node.status in (NodeStatus.ACTIVE, NodeStatus.WATCH):
            if not target_graph.has_entity(eid):
                new_node = EntityNode(
                    id=eid,
                    type=node.type,
                    aliases=dict(node.aliases),
                    first_seen=node.last_seen,
                    last_seen=node.last_seen,
                    score=node.score * 0.5,
                    status=NodeStatus.WATCH,
                )
                target_graph.add_entity(new_node)
                report["entities_shared"].append({
                    "id": eid,
                    "name": node.aliases.get("en", eid),
                    "from_domain": source_graph.domain,
                })

    # 2. Share new terms linked to shared entities
    for tid, node in source_graph.terms.items():
        if tid in target_graph.terms:
            continue
        # Check if this term co-occurs with terms that exist in target
        has_bridge = any(
            e.source in target_graph.terms or e.target in target_graph.terms
            for e in source_graph.co_occurs
            if e.source == tid or e.target == tid
        )
        if has_bridge and node.status in (NodeStatus.ACTIVE, NodeStatus.WATCH):
            if not target_graph.has_term(tid):
                new_node = TermNode(
                    id=tid,
                    type=node.type,
                    aliases=dict(node.aliases),
                    children=list(node.children),
                    first_seen=node.last_seen,
                    last_seen=node.last_seen,
                    score=node.score * 0.5,
                    status=NodeStatus.WATCH,
                )
                target_graph.add_term(new_node)
                report["terms_shared"].append({
                    "id": tid,
                    "name": node.aliases.get("en", tid),
                    "from_domain": source_graph.domain,
                })

    # 3. Share new channels (only if they cover shared terms)
    for cid, node in source_graph.channels.items():
        if cid in target_graph.channels:
            continue
        covers_shared = any(
            e.target in target_graph.terms
            for e in source_graph.covers
            if e.source == cid
        )
        if covers_shared and node.status in (NodeStatus.ACTIVE, NodeStatus.WATCH):
            if not target_graph.has_channel(cid):
                new_node = ChannelNode(
                    id=cid,
                    type=node.type,
                    url=node.url,
                    reliability=node.reliability,
                    js_rendered=node.js_rendered,
                    first_seen=node.last_seen,
                    last_seen=node.last_seen,
                    score=node.score * 0.5,
                    status=NodeStatus.WATCH,
                )
                target_graph.add_channel(new_node)
                report["channels_shared"].append({
                    "id": cid,
                    "url": node.url,
                    "from_domain": source_graph.domain,
                })

    return report


def pollinate_pair(
    graph_path1: str,
    graph_path2: str,
) -> Optional[dict]:
    """
    Two-way pollination between two graph files. Each enriches the other.

    Returns combined report or None if one graph doesn't exist.
    """
    if not os.path.exists(graph_path1) or not os.path.exists(graph_path2):
        return None

    g1 = SourceGraph.load(graph_path1)
    g2 = SourceGraph.load(graph_path2)

    r1 = pollinate(g1, g2)
    r2 = pollinate(g2, g1)

    g1.save(graph_path1)
    g2.save(graph_path2)

    return {
        "domain1": g1.domain,
        "domain2": g2.domain,
        "pollination_1_to_2": r1,
        "pollination_2_to_1": r2,
    }
