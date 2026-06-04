"""Group co-occurring terms into signal candidates."""

from __future__ import annotations

from typing import Any


def group_signal_terms(
    telemetry: dict[str, Any],
    co_occurrence: dict[str, Any],
    *,
    min_pair_count: int = 1,
    max_terms_per_burst: int = 3,
    max_candidates: int = 30,
) -> list[dict[str, Any]]:
    """Build signal candidates from strong pair seeds, not whole components.

    Connected components over-merge when generic bridge terms such as "nvidia",
    "ssd", or "ai" connect otherwise separate stories. Burst candidates should
    stay small and evidence-shaped: start from a co-occurring pair, then expand
    only with terms that strongly connect to the current seed.
    """
    term_ids = [row["term"] for row in telemetry.get("terms", []) if row.get("total_count", 0) > 0]
    telemetry_by_term = {row["term"]: row for row in telemetry.get("terms", [])}
    edge_map = _edge_map(co_occurrence)

    groups: list[set[str]] = []
    for edge in co_occurrence.get("edges", []):
        if int(edge.get("count", 0) or 0) < min_pair_count:
            continue
        left, right = edge.get("terms", ["", ""])
        if left not in telemetry_by_term or right not in telemetry_by_term:
            continue
        group = _expand_seed(
            {left, right},
            term_ids,
            edge_map,
            max_terms=max_terms_per_burst,
        )
        groups.append(group)

    # Preserve important singleton terms too. A real signal can be a single term
    # when it has strong raw/source/DB support but little co-occurrence.
    for term_id in term_ids:
        groups.append({term_id})

    unique_groups = _dedupe_groups(groups)
    candidates = []
    for terms in unique_groups:
        rows = [telemetry_by_term[term] for term in sorted(terms)]
        representative_titles = _representative_titles(terms, co_occurrence)
        structure = _structure_metrics(terms, co_occurrence)
        label = _label(rows)
        candidates.append({
            "label": label,
            "terms": sorted(terms),
            "term_count": len(terms),
            "grouping_strategy": "pair_seed_limited_expansion" if len(terms) > 1 else "singleton_telemetry",
            **structure,
            "observed_count": sum(row.get("total_count", 0) for row in rows),
            "weighted_count": round(sum(float(row.get("weighted_count", 0.0) or 0.0) for row in rows), 4),
            "source_count": len({source for row in rows for source in row.get("sources", [])}),
            "official_count": sum(row.get("official_count", 0) for row in rows),
            "raw_count": sum(row.get("raw_count", 0) for row in rows),
            "db_count": sum(row.get("db_count", 0) for row in rows),
            "representative_titles": representative_titles,
        })
    return sorted(
        candidates,
        key=lambda item: (
            -item["term_count"],
            -item["co_occurrence_count"],
            -item["weighted_count"],
            item["label"],
        ),
    )[:max_candidates]


def _edge_map(co_occurrence: dict[str, Any]) -> dict[frozenset[str], int]:
    edges = {}
    for edge in co_occurrence.get("edges", []):
        terms = edge.get("terms", [])
        if len(terms) != 2:
            continue
        edges[frozenset(terms)] = int(edge.get("count", 0) or 0)
    return edges


def _expand_seed(
    group: set[str],
    term_ids: list[str],
    edge_map: dict[frozenset[str], int],
    *,
    max_terms: int,
) -> set[str]:
    while len(group) < max_terms:
        best_term = ""
        best_score = 0
        for term_id in term_ids:
            if term_id in group:
                continue
            counts = [
                edge_map.get(frozenset((term_id, existing)), 0)
                for existing in group
            ]
            linked = [count for count in counts if count > 0]
            if not linked:
                continue
            # Require multiple links into the seed after the initial pair.
            # A single strong edge can otherwise pull bridge terms into
            # unrelated local stories.
            if len(linked) < min(2, len(group)):
                continue
            score = sum(linked)
            if score > best_score:
                best_score = score
                best_term = term_id
        if not best_term:
            break
        group.add(best_term)
    return group


def _dedupe_groups(groups: list[set[str]]) -> list[set[str]]:
    unique: list[set[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in sorted(groups, key=lambda item: (-len(item), sorted(item))):
        key = tuple(sorted(group))
        if key in seen:
            continue
        # Drop smaller groups that are strict subsets of an existing candidate,
        # except singletons, which remain useful telemetry-backed bursts.
        if len(group) > 1 and any(group < existing for existing in unique):
            continue
        seen.add(key)
        unique.append(group)
    return unique


def _label(rows: list[dict[str, Any]]) -> str:
    labels = [str(row.get("label") or row.get("term")) for row in sorted(rows, key=lambda item: -item.get("weighted_count", 0))]
    return " ".join(labels[:4])


def _representative_titles(terms: set[str], co_occurrence: dict[str, Any]) -> list[str]:
    titles = []
    for edge in co_occurrence.get("edges", []):
        if set(edge.get("terms", [])).issubset(terms):
            for title in edge.get("representative_titles", []):
                if title not in titles:
                    titles.append(title)
                if len(titles) >= 5:
                    return titles
    return titles


def _structure_metrics(terms: set[str], co_occurrence: dict[str, Any]) -> dict[str, Any]:
    if len(terms) <= 1:
        return {
            "co_occurrence_count": 0,
            "co_occurrence_density": 0.0,
            "strongest_pair_count": 0,
        }
    pair_counts = []
    for edge in co_occurrence.get("edges", []):
        if set(edge.get("terms", [])).issubset(terms):
            pair_counts.append(int(edge.get("count", 0) or 0))
    possible_edges = len(terms) * (len(terms) - 1) / 2
    return {
        "co_occurrence_count": sum(pair_counts),
        "co_occurrence_density": round(len(pair_counts) / possible_edges, 4) if possible_edges else 0.0,
        "strongest_pair_count": max(pair_counts) if pair_counts else 0,
    }
