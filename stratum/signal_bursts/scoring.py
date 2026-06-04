"""Burst scoring from telemetry, SourceTrace outputs, baseline, and DB links."""

from __future__ import annotations

from typing import Any

from .baseline import classify_against_baseline
from .linking import link_db_context


def score_bursts(
    candidates: list[dict[str, Any]],
    *,
    source_trace_outputs: dict[str, Any],
    db_context: dict[str, list[dict[str, Any]]],
    normalized_terms: list[dict[str, Any]],
    historical_baseline: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Score burst candidates and attach context."""
    source_quality = {
        row.get("source", ""): float(row.get("quality_score", 0.0) or 0.0)
        for row in source_trace_outputs.get("source_quality", [])
    }
    dedupe_penalty = min(0.2, 0.01 * float(source_trace_outputs.get("dedupe_loss", {}).get("totals", {}).get("deduped_paths", 0) or 0))
    health_penalty = _health_penalty(source_trace_outputs.get("observation_health", {}))

    scored = []
    for candidate in candidates:
        baseline = classify_against_baseline(candidate, historical_baseline)
        links = link_db_context(candidate, db_context, normalized_terms)
        source_diversity_score = min(1.0, candidate.get("source_count", 0) / 5)
        volume_score = min(1.0, candidate.get("weighted_count", 0.0) / 20)
        official_score = min(1.0, candidate.get("official_count", 0) / 2)
        raw_score = min(1.0, candidate.get("raw_count", 0) / 3)
        db_score = min(1.0, candidate.get("db_count", 0) / 3)
        quality_score = _candidate_source_quality(candidate, source_quality)
        novelty_score = min(1.0, max(0.0, baseline["baseline_ratio"] - 1.0) / 3)
        report_score = links.get("db_relevance_score", 0.0)
        structure_score = _structure_score(candidate)
        burst_score = (
            0.15 * volume_score
            + 0.10 * source_diversity_score
            + 0.10 * quality_score
            + 0.10 * official_score
            + 0.10 * raw_score
            + 0.10 * db_score
            + 0.10 * novelty_score
            + 0.10 * report_score
            + 0.15 * structure_score
            - dedupe_penalty
            - health_penalty
        )
        score = round(max(0.0, min(1.0, burst_score)), 4)
        scored.append({
            **candidate,
            **baseline,
            "links": links,
            "burst_score": score,
            "confidence": _confidence(score),
            "recommended_report_treatment": _treatment(score, baseline["classification"], links),
            "score_components": {
                "volume": round(volume_score, 4),
                "source_diversity": round(source_diversity_score, 4),
                "source_quality": round(quality_score, 4),
                "official_support": round(official_score, 4),
                "raw_conversion": round(raw_score, 4),
                "db_relevance": round(db_score, 4),
                "novelty": round(novelty_score, 4),
                "report_context": round(report_score, 4),
                "group_structure": round(structure_score, 4),
                "dedupe_penalty": round(dedupe_penalty, 4),
                "observation_health_penalty": round(health_penalty, 4),
            },
        })
    return _rerank_diverse(scored)


def _candidate_source_quality(candidate: dict[str, Any], source_quality: dict[str, float]) -> float:
    if not source_quality:
        return 0.5
    # Candidate source lists are not preserved in grouping yet, so use a neutral
    # mean of known source qualities as a quality prior for this run.
    return sum(source_quality.values()) / max(len(source_quality), 1)


def _structure_score(candidate: dict[str, Any]) -> float:
    term_count = int(candidate.get("term_count", 0) or 0)
    if term_count <= 1:
        return 0.2
    density = float(candidate.get("co_occurrence_density", 0.0) or 0.0)
    strongest_pair = float(candidate.get("strongest_pair_count", 0) or 0)
    pair_strength = min(1.0, strongest_pair / 5)
    size_score = 0.7 if term_count == 2 else 1.0
    return max(0.0, min(1.0, 0.45 * density + 0.35 * pair_strength + 0.20 * size_score))


def _health_penalty(observation_health: dict[str, Any]) -> float:
    issues = 0
    total = 0
    for layer in ("watchlist", "discovery"):
        for row in observation_health.get(layer, {}).get("sources", []):
            total += 1
            if row.get("health_status") not in {"ok", None, ""}:
                issues += 1
    return min(0.2, issues / max(total, 1) * 0.1)


def _confidence(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _treatment(score: float, classification: str, links: dict[str, Any]) -> str:
    if score >= 0.75 and (links.get("threads") or links.get("events")):
        return "core_judgment_candidate"
    if classification in {"emerging", "intensifying"} and score >= 0.45:
        return "watch_item"
    if score >= 0.35:
        return "verification_needed"
    return "noise_or_duplicate"


def _rerank_diverse(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = sorted(
        scored,
        key=lambda item: (-_base_ranking_score(item), item["label"]),
    )
    selected: list[dict[str, Any]] = []
    while remaining:
        best_index = 0
        best_score = -1.0
        for index, item in enumerate(remaining):
            score = _base_ranking_score(item) - _overlap_penalty(item, selected)
            if score > best_score:
                best_index = index
                best_score = score
        item = remaining.pop(best_index)
        item = {**item, "ranking_score": round(best_score, 4)}
        selected.append(item)
    return selected


def _base_ranking_score(item: dict[str, Any]) -> float:
    co_occurrence_bonus = min(0.05, float(item.get("co_occurrence_count", 0) or 0) / 100 * 0.05)
    return float(item.get("burst_score", 0.0) or 0.0) + co_occurrence_bonus


def _overlap_penalty(item: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    terms = set(item.get("terms", []))
    if not terms:
        return 0.0
    penalty = 0.0
    for other in selected[:8]:
        other_terms = set(other.get("terms", []))
        if not other_terms:
            continue
        overlap = len(terms & other_terms) / max(len(terms), len(other_terms))
        penalty = max(penalty, overlap * 0.08)
    return penalty
