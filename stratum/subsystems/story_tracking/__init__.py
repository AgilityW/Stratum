"""Stable package surface for story-tracking contracts and context assembly."""

from .briefing_context import format_context_for_prompt, generate_context
from .context_policy import ContextSelectionPolicy
from .story_contracts import (
    BriefingContext,
    CausalEdge,
    EventRecord,
    Judgment,
    Prominence,
    Scale,
    ScaleRef,
    TaxonomyEntry,
    TimelineEntry,
    UpdateType,
    Verdict,
    from_jsonl_line,
    to_jsonl_line,
)

__all__ = [
    "BriefingContext",
    "CausalEdge",
    "ContextSelectionPolicy",
    "EventRecord",
    "Judgment",
    "Prominence",
    "Scale",
    "ScaleRef",
    "TaxonomyEntry",
    "TimelineEntry",
    "UpdateType",
    "Verdict",
    "format_context_for_prompt",
    "from_jsonl_line",
    "generate_context",
    "to_jsonl_line",
]
