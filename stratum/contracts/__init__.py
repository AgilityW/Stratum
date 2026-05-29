"""
Stratum Contracts — Centralised data models for all subsystems.

Subsystems define their data contracts here so that pytest can collect
all modules without import-path conflicts.

Modules:
  event_thread      — CrossTemporalLink, BriefingRef, CrossTemporalState
  source_intelligence — RecordInput/Output, EvalDimensions, PipelineResult, etc.
"""

from .event_thread import (
    VALID_SCALES,
    SCALE_ORDER,
    scale_higher,
    scale_lower,
    BriefingRef,
    CrossTemporalLink,
    RegisterInput,
    RollupInput,
    CrossTemporalState,
    TraceResult,
)

from .source_intelligence import (
    RecordInput,
    RecordOutput,
    ProfileOutput,
    DiscoverCandidate,
    DiscoverOutput,
    TrialOutput,
    EvalDimensions,
    EvalResult,
    EvalOutput,
    HealthAlert,
    HealthOutput,
    CoverageGap,
    CoverageOutput,
    PipelineResult,
)
