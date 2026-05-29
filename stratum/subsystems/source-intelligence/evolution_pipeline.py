"""Pipeline — Source Intelligence full evolution cycle.

Orchestrates all 7 stages of the source evolution pipeline.
Single entry point: run_pipeline(domain_id, run_date, data_dir, domain_config).

Stages:
  1. RECORD    — articles → SourceRecords
  2. PROFILE   — SourceRecords → SourceProfiles (EMA update)
  3. DISCOVER  — new domains → trial candidates
  4. TRIAL     — manage trial pool, track samples
  5. EVALUATE  — enriched 7-dim scoring + acceleration
  6. HEALTH    — source health check, dry streaks, degradation
  7. COVERAGE  — gap detection, follow-up queries

Each stage is independently testable. The pipeline is a thin orchestrator.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

# Resolve paths to existing modules
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_SOURCE_MGMT = str(_PROJECT_ROOT / "stratum" / "subsystems" / "source-management")
_MONITORING = str(_PROJECT_ROOT / "stratum" / "subsystems" / "monitoring")

sys.path.insert(0, _SOURCE_MGMT)
sys.path.insert(0, _MONITORING)
sys.path.insert(0, str(Path(__file__).parent))

from recorder import generate_records, write_records
from profiler import process_records
from trial import load_trial_pool, save_trial_pool, add_candidate, track_samples, process_evaluations, evaluate_source
from health import rebuild_stats, get_dry_sources, get_top_contributors, write_daily_record
from coverage import detect_gaps, generate_followup_queries
from enricher import compute_enriched_eval
from stratum.contracts import (
    RecordInput, RecordOutput, ProfileOutput,
    DiscoverCandidate, DiscoverOutput,
    TrialOutput, EvalResult, EvalDimensions, EvalOutput,
    HealthAlert, HealthOutput, CoverageGap, CoverageOutput,
    PipelineResult,
)


# ═══════════════════════════════════════════════════════════
# Stage 1: RECORD
# ═══════════════════════════════════════════════════════════

def stage_record(input: RecordInput, trial_sources: set = None) -> RecordOutput:
    """Generate SourceRecords from articles and clusters."""
    # Load articles
    articles = []
    with open(input.articles_path) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))

    # Load clusters
    clusters = []
    if os.path.exists(input.clusters_path):
        with open(input.clusters_path) as f:
            clusters = json.load(f).get("clusters", [])

    records = generate_records(articles, clusters, input.run_date, trial_sources)
    output_dir = os.path.dirname(input.articles_path).replace("articles", "sources")
    records_path = write_records(records, output_dir)

    return RecordOutput(
        records=records,
        unique_sources=len(set(r["source_domain"] for r in records)),
        total_records=len(records),
        records_path=records_path,
    )


# ═══════════════════════════════════════════════════════════
# Stage 2: PROFILE
# ═══════════════════════════════════════════════════════════

def stage_profile(records: list[dict], data_dir: str, run_date: str) -> ProfileOutput:
    """Update SourceProfiles from today's records."""
    profiles_dir = os.path.join(data_dir, "profiles")
    stats = process_records(records, profiles_dir, run_date)
    return ProfileOutput(
        updated=stats["updated"],
        new_profiles=stats["new"],
        alerts=stats.get("alerts", []),
        profiles_dir=profiles_dir,
    )


# ═══════════════════════════════════════════════════════════
# Stage 3: DISCOVER
# ═══════════════════════════════════════════════════════════

def stage_discover(
    records: list[dict],
    known_sources: set[str],
    trial_sources: set[str],
    run_date: str,
) -> DiscoverOutput:
    """Discover new source candidates from today's records.

    A source is "new" if its domain is not in known_sources (seed + promoted)
    and not already in the trial pool.
    """
    candidates = []
    seen = set()

    for r in records:
        domain = r.get("source_domain", "")
        if not domain:
            continue
        if domain in known_sources or domain in trial_sources or domain in seen:
            continue
        seen.add(domain)

        candidates.append(DiscoverCandidate(
            domain=domain,
            source_type=r.get("source_type", "unknown"),
            source_locale=r.get("source_locale", "en"),
            first_seen=run_date,
            first_url="",  # would need article URL
            context=f"Discovered in {r.get('cluster_id', 'unclustered')} context",
        ))

    return DiscoverOutput(
        candidates=candidates,
        total_new=len(candidates),
        skipped_known=len(records) - len(candidates),
    )


# ═══════════════════════════════════════════════════════════
# Stage 4: TRIAL
# ═══════════════════════════════════════════════════════════

