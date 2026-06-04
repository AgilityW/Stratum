"""Capability registry for future MCP and agent-facing wrappers."""

from __future__ import annotations

from typing import Any


CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = {
    "source_trace.run": {
        "name": "source_trace.run",
        "family": "analysis",
        "owner": "stratum.source_trace",
        "entrypoint": "stratum.capabilities.source_trace",
        "summary": "Run SourceTrace acquisition observability analysis from a run directory.",
    },
    "signal_bursts.run": {
        "name": "signal_bursts.run",
        "family": "analysis",
        "owner": "stratum.signal_bursts",
        "entrypoint": "stratum.capabilities.signal_bursts",
        "summary": "Run term-level burst detection from explicit records or a run directory.",
    },
    "signal_awareness.run": {
        "name": "signal_awareness.run",
        "family": "analysis",
        "owner": "stratum.subsystems.signal_awareness",
        "entrypoint": "stratum.capabilities.signal_awareness",
        "summary": "Run early signal sensing and collection-readiness planning.",
    },
    "discovery_diagnostics.build": {
        "name": "discovery_diagnostics.build",
        "family": "diagnostics",
        "owner": "stratum.sourcing.discovery",
        "entrypoint": "stratum.capabilities.discovery_diagnostics",
        "summary": "Build deterministic discovery diagnostics from explicit search payloads.",
    },
    "source_expansion.evaluate": {
        "name": "source_expansion.evaluate",
        "family": "diagnostics",
        "owner": "stratum.sourcing.watchlist.source_expansion",
        "entrypoint": "stratum.capabilities.source_expansion",
        "summary": "Evaluate watchlist source-expansion signals from a completed run directory.",
    },
    "report_context.get": {
        "name": "report_context.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.report_context",
        "summary": "Return report-semantic context for downstream AI consumers.",
    },
    "thread_timeline.get": {
        "name": "thread_timeline.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.thread_timeline",
        "summary": "Return one thread timeline for research or diagnostic consumers.",
    },
    "thread_keyword_events.get": {
        "name": "thread_keyword_events.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.thread_keywords",
        "summary": "Return active event rows used for thread keyword feedback export.",
    },
    "entity_timeline.get": {
        "name": "entity_timeline.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.entity_timeline",
        "summary": "Return one entity timeline for research or diagnostic consumers.",
    },
    "technology_progress.get": {
        "name": "technology_progress.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.technology_progress",
        "summary": "Return technology progress across companies and periods.",
    },
    "trend_summary.get": {
        "name": "trend_summary.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.trend_summary",
        "summary": "Return scale-level trend summary for a date window.",
    },
    "key_timeline.get": {
        "name": "key_timeline.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.key_timeline",
        "summary": "Return key timeline milestones for a date window.",
    },
    "judgment_status.get": {
        "name": "judgment_status.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.judgment_status",
        "summary": "Return grouped judgment verification status for a date window.",
    },
    "active_search_queries.load": {
        "name": "active_search_queries.load",
        "family": "collection_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.active_queries",
        "summary": "Load active search queries from a SQLite database path.",
    },
    "search_engine_health.load": {
        "name": "search_engine_health.load",
        "family": "collection_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.search_health_db",
        "summary": "Load latest persisted search-engine health records from a SQLite database path.",
    },
    "search_engine_health.get": {
        "name": "search_engine_health.get",
        "family": "collection_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.search_health",
        "summary": "Load latest persisted search-engine health records for a domain DB.",
    },
    "due_judgments.get": {
        "name": "due_judgments.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.due_judgments",
        "summary": "Return judgments still pending verification for follow-up review.",
    },
    "report_item_evidence.get": {
        "name": "report_item_evidence.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.report_evidence",
        "summary": "Return evidence links for one report item.",
    },
    "report_lineage.trace": {
        "name": "report_lineage.trace",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.report_lineage",
        "summary": "Trace one report back to lower-scale reports, events, threads, and articles.",
    },
    "cascade_inputs.get": {
        "name": "cascade_inputs.get",
        "family": "synthesis_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.cascade_inputs",
        "summary": "Return higher-scale synthesis input bundle without running synthesis.",
    },
    "key_events.get": {
        "name": "key_events.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.key_events",
        "summary": "Return priority-ranked key events for a date window.",
    },
    "briefing_context.generate": {
        "name": "briefing_context.generate",
        "family": "research_context",
        "owner": "stratum.subsystems.story_tracking",
        "entrypoint": "stratum.capabilities.briefing_context",
        "summary": "Generate structured briefing context for report-adjacent agent workflows.",
    },
    "briefing_context.format": {
        "name": "briefing_context.format",
        "family": "research_context",
        "owner": "stratum.subsystems.story_tracking",
        "entrypoint": "stratum.capabilities.format_briefing",
        "summary": "Format structured briefing context for prompt or operator display.",
    },
    "thread_lifecycle.diagnostics": {
        "name": "thread_lifecycle.diagnostics",
        "family": "diagnostics",
        "owner": "stratum.subsystems.event_thread",
        "entrypoint": "stratum.capabilities.thread_lifecycle",
        "summary": "Return lifecycle diagnostics for current event-thread state.",
    },
    "synthesis_policy_config.get": {
        "name": "synthesis_policy_config.get",
        "family": "synthesis_read",
        "owner": "stratum.db.synthesis",
        "entrypoint": "stratum.capabilities.synthesis_policy",
        "summary": "Return configured higher-scale synthesis thresholds for diagnostics or agent planning.",
    },
    "report_evaluation.run": {
        "name": "report_evaluation.run",
        "family": "evaluation",
        "owner": "stratum.evaluation",
        "entrypoint": "stratum.capabilities.evaluate_reports",
        "summary": "Run deterministic report regression evaluation from a case file.",
    },
    "signal_aware_daily.attach": {
        "name": "signal_aware_daily.attach",
        "family": "dry_run",
        "owner": "stratum.orchestrator.signal_attach",
        "entrypoint": "stratum.capabilities.attach_signal",
        "summary": "Attach signal-awareness review outputs to an existing daily run without rerunning the pipeline.",
    },
    "story_context.get": {
        "name": "story_context.get",
        "family": "semantic_read",
        "owner": "stratum.db.service",
        "entrypoint": "stratum.capabilities.story_context",
        "summary": "Return story-context records for downstream AI consumers.",
    },
    "watch_queries.generate": {
        "name": "watch_queries.generate",
        "family": "planning",
        "owner": "stratum.subsystems.event_thread",
        "entrypoint": "stratum.capabilities.watch_queries",
        "summary": "Generate next-run watch queries from active or emerging thread state.",
    },
    "signal_awareness.config.get": {
        "name": "signal_awareness.config.get",
        "family": "domain_config",
        "owner": "domains/{domain}/signal_awareness.yaml",
        "entrypoint": "stratum.capabilities.awareness_config",
        "summary": "Load domain-owned signal-awareness configuration for agent or MCP setup.",
    },
}


def list_capabilities() -> list[dict[str, Any]]:
    """Return MCP-ready capability descriptors."""
    return [dict(spec) for spec in CAPABILITY_REGISTRY.values()]


def describe(name: str) -> dict[str, Any]:
    """Return one capability descriptor by canonical name."""
    if name not in CAPABILITY_REGISTRY:
        raise KeyError(f"unknown capability: {name}")
    return dict(CAPABILITY_REGISTRY[name])
