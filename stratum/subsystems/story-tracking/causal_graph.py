"""Causal graph — directed cause → effect relationships between events.

Each CausalEdge is itself a testable hypothesis:
  cause_id → effect_id, with a mechanism explaining why.

Operates on the CausalRepository interface. Pure functions.
"""

from collections import deque
from typing import Optional

from story_contracts import CausalEdge


# ── Edge Management ──

def add_edge(
    repo,
    state_manager,
    domain_id: str,
    cause_id: str,
    effect_id: str,
    mechanism: str,
    confidence: str,
    created: str,
) -> CausalEdge:
    """Add a causal edge with auto-incremented ID.

    Returns the created edge (already persisted).
    """
    seq = state_manager.next_causal_seq()
    edge = CausalEdge(
        id=f"causal-{domain_id}-{seq:04d}",
        cause_id=cause_id,
        effect_id=effect_id,
        mechanism=mechanism,
        confidence=confidence,
        created=created,
    )
    repo.add(edge)
    return edge


def verify_edge(repo, edge_id: str, verified_at: str, judgment_id: str = "") -> Optional[CausalEdge]:
    """Mark a causal edge as verified. Returns None if edge not found."""
    edges = repo.all()
    for edge in edges:
        if edge.id == edge_id:
            edge.verified = True
            edge.verified_at = verified_at
            if judgment_id:
                edge.judgment_id = judgment_id
            # Rewrite: JSONL doesn't support in-place update, so we need to
            # delete old and append new. Use the repo's update method if it exists,
            # otherwise do manual rewrite.
            _rewrite_edge(repo, edges)
            return edge
    return None


def _rewrite_edge(repo, edges: list[CausalEdge]):
    """Rewrite all edges to the repo file."""
    import os, json
    file_path = repo._file_path
    with open(file_path, "w") as f:
        for e in edges:
            line = json.dumps({
                "id": e.id, "cause_id": e.cause_id, "effect_id": e.effect_id,
                "mechanism": e.mechanism, "confidence": e.confidence,
                "created": e.created, "verified": e.verified,
                "verified_at": e.verified_at, "judgment_id": e.judgment_id,
            }, ensure_ascii=False)
            f.write(line + "\n")


# ── Graph Traversal ──

def upstream(edges: list[CausalEdge], event_id: str) -> list[CausalEdge]:
    """All direct causes of an event (edges where effect_id matches)."""
    return [e for e in edges if e.effect_id == event_id]


def downstream(edges: list[CausalEdge], event_id: str) -> list[CausalEdge]:
    """All direct effects of an event (edges where cause_id matches)."""
    return [e for e in edges if e.cause_id == event_id]


def causal_chain_up(edges: list[CausalEdge], event_id: str, max_depth: int = 10) -> list[str]:
    """Trace all upstream events (BFS) up to max_depth.

    Returns ordered list of event_ids from immediate cause to root cause.
    """
    visited = set()
    queue = deque([event_id])
    chain = []

    for _ in range(max_depth):
        if not queue:
            break
        current = queue.popleft()
        for edge in edges:
            if edge.effect_id == current and edge.cause_id not in visited:
                chain.append(edge.cause_id)
                visited.add(edge.cause_id)
                queue.append(edge.cause_id)

    return chain


def causal_chain_down(edges: list[CausalEdge], event_id: str, max_depth: int = 10) -> list[str]:
    """Trace all downstream events (BFS) up to max_depth.

    Returns ordered list of event_ids from immediate effect to leaf.
    """
    visited = set()
    queue = deque([event_id])
    chain = []

    for _ in range(max_depth):
        if not queue:
            break
        current = queue.popleft()
        for edge in edges:
            if edge.cause_id == current and edge.effect_id not in visited:
                chain.append(edge.effect_id)
                visited.add(edge.effect_id)
                queue.append(edge.effect_id)

    return chain


def subgraph(edges: list[CausalEdge], event_ids: set[str]) -> list[CausalEdge]:
    """All edges where either endpoint is in event_ids."""
    return [e for e in edges if e.cause_id in event_ids or e.effect_id in event_ids]


# ── Analysis ──

def unverified_edges(edges: list[CausalEdge]) -> list[CausalEdge]:
    """Causal edges that have not yet been verified."""
    return [e for e in edges if not e.verified]


def find_loops(edges: list[CausalEdge]) -> list[list[str]]:
    """Detect cycles in the causal graph.

    Returns list of cycles, where each cycle is [event_id, ...].

    Uses DFS with path tracking. Only reports simple cycles.
    """
    # Build adjacency list: cause_id → [effect_ids]
    adj = {}
    for e in edges:
        adj.setdefault(e.cause_id, []).append(e.effect_id)

    loops = []
    visited = set()

    def dfs(node, path, path_set):
        if node in path_set:
            # Found a cycle — extract the loop
            loop_start = path.index(node)
            loop = path[loop_start:] + [node]
            loops.append(loop)
            return

        path.append(node)
        path_set.add(node)

        for neighbor in adj.get(node, []):
            dfs(neighbor, path[:], path_set.copy())

    for node in adj:
        if node not in visited:
            dfs(node, [], set())

    return loops


def edge_stats(edges: list[CausalEdge]) -> dict:
    """Summary statistics for the causal graph."""
    total = len(edges)
    verified_count = sum(1 for e in edges if e.verified)
    verified_by_conf = {"A": 0, "B": 0, "C": 0}
    for e in edges:
        if e.verified and e.confidence in verified_by_conf:
            verified_by_conf[e.confidence] += 1

    # In-degree / out-degree
    causes = {}
    effects = {}
    for e in edges:
        causes[e.cause_id] = causes.get(e.cause_id, 0) + 1
        effects[e.effect_id] = effects.get(e.effect_id, 0) + 1

    all_nodes = set(list(causes.keys()) + list(effects.keys()))

    return {
        "total_edges": total,
        "verified": verified_count,
        "unverified": total - verified_count,
        "verified_by_confidence": verified_by_conf,
        "total_nodes": len(all_nodes),
        "nodes_with_outgoing": len(causes),
        "nodes_with_incoming": len(effects),
    }
