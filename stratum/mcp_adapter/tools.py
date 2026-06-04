"""Tool-style adapter descriptors built on the capability layer."""

from __future__ import annotations

from typing import Any

from stratum.capabilities import call


MCP_ADAPTER_VERSION = "0.1"


MCP_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "source_trace_run": {
        "name": "source_trace_run",
        "capability": "source_trace.run",
        "title": "Run SourceTrace",
        "description": "Run acquisition observability analysis from a completed run directory.",
        "input_schema": {
            "type": "object",
            "required": ["input_dir"],
            "properties": {
                "input_dir": {"type": "string"},
                "output_dir": {"type": "string"},
                "db_context": {"type": "object"},
                "write_csv": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "signal_bursts_run": {
        "name": "signal_bursts_run",
        "capability": "signal_bursts.run",
        "title": "Run Signal Bursts",
        "description": "Run term-level burst detection from explicit records or a completed run directory.",
        "input_schema": {
            "type": "object",
            "required": ["terms"],
            "properties": {
                "terms": {"type": "array"},
                "data_dir": {"type": "string"},
                "records_by_layer": {"type": "object"},
                "source_trace_outputs": {"type": "object"},
                "db_context": {"type": "object"},
                "historical_baseline": {"type": "object"},
                "run_date": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "signal_awareness_run": {
        "name": "signal_awareness_run",
        "capability": "signal_awareness.run",
        "title": "Run Signal Awareness",
        "description": "Run early signal sensing and collection-readiness planning.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "records"],
            "properties": {
                "domain": {"type": "string"},
                "run_date": {"type": ["string", "null"]},
                "records": {"type": "array"},
                "topic_rules": {"type": "array"},
                "anchor_registry": {"type": "array"},
                "historical_snapshots": {"type": "array"},
                "active_signals": {"type": "array"},
                "config_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "discovery_diagnostics_build": {
        "name": "discovery_diagnostics_build",
        "capability": "discovery_diagnostics.build",
        "title": "Build Discovery Diagnostics",
        "description": "Build deterministic discovery diagnostics from explicit search payloads.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "workspace", "queries", "raw_results", "curated_results", "query_stats"],
            "properties": {
                "domain": {"type": "string"},
                "workspace": {"type": "string"},
                "queries": {"type": "array"},
                "raw_results": {"type": "array"},
                "curated_results": {"type": "array"},
                "query_stats": {"type": "array"},
                "config_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "source_expansion_evaluate": {
        "name": "source_expansion_evaluate",
        "capability": "source_expansion.evaluate",
        "title": "Evaluate Source Expansion",
        "description": "Evaluate watchlist source-expansion signals from a completed run directory.",
        "input_schema": {
            "type": "object",
            "required": ["run_data_dir"],
            "properties": {
                "run_data_dir": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "report_context_get": {
        "name": "report_context_get",
        "capability": "report_context.get",
        "title": "Get Report Context",
        "description": "Read report-semantic context from the DB service layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "scale", "period"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "period": {"type": "string"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_timeline_get": {
        "name": "thread_timeline_get",
        "capability": "thread_timeline.get",
        "title": "Get Thread Timeline",
        "description": "Read one thread timeline from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "thread_id"],
            "properties": {
                "domain": {"type": "string"},
                "thread_id": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
                "scale": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_keyword_events_get": {
        "name": "thread_keyword_events_get",
        "capability": "thread_keyword_events.get",
        "title": "Get Thread Keyword Events",
        "description": "Read active event rows used for thread keyword feedback export.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"}
            },
            "additionalProperties": False
        }
    },
    "entity_timeline_get": {
        "name": "entity_timeline_get",
        "capability": "entity_timeline.get",
        "title": "Get Entity Timeline",
        "description": "Read one entity timeline from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "entity_id"],
            "properties": {
                "domain": {"type": "string"},
                "entity_id": {"type": "string"},
                "scale": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "technology_progress_get": {
        "name": "technology_progress_get",
        "capability": "technology_progress.get",
        "title": "Get Technology Progress",
        "description": "Read technology progress across companies and periods from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "term_id"],
            "properties": {
                "domain": {"type": "string"},
                "term_id": {"type": "string"},
                "entity_ids": {"type": "array"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
                "scale": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "active_search_queries_load": {
        "name": "active_search_queries_load",
        "capability": "active_search_queries.load",
        "title": "Load Active Search Queries",
        "description": "Load active search queries from a SQLite database path.",
        "input_schema": {
            "type": "object",
            "required": ["db_path"],
            "properties": {
                "db_path": {"type": "string"}
            },
            "additionalProperties": False
        }
    },
    "trend_summary_get": {
        "name": "trend_summary_get",
        "capability": "trend_summary.get",
        "title": "Get Trend Summary",
        "description": "Read scale-level trend summary from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "scale", "start_period", "end_period"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "key_timeline_get": {
        "name": "key_timeline_get",
        "capability": "key_timeline.get",
        "title": "Get Key Timeline",
        "description": "Read key timeline milestones from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "scale", "start_period", "end_period"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
                "limit_per_period": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    "judgment_status_get": {
        "name": "judgment_status_get",
        "capability": "judgment_status.get",
        "title": "Get Judgment Status",
        "description": "Read grouped judgment verification status from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "due_judgments_get": {
        "name": "due_judgments_get",
        "capability": "due_judgments.get",
        "title": "Get Due Judgments",
        "description": "Read pending judgments due for follow-up verification.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "period": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "search_engine_health_load": {
        "name": "search_engine_health_load",
        "capability": "search_engine_health.load",
        "title": "Load Search Engine Health",
        "description": "Load latest persisted search-engine health from a SQLite database path.",
        "input_schema": {
            "type": "object",
            "required": ["db_path"],
            "properties": {
                "db_path": {"type": "string"}
            },
            "additionalProperties": False
        }
    },
    "search_engine_health_get": {
        "name": "search_engine_health_get",
        "capability": "search_engine_health.get",
        "title": "Get Search Engine Health",
        "description": "Load latest persisted search-engine health from a domain DB.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"}
            },
            "additionalProperties": False
        }
    },
    "report_item_evidence_get": {
        "name": "report_item_evidence_get",
        "capability": "report_item_evidence.get",
        "title": "Get Report Item Evidence",
        "description": "Read report-item evidence detail from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "report_item_id"],
            "properties": {
                "domain": {"type": "string"},
                "report_item_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "report_lineage_trace": {
        "name": "report_lineage_trace",
        "capability": "report_lineage.trace",
        "title": "Trace Report Lineage",
        "description": "Trace one report back to lower-scale reports, events, threads, and articles.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "report_id"],
            "properties": {
                "domain": {"type": "string"},
                "report_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "report_evaluation_run": {
        "name": "report_evaluation_run",
        "capability": "report_evaluation.run",
        "title": "Run Report Evaluation",
        "description": "Run deterministic report regression evaluation from a benchmark case file.",
        "input_schema": {
            "type": "object",
            "required": ["cases_path"],
            "properties": {
                "cases_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "cascade_inputs_get": {
        "name": "cascade_inputs_get",
        "capability": "cascade_inputs.get",
        "title": "Get Cascade Inputs",
        "description": "Read higher-scale synthesis input bundle without running synthesis.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "target_scale"],
            "properties": {
                "domain": {"type": "string"},
                "target_scale": {"type": "string"},
                "target_period": {"type": "string"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "key_events_get": {
        "name": "key_events_get",
        "capability": "key_events.get",
        "title": "Get Key Events",
        "description": "Read priority-ranked key events from the DB semantic-read layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "scale", "start_period", "end_period"],
            "properties": {
                "domain": {"type": "string"},
                "scale": {"type": "string"},
                "start_period": {"type": "string"},
                "end_period": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    "signal_aware_daily_attach": {
        "name": "signal_aware_daily_attach",
        "capability": "signal_aware_daily.attach",
        "title": "Attach Signal Awareness To Existing Daily Run",
        "description": "Attach signal-awareness dry-run outputs to an existing daily run without rerunning the pipeline.",
        "input_schema": {
            "type": "object",
            "required": ["domain", "run_date"],
            "properties": {
                "domain": {"type": "string"},
                "run_date": {"type": "string"},
                "config_path": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "story_context_get": {
        "name": "story_context_get",
        "capability": "story_context.get",
        "title": "Get Story Context",
        "description": "Read story-context records from the DB service layer.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "watch_queries_generate": {
        "name": "watch_queries_generate",
        "capability": "watch_queries.generate",
        "title": "Generate Watch Queries",
        "description": "Generate next-run watch queries from active or emerging thread state.",
        "input_schema": {
            "type": "object",
            "required": ["threads"],
            "properties": {
                "threads": {"type": "object"},
                "max_queries": {"type": "integer"},
                "locales": {"type": "array"},
            },
            "additionalProperties": False,
        },
    },
    "briefing_context_generate": {
        "name": "briefing_context_generate",
        "capability": "briefing_context.generate",
        "title": "Generate Briefing Context",
        "description": "Generate structured story-tracking briefing context for research-oriented workflows.",
        "input_schema": {
            "type": "object",
            "required": ["domain_id", "scale", "target_date", "events", "edges", "judgments"],
            "properties": {
                "domain_id": {"type": "string"},
                "scale": {"type": "string"},
                "target_date": {"type": "string"},
                "events": {"type": "array"},
                "edges": {"type": "array"},
                "judgments": {"type": "array"},
                "lookback_days": {"type": "integer"},
                "coverage_gap_days": {"type": "integer"},
                "due_within_days": {"type": "integer"},
                "coverage_entities": {"type": "array"},
            },
            "additionalProperties": False,
        },
    },
    "thread_lifecycle_diagnostics": {
        "name": "thread_lifecycle_diagnostics",
        "capability": "thread_lifecycle.diagnostics",
        "title": "Get Thread Lifecycle Diagnostics",
        "description": "Return lifecycle diagnostics for current thread state.",
        "input_schema": {
            "type": "object",
            "required": ["threads", "run_date"],
            "properties": {
                "threads": {"type": "object"},
                "run_date": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "synthesis_policy_config_get": {
        "name": "synthesis_policy_config_get",
        "capability": "synthesis_policy_config.get",
        "title": "Get Synthesis Policy Config",
        "description": "Read configured higher-scale synthesis thresholds without running synthesis.",
        "input_schema": {
            "type": "object",
            "required": ["target_scale"],
            "properties": {
                "target_scale": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "signal_awareness_config_get": {
        "name": "signal_awareness_config_get",
        "capability": "signal_awareness.config.get",
        "title": "Get Signal Awareness Config",
        "description": "Load domain-owned signal-awareness config for agent or tool setup.",
        "input_schema": {
            "type": "object",
            "required": ["domain"],
            "properties": {
                "domain": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}


def list_tools() -> list[dict[str, Any]]:
    """Return stable tool descriptors for future MCP transport layers."""
    return [dict(spec, adapter_version=MCP_ADAPTER_VERSION) for spec in MCP_TOOL_REGISTRY.values()]


def get_tool(name: str) -> dict[str, Any]:
    """Return one tool descriptor."""
    if name not in MCP_TOOL_REGISTRY:
        raise KeyError(f"unknown mcp tool: {name}")
    return dict(MCP_TOOL_REGISTRY[name], adapter_version=MCP_ADAPTER_VERSION)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one tool by delegating to the capability invocation envelope."""
    try:
        tool = MCP_TOOL_REGISTRY[name]
    except KeyError as exc:
        return {
            "version": MCP_ADAPTER_VERSION,
            "tool": name,
            "status": "error",
            "capability_result": None,
            "error": {
                "type": "UnknownMcpTool",
                "message": str(exc),
            },
        }
    result = call(tool["capability"], arguments)
    return {
        "version": MCP_ADAPTER_VERSION,
        "tool": name,
        "status": result["status"],
        "capability_result": result,
        "error": result["error"],
    }
