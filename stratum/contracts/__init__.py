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
