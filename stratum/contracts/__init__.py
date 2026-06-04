"""
Stratum Contracts — Centralised data models.

Subsystems define their data contracts here so that pytest can collect
all modules without import-path conflicts.

Modules:
  event_thread — CrossTemporalLink, BriefingRef, CrossTemporalState
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
from .report_window import (
    ReportWindow,
    custom_period_id,
    parse_custom_period,
    period_window,
    resolve_report_window,
)
from .pipeline_artifacts import (
    DATA_DIR_ARTIFACTS,
    EDIT_TRACE,
    EVENT_THREADS,
    LEGACY_RAW_ALIASES,
    NORMALIZED_ARTICLES,
    RAW_RESULTS,
    RAW_STATS,
    REPORT_ARTIFACT_TYPES,
    RUN_MANIFEST,
    STORY_CLUSTERS,
    THREAD_KEYWORDS,
    VERIFIED_ARTICLES,
    VERIFY_STATS,
)
