"""Capability invocation envelopes for future MCP wrappers."""

from __future__ import annotations

from typing import Any, Callable

from .analysis import signal_awareness, signal_bursts, source_trace
from .context import awareness_config, report_context, story_context
from .db_reads import (
    active_queries,
    cascade_inputs,
    due_judgments,
    entity_timeline,
    judgment_status,
    key_events,
    key_timeline,
    report_evidence,
    report_lineage,
    search_health,
    search_health_db,
    technology_progress,
    thread_keywords,
    thread_timeline,
    trend_summary,
)
from .diagnostics import discovery_diagnostics, source_expansion
from .planning import attach_signal, evaluate_reports, watch_queries
from .research import briefing_context, format_briefing, synthesis_policy, thread_lifecycle


CAPABILITY_VERSION = "0.1"


def list_calls() -> list[str]:
    """Return canonical capability names suitable for MCP-style wrappers."""
    return sorted(_dispatch_table())


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke one named capability and wrap the result in a stable envelope."""
    try:
        handler = _dispatch_table()[name]
    except KeyError as exc:
        return {
            "version": CAPABILITY_VERSION,
            "capability": name,
            "status": "error",
            "payload": None,
            "error": {
                "type": "UnknownCapability",
                "message": str(exc),
            },
        }
    try:
        payload = handler(**arguments)
    except Exception as exc:  # pragma: no cover - exercised by tests through envelope checks
        return {
            "version": CAPABILITY_VERSION,
            "capability": name,
            "status": "error",
            "payload": None,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
    return {
        "version": CAPABILITY_VERSION,
        "capability": name,
        "status": "ok",
        "payload": payload,
        "error": None,
    }


def _dispatch_table() -> dict[str, Callable[..., Any]]:
    return {
        "briefing_context.format": format_briefing,
        "briefing_context.generate": briefing_context,
        "cascade_inputs.get": cascade_inputs,
        "discovery_diagnostics.build": discovery_diagnostics,
        "due_judgments.get": due_judgments,
        "entity_timeline.get": entity_timeline,
        "judgment_status.get": judgment_status,
        "key_events.get": key_events,
        "key_timeline.get": key_timeline,
        "search_engine_health.get": search_health,
        "search_engine_health.load": search_health_db,
        "report_context.get": report_context,
        "report_item_evidence.get": report_evidence,
        "report_lineage.trace": report_lineage,
        "report_evaluation.run": evaluate_reports,
        "signal_aware_daily.attach": attach_signal,
        "signal_awareness.config.get": awareness_config,
        "signal_awareness.run": signal_awareness,
        "signal_bursts.run": signal_bursts,
        "source_expansion.evaluate": source_expansion,
        "source_trace.run": source_trace,
        "active_search_queries.load": active_queries,
        "story_context.get": story_context,
        "synthesis_policy_config.get": synthesis_policy,
        "thread_keyword_events.get": thread_keywords,
        "thread_lifecycle.diagnostics": thread_lifecycle,
        "thread_timeline.get": thread_timeline,
        "technology_progress.get": technology_progress,
        "trend_summary.get": trend_summary,
        "watch_queries.generate": watch_queries,
    }
