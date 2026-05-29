"""Tests for story-tracking causal graph."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import tempfile
import pytest

from story_contracts import CausalEdge
from repository import JsonlCausalRepository, StateManager
from causal_graph import (
    add_edge, verify_edge,
    upstream, downstream, causal_chain_up, causal_chain_down,
    subgraph, unverified_edges, find_loops, edge_stats,
)


# ── Helpers ──

def make_edge(seq: int, cause: str, effect: str, verified: bool = False) -> CausalEdge:
    return CausalEdge(
        id=f"causal-storage-{seq:04d}",
        cause_id=cause,
        effect_id=effect,
        mechanism=f"Mechanism {seq}: {cause} → {effect}",
        confidence="B",
        created="2026-05-30",
        verified=verified,
    )


# ── Fixtures ──

@pytest.fixture
def repo_and_state():
    with tempfile.TemporaryDirectory() as d:
        repo = JsonlCausalRepository(d)
        state = StateManager(d)
        yield repo, state, "storage"


@pytest.fixture
def simple_chain(repo_and_state):
    """A → B → C → D"""
    repo, state, domain = repo_and_state
    add_edge(repo, state, domain, "A", "B", "A causes B", "B", "2026-05-28")
    add_edge(repo, state, domain, "B", "C", "B causes C", "B", "2026-05-29")
    add_edge(repo, state, domain, "C", "D", "C causes D", "B", "2026-05-30")
    return repo, state, domain


@pytest.fixture
def branching_graph(repo_and_state):
    """A → B, A → C, B → D, C → D, D → E"""
    repo, state, domain = repo_and_state
    add_edge(repo, state, domain, "A", "B", "A→B", "B", "2026-05-28")
    add_edge(repo, state, domain, "A", "C", "A→C", "B", "2026-05-28")
    add_edge(repo, state, domain, "B", "D", "B→D", "B", "2026-05-29")
    add_edge(repo, state, domain, "C", "D", "C→D", "B", "2026-05-29")
    add_edge(repo, state, domain, "D", "E", "D→E", "B", "2026-05-30")
    return repo, state, domain


# ── Edge Management ──

class TestEdgeManagement:
    def test_add_edge(self, repo_and_state):
        repo, state, domain = repo_and_state
        edge = add_edge(repo, state, domain, "ev-001", "ev-002",
                       "Capacity shift", "B", "2026-05-30")
        assert edge.id == "causal-storage-0001"
        assert edge.cause_id == "ev-001"

    def test_add_multiple_edges(self, repo_and_state):
        repo, state, domain = repo_and_state
        e1 = add_edge(repo, state, domain, "A", "B", "m1", "B", "2026-05-28")
        e2 = add_edge(repo, state, domain, "B", "C", "m2", "B", "2026-05-29")
        assert e1.id != e2.id
        assert repo.count() == 2


# ── Graph Traversal ──

class TestTraversal:
    def test_upstream(self, simple_chain):
        repo, state, domain = simple_chain
        edges = repo.all()
        result = upstream(edges, "C")
        assert len(result) == 1
        assert result[0].cause_id == "B"

    def test_upstream_none(self, simple_chain):
        repo, state, domain = simple_chain
        edges = repo.all()
        result = upstream(edges, "A")
        assert len(result) == 0

    def test_downstream(self, simple_chain):
        repo, state, domain = simple_chain
        edges = repo.all()
        result = downstream(edges, "B")
        assert len(result) == 1
        assert result[0].effect_id == "C"

    def test_downstream_multiple(self, branching_graph):
        repo, state, domain = branching_graph
        edges = repo.all()
        result = downstream(edges, "A")
        assert len(result) == 2  # A→B, A→C

    def test_causal_chain_up(self, simple_chain):
        repo, state, domain = simple_chain
        edges = repo.all()
        chain = causal_chain_up(edges, "D")
        assert chain == ["C", "B", "A"]

    def test_causal_chain_down(self, simple_chain):
        repo, state, domain = simple_chain
        edges = repo.all()
        chain = causal_chain_down(edges, "A")
        assert chain == ["B", "C", "D"]

    def test_chain_branching_down(self, branching_graph):
        repo, state, domain = branching_graph
        edges = repo.all()
        chain = causal_chain_down(edges, "A")
        # A → B, A → C → then B→D, C→D → D→E
        assert "B" in chain
        assert "C" in chain
        assert "D" in chain
        assert "E" in chain

    def test_subgraph(self, branching_graph):
        repo, state, domain = branching_graph
        edges = repo.all()
        result = subgraph(edges, {"B", "C"})
        # Edges: A→B, A→C, B→D, C→D (all touch B or C)
        assert len(result) == 4


# ── Analysis ──

class TestAnalysis:
    def test_unverified_edges(self, repo_and_state):
        repo, state, domain = repo_and_state
        add_edge(repo, state, domain, "A", "B", "m1", "B", "2026-05-28")
        add_edge(repo, state, domain, "B", "C", "m2", "B", "2026-05-29")
        assert len(unverified_edges(repo.all())) == 2

    def test_no_cycles_in_chain(self, simple_chain):
        repo, state, domain = simple_chain
        loops = find_loops(repo.all())
        assert len(loops) == 0

    def test_detect_simple_cycle(self, repo_and_state):
        repo, state, domain = repo_and_state
        add_edge(repo, state, domain, "A", "B", "A→B", "B", "2026-05-28")
        add_edge(repo, state, domain, "B", "C", "B→C", "B", "2026-05-29")
        add_edge(repo, state, domain, "C", "A", "C→A", "B", "2026-05-30")
        loops = find_loops(repo.all())
        assert len(loops) >= 1

    def test_edge_stats(self, branching_graph):
        repo, state, domain = branching_graph
        stats = edge_stats(repo.all())
        assert stats["total_edges"] == 5
        assert stats["total_nodes"] == 5  # A, B, C, D, E
        assert stats["nodes_with_outgoing"] == 4  # A, B, C, D
        assert stats["nodes_with_incoming"] == 4  # B, C, D, E
