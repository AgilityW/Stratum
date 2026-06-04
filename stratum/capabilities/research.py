"""Capability wrappers for research-oriented context and diagnostics."""

from __future__ import annotations

from typing import Any

from stratum.db.synthesis import get_synthesis_policy_config
from stratum.subsystems.event_thread import lifecycle_diagnostics
from stratum.subsystems.story_tracking import format_context_for_prompt, generate_context
from stratum.subsystems.story_tracking.story_contracts import BriefingContext


def briefing_context(
    *,
    domain_id: str,
    scale: str,
    target_date: str,
    events: list[Any],
    edges: list[Any],
    judgments: list[Any],
    lookback_days: int = 7,
    coverage_gap_days: int = 14,
    due_within_days: int = 7,
    coverage_entities: list[str] | None = None,
) -> dict[str, Any]:
    """Generate structured story-tracking briefing context."""
    return generate_context(
        domain_id=domain_id,
        scale=scale,
        target_date=target_date,
        events=events,
        edges=edges,
        judgments=judgments,
        lookback_days=lookback_days,
        coverage_gap_days=coverage_gap_days,
        due_within_days=due_within_days,
        coverage_entities=coverage_entities,
    ).__dict__


def format_briefing(
    *,
    context: BriefingContext | dict[str, Any],
    max_items: int = 10,
) -> str:
    """Format story-tracking briefing context for prompt injection."""
    if isinstance(context, dict):
        context = BriefingContext(**context)
    return format_context_for_prompt(context, max_items=max_items)


def thread_lifecycle(
    *,
    threads: dict[str, Any],
    run_date: str,
) -> list[dict[str, Any]]:
    """Return lifecycle diagnostics for current thread state."""
    return lifecycle_diagnostics(threads, run_date)


def synthesis_policy(*, target_scale: str) -> dict[str, Any]:
    """Return configured higher-scale synthesis thresholds for diagnostics."""
    config = get_synthesis_policy_config(target_scale)
    return {
        "target_scale": target_scale,
        "config": config.__dict__,
    }
