"""
Source Graph — core data structures.

Domain-agnostic. Nodes are Entities, Terms, Channels.
Edges are weighted relationships between them.
The graph is the living state; all evolution is graph mutation.

Usage:
    from graph import SourceGraph, EntityNode, TermNode, ChannelNode
    graph = SourceGraph("storage")
    graph.add_entity(EntityNode(id="cxmt", aliases={"en": "CXMT", "zh-CN": "长鑫存储"}))
    graph.add_edge_mention("cxmt", "hbm4", weight=0.8)
    graph.save("graph-state.json")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Optional


# ── Node Types ────────────────────────────────────────────

class NodeStatus(str, Enum):
    SEED = "seed"       # manually seeded, never auto-downgraded
    ACTIVE = "active"   # auto-discovered, confirmed high-signal
    WATCH = "watch"     # candidate, needs more evidence
    DORMANT = "dormant" # no signal for ≥30 days
    PRUNED = "pruned"   # deleted (≥90 days dormant)


class EntityType(str, Enum):
    COMPANY = "COMPANY"
    PRODUCT = "PRODUCT"
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"


class TermType(str, Enum):
    TECHNOLOGY = "TECHNOLOGY"
    METRIC = "METRIC"
    STANDARD = "STANDARD"
    TECHNIQUE = "TECHNIQUE"
    MATERIAL = "MATERIAL"


class ChannelType(str, Enum):
    NEWSROOM = "NEWSROOM"
    BLOG = "BLOG"
    ANALYST = "ANALYST"
    MEDIA = "MEDIA"
    RESEARCH = "RESEARCH"
    COMMUNITY = "COMMUNITY"


# ── Node Dataclasses ───────────────────────────────────────

@dataclass
class EntityNode:
    id: str
    type: EntityType = EntityType.COMPANY
    aliases: dict[str, str] = field(default_factory=dict)  # locale → name
    first_seen: str = ""
    last_seen: str = ""
    score: float = 0.0
    status: NodeStatus = NodeStatus.WATCH

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "aliases": self.aliases,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "score": self.score,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, id: str, d: dict) -> "EntityNode":
        return cls(
            id=id,
            type=EntityType(d.get("type", "COMPANY")),
            aliases=d.get("aliases", {}),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
            score=d.get("score", 0.0),
            status=NodeStatus(d.get("status", "watch")),
        )


@dataclass
class TermNode:
    id: str
    type: TermType = TermType.TECHNOLOGY
    aliases: dict[str, str] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    score: float = 0.0
    status: NodeStatus = NodeStatus.WATCH

    def to_dict(self) -> dict:
        d = {
            "type": self.type.value,
            "aliases": self.aliases,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "score": self.score,
            "status": self.status.value,
        }
        if self.children:
            d["children"] = self.children
        return d

    @classmethod
    def from_dict(cls, id: str, d: dict) -> "TermNode":
        return cls(
            id=id,
            type=TermType(d.get("type", "TECHNOLOGY")),
            aliases=d.get("aliases", {}),
            children=d.get("children", []),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
            score=d.get("score", 0.0),
            status=NodeStatus(d.get("status", "watch")),
        )


@dataclass
class ChannelNode:
    id: str
    type: ChannelType = ChannelType.NEWSROOM
    url: str = ""
    reliability: float = 0.5
    js_rendered: bool = False
    last_200: bool = True
    last_hit: Optional[str] = None
    first_seen: str = ""
    last_seen: str = ""
    score: float = 0.0
    status: NodeStatus = NodeStatus.WATCH

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "url": self.url,
            "reliability": self.reliability,
            "js_rendered": self.js_rendered,
            "last_200": self.last_200,
            "last_hit": self.last_hit,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "score": self.score,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, id: str, d: dict) -> "ChannelNode":
        return cls(
            id=id,
            type=ChannelType(d.get("type", "NEWSROOM")),
            url=d.get("url", ""),
            reliability=d.get("reliability", 0.5),
            js_rendered=d.get("js_rendered", False),
            last_200=d.get("last_200", True),
            last_hit=d.get("last_hit"),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
            score=d.get("score", 0.0),
            status=NodeStatus(d.get("status", "watch")),
        )


# ── Edge Dataclasses ───────────────────────────────────────

@dataclass
class Edge:
    source: str
    target: str
    weight: float = 0.0
    first_observed: str = ""
    last_observed: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "weight": self.weight,
            "first_observed": self.first_observed,
            "last_observed": self.last_observed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(**d)


# ── Graph ──────────────────────────────────────────────────

class SourceGraph:
    """The living source graph. All mutation happens here."""

    def __init__(self, domain: str):
        self.domain = domain
        self.initialized: str = ""
        self.last_evolved: str = ""
        self.entities: dict[str, EntityNode] = {}
        self.terms: dict[str, TermNode] = {}
        self.channels: dict[str, ChannelNode] = {}
        self.mentions: list[Edge] = []         # Entity → Term
        self.co_occurs: list[Edge] = []        # Term → Term
        self.publishes_on: list[Edge] = []     # Entity → Channel
        self.covers: list[Edge] = []           # Channel → Term

    # ── Node operations ──

    def add_entity(self, node: EntityNode) -> None:
        self.entities[node.id] = node

    def add_term(self, node: TermNode) -> None:
        self.terms[node.id] = node

    def add_channel(self, node: ChannelNode) -> None:
        self.channels[node.id] = node

    def get_entity(self, id: str) -> Optional[EntityNode]:
        return self.entities.get(id)

    def get_term(self, id: str) -> Optional[TermNode]:
        return self.terms.get(id)

    def get_channel(self, id: str) -> Optional[ChannelNode]:
        return self.channels.get(id)

    def has_entity(self, id: str) -> bool:
        return id in self.entities

    def has_term(self, id: str) -> bool:
        return id in self.terms

    def has_channel(self, id: str) -> bool:
        return id in self.channels

    # ── Alias matching ──

    def find_entity_by_alias(self, text: str) -> Optional[str]:
        """Given a raw name, find matching entity ID via aliases."""
        text_lower = text.lower().strip()
        for eid, node in self.entities.items():
            for alias in node.aliases.values():
                if alias.lower() == text_lower or alias.lower() in text_lower:
                    return eid
        return None

    def find_term_by_alias(self, text: str) -> Optional[str]:
        """Given a raw term, find matching term ID via aliases."""
        text_lower = text.lower().strip()
        for tid, node in self.terms.items():
            for alias in node.aliases.values():
                if alias.lower() == text_lower:
                    return tid
        return None

    # ── Edge operations ──

    def add_edge_mention(self, entity_id: str, term_id: str,
                         weight: float = 0.0, date_str: str = "") -> None:
        self.mentions.append(Edge(
            source=entity_id, target=term_id,
            weight=weight, first_observed=date_str, last_observed=date_str))

    def add_edge_co_occur(self, term1_id: str, term2_id: str,
                           weight: float = 0.0, date_str: str = "") -> None:
        self.co_occurs.append(Edge(
            source=term1_id, target=term2_id,
            weight=weight, first_observed=date_str, last_observed=date_str))

    def add_edge_publishes(self, entity_id: str, channel_id: str,
                            weight: float = 0.0, date_str: str = "") -> None:
        self.publishes_on.append(Edge(
            source=entity_id, target=channel_id,
            weight=weight, first_observed=date_str, last_observed=date_str))

    def add_edge_covers(self, channel_id: str, term_id: str,
                         weight: float = 0.0, date_str: str = "") -> None:
        self.covers.append(Edge(
            source=channel_id, target=term_id,
            weight=weight, first_observed=date_str, last_observed=date_str))

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "initialized": self.initialized,
            "last_evolved": self.last_evolved,
            "nodes": {
                "entities": {eid: n.to_dict() for eid, n in self.entities.items()},
                "terms": {tid: n.to_dict() for tid, n in self.terms.items()},
                "channels": {cid: n.to_dict() for cid, n in self.channels.items()},
            },
            "edges": {
                "mentions": [e.to_dict() for e in self.mentions],
                "co_occurs_with": [e.to_dict() for e in self.co_occurs],
                "publishes_on": [e.to_dict() for e in self.publishes_on],
                "covers": [e.to_dict() for e in self.covers],
            },
            "meta": {
                "total_entities": len(self.entities),
                "total_terms": len(self.terms),
                "total_channels": len(self.channels),
                "total_edges": (len(self.mentions) + len(self.co_occurs) +
                                len(self.publishes_on) + len(self.covers)),
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceGraph":
        g = cls(domain=d["domain"])
        g.initialized = d.get("initialized", "")
        g.last_evolved = d.get("last_evolved", "")
        for eid, nd in d.get("nodes", {}).get("entities", {}).items():
            g.entities[eid] = EntityNode.from_dict(eid, nd)
        for tid, nd in d.get("nodes", {}).get("terms", {}).items():
            g.terms[tid] = TermNode.from_dict(tid, nd)
        for cid, nd in d.get("nodes", {}).get("channels", {}).items():
            g.channels[cid] = ChannelNode.from_dict(cid, nd)
        for e in d.get("edges", {}).get("mentions", []):
            g.mentions.append(Edge.from_dict(e))
        for e in d.get("edges", {}).get("co_occurs_with", []):
            g.co_occurs.append(Edge.from_dict(e))
        for e in d.get("edges", {}).get("publishes_on", []):
            g.publishes_on.append(Edge.from_dict(e))
        for e in d.get("edges", {}).get("covers", []):
            g.covers.append(Edge.from_dict(e))
        return g

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "SourceGraph":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def empty(cls, domain: str) -> "SourceGraph":
        """Create an empty graph for a new domain."""
        return cls(domain=domain)

    # ── Stats ──

    @property
    def active_entities(self) -> list[EntityNode]:
        return [n for n in self.entities.values()
                if n.status in (NodeStatus.SEED, NodeStatus.ACTIVE)]

    @property
    def watch_entities(self) -> list[EntityNode]:
        return [n for n in self.entities.values() if n.status == NodeStatus.WATCH]

    @property
    def active_terms(self) -> list[TermNode]:
        return [n for n in self.terms.values()
                if n.status in (NodeStatus.SEED, NodeStatus.ACTIVE)]

    def summary(self) -> str:
        return (
            f"Graph({self.domain}): "
            f"{len(self.entities)}E/{len(self.terms)}T/{len(self.channels)}C, "
            f"{len(self.mentions)} mentions, "
            f"{len(self.co_occurs)} co-occurrences"
        )
