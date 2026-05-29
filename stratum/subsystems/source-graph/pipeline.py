"""
Source Graph Engine — main pipeline.

Orchestrates: load → extract → score → upgrade → save → query generation.

Usage:
    from pipeline import evolve

    graph, queries, report = evolve(
        domain="storage",
        domain_yaml="data/domain.yaml",
        graph_path="health-data/storage/graph-state.json",
        search_items=todays_results,
    )
"""

from __future__ import annotations

import json
import os
import yaml
from datetime import date, datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus,
)
from extractor import (
    SearchItem, EntityCandidate, TermCandidate, ChannelCandidate,
    EntityExtractor, TermExtractor, ChannelExtractor,
)
from evolution import (
    score_entity_candidate, score_term_candidate, score_channel_candidate,
    compute_upgrade, compute_term_action, compute_channel_action,
    update_edges, generate_new_queries, _decay_all_edges,
)


# ── Main Pipeline ──────────────────────────────────────────

def evolve(
    domain: str,
    domain_yaml_path: str,
    graph_path: str,
    search_items: list[SearchItem],
    log_dir: Optional[str] = None,
    max_auto_queries: int = 5,
    run_date: Optional[date] = None,
) -> dict:
    """
    Run one evolution cycle.

    Args:
        run_date: The date to use as "today" for all evolution decisions.
                  Defaults to date.today() at call time (not import time).

    Returns:
        {
            "graph": SourceGraph,
            "new_queries": [...],
            "report": {
                "entities_extracted": N,
                "terms_extracted": N,
                "channels_extracted": N,
                "entities_upgraded": [...],
                "terms_upgraded": [...],
                "channels_pending_confirmation": [...],
                "queries_generated": N,
            }
        }
    """
    # BUG 5 fix: compute run_date at call time, not import time
    if run_date is None:
        run_date = date.today()
    today_str = run_date.isoformat()

    # 1. Load domain seed
    domain_config = _load_domain_yaml(domain_yaml_path, run_date)

    # 2. Load or initialize graph
    if os.path.exists(graph_path):
        graph = SourceGraph.load(graph_path)
    else:
        graph = _init_graph_from_seed(domain, domain_config, today_str)

    graph.last_evolved = today_str

    # 3. Extract candidates from today's results
    entity_extractor = EntityExtractor()
    term_extractor = TermExtractor()
    channel_extractor = ChannelExtractor()

    entity_candidates = entity_extractor.extract(search_items, graph)
    term_candidates = term_extractor.extract(search_items, graph)
    channel_candidates = channel_extractor.extract(search_items, graph)

    # 4. Score all candidates
    entity_scores = {name: score_entity_candidate(c, entity_candidates)
                     for name, c in entity_candidates.items()}
    term_scores = {name: score_term_candidate(c, term_candidates)
                   for name, c in term_candidates.items()}
    channel_scores = {name: score_channel_candidate(c, channel_candidates)
                      for name, c in channel_candidates.items()}

    # 5. Count observations for upgrade decisions
    entity_obs = _count_entity_observations(entity_candidates, graph)
    term_obs = _count_term_observations(term_candidates, graph)
    # BUG 3 fix: build channel observation history
    channel_obs = _count_channel_observations(channel_candidates, graph)

    # 6. Apply upgrades
    report = {
        "entities_extracted": len(entity_candidates),
        "terms_extracted": len(term_candidates),
        "channels_extracted": len(channel_candidates),
        "entities_upgraded": [],
        "entities_added": [],
        "terms_upgraded": [],
        "terms_added": [],
        "channels_upgraded": [],
        "channels_added": [],
        "channels_pending_confirmation": [],
        "queries_generated": 0,
    }

    new_entity_ids: set[str] = set()
    new_term_ids: set[str] = set()

    # Entities
    seen_entity_ids = set()
    for raw_name, candidate in entity_candidates.items():
        existing_id = graph.find_entity_by_alias(raw_name)
        if existing_id:
            seen_entity_ids.add(existing_id)
            node = graph.get_entity(existing_id)
            old_status = node.status.value
            action = compute_upgrade(existing_id, node, candidate, graph,
                                     {"entity_" + existing_id: entity_obs.get(existing_id, entity_obs.get(raw_name, 0))},
                                     run_date)
            if action:
                node.status = NodeStatus(action)
                node.last_seen = today_str
                report["entities_upgraded"].append({
                    "id": existing_id, "name": raw_name,
                    "from": old_status, "to": action,
                })
        else:
            # New entity → create as WATCH
            eid = _slugify(raw_name)
            if graph.has_entity(eid):
                eid = f"{eid}_{len(graph.entities)}"
            node = EntityNode(
                id=eid,
                type=candidate.type,
                aliases={"en": raw_name},
                first_seen=today_str, last_seen=today_str,
                score=entity_scores[raw_name],
                status=NodeStatus.WATCH,
            )
            graph.add_entity(node)
            new_entity_ids.add(eid)
            report["entities_added"].append({
                "id": eid, "name": raw_name,
                "score": entity_scores[raw_name],
            })

    # Apply decay/prune to existing entities NOT seen today
    for eid, node in list(graph.entities.items()):
        if node.status == NodeStatus.SEED:
            continue
        if eid in seen_entity_ids:
            continue
        old_status = node.status.value
        action = compute_upgrade(eid, node, EntityCandidate(raw_name=eid), graph,
                                 {"entity_" + eid: 0}, run_date)
        if action and action != old_status:
            node.status = NodeStatus(action)
            node.last_seen = today_str
            report["entities_upgraded"].append({
                "id": eid, "name": node.aliases.get("en", eid),
                "from": old_status, "to": action,
            })

    # Terms
    seen_term_ids = set()
    for raw_name, candidate in term_candidates.items():
        existing_id = graph.find_term_by_alias(raw_name)
        if existing_id:
            seen_term_ids.add(existing_id)
            node = graph.get_term(existing_id)
            old_status = node.status.value
            action = compute_term_action(existing_id, node, candidate, graph,
                                         {"term_" + existing_id: term_obs.get(existing_id, term_obs.get(raw_name, 0))},
                                         run_date)
            if action:
                node.status = NodeStatus(action)
                node.last_seen = today_str
                report["terms_upgraded"].append({
                    "id": existing_id, "name": raw_name,
                    "from": old_status, "to": action,
                })
        else:
            tid = _slugify(raw_name)
            if graph.has_term(tid):
                tid = f"{tid}_{len(graph.terms)}"
            node = TermNode(
                id=tid,
                type=candidate.type,
                aliases={"en": raw_name},
                first_seen=today_str, last_seen=today_str,
                score=term_scores[raw_name],
                status=NodeStatus.WATCH,
            )
            graph.add_term(node)
            new_term_ids.add(tid)
            report["terms_added"].append({
                "id": tid, "name": raw_name,
                "score": term_scores[raw_name],
            })

    # Apply decay/prune to existing terms NOT seen today
    for tid, node in list(graph.terms.items()):
        if node.status == NodeStatus.SEED:
            continue
        if tid in seen_term_ids:
            continue
        old_status = node.status.value
        action = compute_term_action(tid, node, TermCandidate(raw_name=tid), graph,
                                     {"term_" + tid: 0}, run_date)
        if action and action != old_status:
            node.status = NodeStatus(action)
            node.last_seen = today_str
            report["terms_upgraded"].append({
                "id": tid, "name": node.aliases.get("en", tid),
                "from": old_status, "to": action,
            })

    # Channels (with confirmation guard)
    for domain_name, candidate in channel_candidates.items():
        existing_id: Optional[str] = None
        for cid, ch in graph.channels.items():
            if domain_name in ch.url:
                existing_id = cid
                break

        if existing_id:
            node = graph.get_channel(existing_id)
            # BUG 3 fix: pass actual channel observation history
            action = compute_channel_action(existing_id, node, candidate, graph,
                                            {"channel_" + existing_id: channel_obs.get(domain_name, 0)},
                                            run_date)
            if action == "CONFIRMATION_REQUIRED":
                report["channels_pending_confirmation"].append({
                    "id": existing_id, "domain": domain_name,
                    "article_count": candidate.article_count,
                    "sample_url": candidate.article_urls[0] if candidate.article_urls else "",
                })
            elif action:
                node.status = NodeStatus(action)
                node.last_seen = today_str
                report["channels_upgraded"].append({
                    "id": existing_id, "domain": domain_name,
                    "to": action,
                })
        else:
            cid = _slugify(domain_name)
            if graph.has_channel(cid):
                cid = f"{cid}_{len(graph.channels)}"
            node = ChannelNode(
                id=cid,
                type=candidate.type,
                url=candidate.url,
                first_seen=today_str, last_seen=today_str,
                score=channel_scores[domain_name],
                status=NodeStatus.WATCH,
            )
            graph.add_channel(node)
            report["channels_added"].append({
                "id": cid, "domain": domain_name,
                "type": candidate.type.value,
                "article_count": candidate.article_count,
            })

    # 7. Update edges (with decay)
    _decay_all_edges(graph, run_date)
    update_edges(graph, search_items, new_entity_ids, new_term_ids, run_date)

    # 8. Generate new queries for next cycle
    new_queries = generate_new_queries(graph, new_entity_ids, new_term_ids,
                                       max_queries=max_auto_queries)
    report["queries_generated"] = len(new_queries)

    # 9. Save graph
    graph.save(graph_path)

    # 10. Write discovery report + evolution log
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

        # Discovery report: what was found today
        report_path = os.path.join(log_dir, "discovery-report.ndjson")
        with open(report_path, "a") as f:
            f.write(json.dumps({"_ts": today_str, **report}, ensure_ascii=False) + "\n")

        # Evolution log: full audit trail of every state change
        log_path = os.path.join(log_dir, "evolution-log.ndjson")
        with open(log_path, "a") as f:
            mutations = _build_mutation_log(report, today_str)
            for m in mutations:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    return {
        "graph": graph,
        "new_queries": new_queries,
        "report": report,
    }


