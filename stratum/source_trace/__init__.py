"""SourceTrace analyzers for evidence acquisition observability."""

from .charts import build_charts, charts_markdown
from .funnel import build_funnel
from .loader import load_inputs
from .missed_signals import find_missed_signals
from .observations import (
    DISCOVERY_OBSERVATIONS,
    WATCHLIST_OBSERVATIONS,
    observation_to_candidate_key,
    summarize_observations,
)
from .runner import build_outputs, run_source_trace
from .provenance import build_provenance
from .quality import score_sources
from .recommendations import generate_recommendations
from .report_impact import compute_report_impact
from .temporal_profile import build_temporal_profile
from .thread_attribution import attribute_threads

__all__ = [
    "attribute_threads",
    "build_charts",
    "build_funnel",
    "build_provenance",
    "build_temporal_profile",
    "charts_markdown",
    "build_outputs",
    "compute_report_impact",
    "DISCOVERY_OBSERVATIONS",
    "find_missed_signals",
    "generate_recommendations",
    "load_inputs",
    "observation_to_candidate_key",
    "run_source_trace",
    "score_sources",
    "summarize_observations",
    "WATCHLIST_OBSERVATIONS",
]
