"""Stable capability layer for future MCP-style and agent-facing use.

This package does not replace the current pipeline. It aggregates a small set
of already-stable deterministic capabilities behind explicit package surfaces so
future MCP wrappers or agent orchestration can call them without reaching into
pipeline internals or stage scripts directly.
"""

from .agent_tasks import get_task, list_tasks, run_task
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
from .registry import describe, list_capabilities
from .research import briefing_context, format_briefing, synthesis_policy, thread_lifecycle
from .runtime import call, list_calls

__all__ = [
    "active_queries",
    "attach_signal",
    "awareness_config",
    "briefing_context",
    "call",
    "cascade_inputs",
    "discovery_diagnostics",
    "due_judgments",
    "entity_timeline",
    "evaluate_reports",
    "format_briefing",
    "describe",
    "get_task",
    "judgment_status",
    "key_events",
    "key_timeline",
    "list_calls",
    "list_capabilities",
    "list_tasks",
    "report_context",
    "report_evidence",
    "report_lineage",
    "run_task",
    "search_health",
    "search_health_db",
    "signal_awareness",
    "signal_bursts",
    "source_expansion",
    "source_trace",
    "story_context",
    "synthesis_policy",
    "technology_progress",
    "thread_keywords",
    "thread_lifecycle",
    "thread_timeline",
    "trend_summary",
    "watch_queries",
]
