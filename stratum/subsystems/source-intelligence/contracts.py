"""Contracts — Data models for the Source Intelligence pipeline.

Each stage has a clear input and output dataclass.
All modules wired through the pipeline use these contracts.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ═══════════════════════════════════════════════════════════
# Stage 1: RECORD — articles → SourceRecords
# ═══════════════════════════════════════════════════════════

@dataclass
class RecordInput:
    articles_path: str              # Path to articles.jsonl
    clusters_path: str              # Path to clusters.json
    run_date: str                   # ISO date


@dataclass
class RecordOutput:
    records: list[dict]             # SourceRecord list
    unique_sources: int
    total_records: int
    records_path: str               # Where records were written


# ═══════════════════════════════════════════════════════════
# Stage 2: PROFILE — SourceRecords → SourceProfiles
# ═══════════════════════════════════════════════════════════

@dataclass
class ProfileOutput:
    updated: int                    # Profiles updated
    new_profiles: int               # New profiles created
    alerts: list[dict]              # Degradation alerts [{source, type, from, to}]
    profiles_dir: str


# ═══════════════════════════════════════════════════════════
# Stage 3: DISCOVER — articles → new source candidates
# ═══════════════════════════════════════════════════════════

@dataclass
class DiscoverCandidate:
    domain: str
    source_type: str                # media | analyst | official | blog
    source_locale: str              # en | zh-CN | ja | ko | ...
    first_seen: str                 # ISO date
    first_url: str                  # Where it was found
    context: str                    # Which query/source led here


@dataclass
class DiscoverOutput:
    candidates: list[DiscoverCandidate]
    total_new: int
    skipped_known: int              # Already in seed or trial pool


# ═══════════════════════════════════════════════════════════
# Stage 4: TRIAL — manage trial pool
# ═══════════════════════════════════════════════════════════

@dataclass
class TrialOutput:
    pool_path: str
    new_candidates: int             # Added this run
    collecting: int                 # Still collecting
    triggered: int                  # Reached threshold → evaluating
    evaluated: int                  # Just evaluated
    recommendations: list[dict]     # [{source, score, recommendation}]


# ═══════════════════════════════════════════════════════════
# Stage 5: EVALUATE — enriched 7-dim scoring
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalDimensions:
    novelty: float                  # % first_disclosure
    verifiability: float            # % cross-verified
    exclusivity: float              # % unique claims
    signal_noise: float             # 1 - % rehash
    depth: float                    # avg claims/article (normalized)
    diversity: float                # topic coverage breadth
    acceleration: float             # bonus from trusted citation / gap fill


@dataclass
class EvalResult:
    source: str
    score: float                    # Weighted 7-dim score
    dimensions: EvalDimensions
    recommendation: str             # promote | archive | extend
    confidence: str                 # high | medium | low (based on sample size)
    sample_count: int
    trial_days: int


@dataclass
class EvalOutput:
    results: list[EvalResult]
    promoted: int
    archived: int
    extended: int


# ═══════════════════════════════════════════════════════════
# Stage 6: HEALTH — source health check
# ═══════════════════════════════════════════════════════════

@dataclass
class HealthAlert:
    source: str
    alert_type: str                 # dry_streak | novelty_drop | http_errors | dead
    severity: str                   # warning | critical
    detail: str


@dataclass
class HealthOutput:
    total_sources: int
    healthy: int
    degraded: int                   # Dry streak > 3 days or novelty drop
    dead: int                       # No hits in 14+ days
    alerts: list[HealthAlert]
    top_contributors: list[dict]
    stats_path: str


# ═══════════════════════════════════════════════════════════
# Stage 7: COVERAGE — gap detection
# ═══════════════════════════════════════════════════════════

@dataclass
class CoverageGap:
    cluster_id: str
    cluster_title: str
    severity: str                   # high | medium
    missing_types: list[str]        # official | analyst | media
    missing_locales: list[str]      # zh-CN | en
    current_sources: list[str]


@dataclass
class CoverageOutput:
    total_clusters: int
    gaps_found: int
    high_severity: int
    gaps: list[CoverageGap]
    followup_queries: list[dict]    # Queries for next day's collection
    alerts_path: str


# ═══════════════════════════════════════════════════════════
# Pipeline aggregate
# ═══════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    domain_id: str
    run_date: str
    record: Optional[RecordOutput] = None
    profile: Optional[ProfileOutput] = None
    discover: Optional[DiscoverOutput] = None
    trial: Optional[TrialOutput] = None
    evaluate: Optional[EvalOutput] = None
    health: Optional[HealthOutput] = None
    coverage: Optional[CoverageOutput] = None
    errors: list[str] = field(default_factory=list)
    summary: str = ""