# ── Seed Initialization ────────────────────────────────────

def _init_graph_from_seed(domain: str, domain_config: dict,
                           today_str: str) -> SourceGraph:
    """Create new graph from domain.yaml seed data."""
    g = SourceGraph(domain=domain)
    g.initialized = today_str
    g.last_evolved = today_str

    for c in domain_config.get("companies", []):
        g.add_entity(EntityNode(
            id=c["id"], type=EntityType(c.get("type", "COMPANY")),
            aliases=c["aliases"],
            first_seen=today_str, last_seen=today_str,
            score=1.0, status=NodeStatus.SEED,
        ))

    for t in domain_config.get("terms", []):
        g.add_term(TermNode(
            id=t["id"], type=TermType(t.get("type", "TECHNOLOGY")),
            aliases=t["aliases"], children=t.get("children", []),
            first_seen=today_str, last_seen=today_str,
            score=1.0, status=NodeStatus.SEED,
        ))

    for ch in domain_config.get("channels", []):
        g.add_channel(ChannelNode(
            id=ch["id"], type=ChannelType(ch.get("type", "NEWSROOM")),
            url=ch["url"], reliability=ch.get("reliability", 0.5),
            js_rendered=ch.get("js_rendered", False),
            first_seen=today_str, last_seen=today_str,
            score=ch.get("reliability", 0.5), status=NodeStatus.SEED,
        ))

    return g