def stage_trial(
    candidates: list[DiscoverCandidate],
    records: list[dict],
    pool_path: str,
    run_date: str,
) -> TrialOutput:
    """Manage trial pool: add candidates, track samples, trigger evaluations."""
    pool = load_trial_pool(pool_path)

    # Add new candidates
    new_count = 0
    for c in candidates:
        prev_len = len(pool.get("entries", []))
        pool = add_candidate(
            pool, c.domain, c.source_type, c.source_locale,
            run_date, discovery_context=c.context,
        )
        if len(pool.get("entries", [])) > prev_len:
            new_count += 1

    # Track samples
    pool, triggered = track_samples(pool, records)

    # Process evaluations
    evaluating = [e for e in pool.get("entries", []) if e.get("status") == "evaluating"]
    pool = process_evaluations(pool, records)

    save_trial_pool(pool, pool_path)

    recommendations = []
    for e in evaluating:
        recommendations.append({
            "source": e["source"],
            "score": e.get("eval_score", 0),
            "recommendation": e.get("recommendation", "unknown"),
        })

    return TrialOutput(
        pool_path=pool_path,
        new_candidates=new_count,
        collecting=len([e for e in pool.get("entries", []) if e["status"] == "collecting"]),
        triggered=len(triggered),
        evaluated=len(evaluating),
        recommendations=recommendations,
    )


# ═══════════════════════════════════════════════════════════
# Stage 5: EVALUATE — Enriched
# ═══════════════════════════════════════════════════════════

def stage_evaluate(
    trial_output: TrialOutput,
    records: list[dict],
    profiles_dir: str,
    known_sources: set[str],
) -> EvalOutput:
    """Enriched 7-dim evaluation for triggered trial sources."""
    pool = load_trial_pool(trial_output.pool_path)
    results = []
    promoted = 0
    archived = 0
    extended = 0

    for entry in pool.get("entries", []):
        if entry.get("status") != "evaluating":
            continue

        src = entry["source"]
        src_records = [r for r in records if r.get("source_domain") == src]
        all_records = records

        enriched = compute_enriched_eval(
            src_records, all_records, known_sources,
            min_samples=entry.get("min_samples", 20),
        )

        dims = enriched["dimensions"]
        results.append(EvalResult(
            source=src,
            score=enriched["score"],
            dimensions=EvalDimensions(
                novelty=dims["novelty"],
                verifiability=dims["verifiability"],
                exclusivity=dims["exclusivity"],
                signal_noise=dims["signal_noise"],
                depth=dims["depth"],
                diversity=dims["diversity"],
                acceleration=dims["acceleration"],
            ),
            recommendation=enriched["recommendation"],
            confidence=enriched["confidence"],
            sample_count=enriched["sample_count"],
            trial_days=entry.get("trial_duration_days", 14),
        ))

        if enriched["recommendation"] == "promote":
            promoted += 1
        elif enriched["recommendation"] == "archive":
            archived += 1
        else:
            extended += 1

    return EvalOutput(
        results=results,
        promoted=promoted,
        archived=archived,
        extended=extended,
    )


# ═══════════════════════════════════════════════════════════
# Stage 6: HEALTH
# ═══════════════════════════════════════════════════════════

def stage_health(data_dir: str, records: list[dict], run_date: str) -> HealthOutput:
    """Source health check."""
    # Write daily records for each source
    sources_seen = {}
    for r in records:
        src = r.get("source_domain", "")
        if src not in sources_seen:
            sources_seen[src] = {"hits": 0, "selected": 0}
        sources_seen[src]["hits"] += 1
        if r.get("role") != "rehash":
            sources_seen[src]["selected"] += 1

    health_dir = os.path.join(data_dir, "health")
    os.makedirs(health_dir, exist_ok=True)
    for src, counts in sources_seen.items():
        write_daily_record(health_dir, run_date, src,
                          hits=counts["hits"], selected=counts["selected"])

    stats = rebuild_stats(health_dir)
    dry = get_dry_sources(health_dir, min_dry_days=3)
    top = get_top_contributors(health_dir, limit=10)

    # Build alerts
    alerts = []
    for d in dry:
        alerts.append(HealthAlert(
            source=d["source"],
            alert_type="dry_streak",
            severity="warning" if d["dry_streak"] < 7 else "critical",
            detail=f"Dry streak: {d['dry_streak']} days, hit rate: {d['hit_rate']}",
        ))

    total = stats.get("total_sources", 0)
    dead = len([s for s in stats.get("sources", {}).values()
                if s.get("dry_streak", 0) >= 14])

    return HealthOutput(
        total_sources=total,
        healthy=total - len(dry) - dead,
        degraded=len(dry),
        dead=dead,
        alerts=alerts,
        top_contributors=top,
        stats_path=os.path.join(health_dir, "source-stats.json"),
    )


# ═══════════════════════════════════════════════════════════
# Stage 7: COVERAGE
# ═══════════════════════════════════════════════════════════

def stage_coverage(
    clusters_path: str,
    records: list[dict],
    run_date: str,
    data_dir: str,
) -> CoverageOutput:
    """Coverage gap detection."""
    clusters = []
    if os.path.exists(clusters_path):
        with open(clusters_path) as f:
            clusters = json.load(f).get("clusters", [])

    gaps = detect_gaps(clusters, records)
    followup = generate_followup_queries(gaps)

    out_dir = os.path.join(data_dir, "gap-alerts", run_date)
    os.makedirs(out_dir, exist_ok=True)
    result = {
        "date": run_date,
        "total_clusters": len(clusters),
        "gaps_found": len(gaps),
        "high_severity": len([g for g in gaps if g.get("severity") == "high"]),
        "gaps": gaps,
        "followup_queries": followup,
    }
    alerts_path = os.path.join(out_dir, "gap-alerts.json")
    with open(alerts_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return CoverageOutput(
        total_clusters=result["total_clusters"],
        gaps_found=result["gaps_found"],
        high_severity=result["high_severity"],
        gaps=[CoverageGap(
            cluster_id=g.get("cluster_id", ""),
            cluster_title=g.get("title", ""),
            severity=g.get("severity", "medium"),
            missing_types=g.get("missing_types", []),
            missing_locales=g.get("missing_locales", []),
            current_sources=g.get("current_sources", []),
        ) for g in gaps],
        followup_queries=followup,
        alerts_path=alerts_path,
    )


# ═══════════════════════════════════════════════════════════
# FULL PIPELINE
# ═══════════════════════════════════════════════════════════

def run_pipeline(
    domain_id: str,
    run_date: str,
    data_dir: str,
    domain_config: dict,
) -> PipelineResult:
    """Run the full source intelligence evolution cycle.

    Args:
        domain_id: e.g. 'storage'
        run_date: ISO date string
        data_dir: Data directory for this domain/date
        domain_config: Parsed domain.yaml

    Returns:
        PipelineResult with all stage outputs
    """
    result = PipelineResult(domain_id=domain_id, run_date=run_date)

    articles_path = os.path.join(data_dir, "articles.jsonl")
    clusters_path = os.path.join(data_dir.replace("/data/", "/data/").replace(run_date, ""),
                                 run_date, "clusters.json")
    if not os.path.exists(clusters_path):
        # Try alternate path: data_dir might already be date-specific
        clusters_path = os.path.join(data_dir, "clusters.json")

    if not os.path.exists(articles_path):
        result.errors.append(f"articles.jsonl not found: {articles_path}")
        return result

    # Build known sources set from domain config
    known_sources = set()
    for company in domain_config.get("companies", []):
        for alias in company.get("aliases", {}).values():
            known_sources.add(alias.lower())
    for source in domain_config.get("pipeline", {}).get("low_priority_domains", []):
        known_sources.add(source.lower())

    trial_pool_path = os.path.join(data_dir, "trial-pool.json")
    trial_pool = load_trial_pool(trial_pool_path)
    trial_sources = {e["source"] for e in trial_pool.get("entries", [])}

    # ── Stage 1: RECORD ──
    try:
        result.record = stage_record(
            RecordInput(articles_path=articles_path, clusters_path=clusters_path,
                       run_date=run_date),
            trial_sources=trial_sources,
        )
        records = result.record.records
    except Exception as e:
        result.errors.append(f"RECORD failed: {e}")
        return result

    # ── Stage 2: PROFILE ──
    try:
        result.profile = stage_profile(records, data_dir, run_date)
    except Exception as e:
        result.errors.append(f"PROFILE failed: {e}")

    # ── Stage 3: DISCOVER ──
    try:
        result.discover = stage_discover(records, known_sources, trial_sources, run_date)
    except Exception as e:
        result.errors.append(f"DISCOVER failed: {e}")

    # ── Stage 4: TRIAL ──
    try:
        result.trial = stage_trial(
            result.discover.candidates if result.discover else [],
            records, trial_pool_path, run_date,
        )
    except Exception as e:
        result.errors.append(f"TRIAL failed: {e}")

    # ── Stage 5: EVALUATE ──
    try:
        if result.trial and result.trial.triggered > 0:
            result.evaluate = stage_evaluate(
                result.trial, records,
                os.path.join(data_dir, "profiles"),
                known_sources,
            )
    except Exception as e:
        result.errors.append(f"EVALUATE failed: {e}")

    # ── Stage 6: HEALTH ──
    try:
        result.health = stage_health(data_dir, records, run_date)
    except Exception as e:
        result.errors.append(f"HEALTH failed: {e}")

    # ── Stage 7: COVERAGE ──
    try:
        result.coverage = stage_coverage(clusters_path, records, run_date, data_dir)
    except Exception as e:
        result.errors.append(f"COVERAGE failed: {e}")

    # Summary
    parts = []
    if result.record:
        parts.append(f"{result.record.unique_sources} sources, {result.record.total_records} records")
    if result.profile:
        parts.append(f"{result.profile.updated} profiles ({result.profile.new_profiles} new)")
    if result.discover:
        parts.append(f"{result.discover.total_new} new candidates")
    if result.trial:
        parts.append(f"trial: {result.trial.new_candidates} added, {result.trial.triggered} triggered")
    if result.evaluate:
        parts.append(f"eval: {result.evaluate.promoted}P/{result.evaluate.archived}A/{result.evaluate.extended}E")
    if result.health:
        parts.append(f"health: {result.health.healthy} ok, {result.health.degraded} degraded, {result.health.dead} dead")
    if result.coverage:
        parts.append(f"gaps: {result.coverage.gaps_found} ({result.coverage.high_severity} high)")

    result.summary = " | ".join(parts)
    return result