# ── Helpers ────────────────────────────────────────────────

def _load_domain_yaml(path: str, run_date: date) -> dict:
    """Load domain.yaml with dynamic placeholder substitution."""
    import re as _re

    with open(path) as f:
        raw = f.read()

    replacements = {
        "${CURRENT_YEAR}": str(run_date.year),
        "${CURRENT_MONTH_EN}": run_date.strftime("%B"),
        "${CURRENT_MONTH_ZH}": str(run_date.month) + "月",
    }
    for placeholder, value in replacements.items():
        raw = raw.replace(placeholder, value)

    return yaml.safe_load(raw)


def _slugify(text: str) -> str:
    """Convert raw text to a graph-safe ID."""
    return text.lower().replace(" ", "-").replace(".", "").replace("/", "-")[:64]


def _build_mutation_log(report: dict, today_str: str) -> list[dict]:
    """Convert discovery report into atomic mutation log entries."""
    mutations = []
    ts = report.get("_ts", today_str)

    for e in report.get("entities_added", []):
        mutations.append({
            "ts": ts, "action": "add", "node_type": "entity",
            "node_id": e["id"], "name": e["name"],
            "score": e.get("score", 0),
        })
    for e in report.get("entities_upgraded", []):
        mutations.append({
            "ts": ts, "action": "upgrade", "node_type": "entity",
            "node_id": e["id"], "name": e["name"],
            "from": e.get("from"), "to": e.get("to"),
        })
    for t in report.get("terms_added", []):
        mutations.append({
            "ts": ts, "action": "add", "node_type": "term",
            "node_id": t["id"], "name": t["name"],
            "score": t.get("score", 0),
        })
    for t in report.get("terms_upgraded", []):
        mutations.append({
            "ts": ts, "action": "upgrade", "node_type": "term",
            "node_id": t["id"], "name": t["name"],
            "from": t.get("from"), "to": t.get("to"),
        })
    for c in report.get("channels_added", []):
        mutations.append({
            "ts": ts, "action": "add", "node_type": "channel",
            "node_id": c["id"], "domain": c.get("domain", ""),
        })
    for c in report.get("channels_pending_confirmation", []):
        mutations.append({
            "ts": ts, "action": "pending_confirmation", "node_type": "channel",
            "node_id": c["id"], "domain": c.get("domain", ""),
        })

    return mutations


def _count_entity_observations(candidates: dict[str, EntityCandidate],
                               graph: SourceGraph) -> dict[str, int]:
    """Count how many independent URLs mention each entity candidate."""
    counts = {}
    for name, c in candidates.items():
        # Check against existing entities too
        eid = graph.find_entity_by_alias(name)
        key = name if not eid else eid
        counts[key] = len(set(c.source_urls))
    return counts


def _count_term_observations(candidates: dict[str, TermCandidate],
                             graph: SourceGraph) -> dict[str, int]:
    counts = {}
    for name, c in candidates.items():
        tid = graph.find_term_by_alias(name)
        key = name if not tid else tid
        counts[key] = len(set(c.source_urls))
    return counts


def _count_channel_observations(candidates: dict[str, ChannelCandidate],
                                 graph: SourceGraph) -> dict[str, int]:
    """BUG 3 fix: Count how many articles mention each channel candidate."""
    counts = {}
    for domain_name, c in candidates.items():
        counts[domain_name] = c.article_count
    return counts
