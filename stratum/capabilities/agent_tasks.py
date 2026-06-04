"""Agent-facing task wrappers built on the capability layer."""

from __future__ import annotations

from typing import Any

from stratum.source_trace import load_inputs

from .context import awareness_config
from .runtime import call


AGENT_TASK_VERSION = "0.1"


AGENT_TASK_REGISTRY: dict[str, dict[str, Any]] = {
    "analyze_signal_landscape": {
        "name": "analyze_signal_landscape",
        "summary": "Analyze one completed run for observability, bursts, and early collection-readiness signals.",
        "capabilities": [
            "source_trace.run",
            "signal_bursts.run",
            "signal_awareness.run",
        ],
    },
    "lookup_report_context": {
        "name": "lookup_report_context",
        "summary": "Fetch report-semantic context through the capability layer.",
        "capabilities": ["report_context.get"],
    },
    "lookup_story_context": {
        "name": "lookup_story_context",
        "summary": "Fetch story-context records through the capability layer.",
        "capabilities": ["story_context.get"],
    },
    "inspect_discovery_diagnostics": {
        "name": "inspect_discovery_diagnostics",
        "summary": "Build deterministic discovery diagnostics from explicit search payloads.",
        "capabilities": ["discovery_diagnostics.build"],
    },
    "inspect_source_expansion": {
        "name": "inspect_source_expansion",
        "summary": "Inspect source-expansion recommendations from one completed watchlist run.",
        "capabilities": ["source_expansion.evaluate"],
    },
    "evaluate_report_regression": {
        "name": "evaluate_report_regression",
        "summary": "Run deterministic report-quality regression evaluation from a benchmark case file.",
        "capabilities": ["report_evaluation.run"],
    },
    "generate_followup_watch_queries": {
        "name": "generate_followup_watch_queries",
        "summary": "Generate next-run watch queries from active or emerging thread state.",
        "capabilities": ["watch_queries.generate"],
    },
    "attach_signal_awareness_to_run": {
        "name": "attach_signal_awareness_to_run",
        "summary": "Attach signal-awareness dry-run outputs to an existing daily run without rerunning the pipeline.",
        "capabilities": ["signal_aware_daily.attach"],
    },
    "inspect_thread_timeline": {
        "name": "inspect_thread_timeline",
        "summary": "Inspect one thread timeline through the DB semantic-read layer.",
        "capabilities": ["thread_timeline.get"],
    },
    "inspect_scale_trends": {
        "name": "inspect_scale_trends",
        "summary": "Inspect scale-level trend summary, key timeline, and judgment status for one window.",
        "capabilities": [
            "trend_summary.get",
            "key_timeline.get",
            "judgment_status.get",
        ],
    },
    "inspect_report_lineage": {
        "name": "inspect_report_lineage",
        "summary": "Trace one report back to lower-scale evidence and lineage links.",
        "capabilities": ["report_lineage.trace"],
    },
    "inspect_report_item_evidence": {
        "name": "inspect_report_item_evidence",
        "summary": "Inspect report-item evidence links through the DB semantic-read layer.",
        "capabilities": ["report_item_evidence.get"],
    },
    "prepare_scale_synthesis_research": {
        "name": "prepare_scale_synthesis_research",
        "summary": "Load higher-scale synthesis input bundle without running synthesis or render stages.",
        "capabilities": ["cascade_inputs.get"],
    },
    "inspect_technology_progress": {
        "name": "inspect_technology_progress",
        "summary": "Inspect one technology progression across companies and periods.",
        "capabilities": ["technology_progress.get"],
    },
    "inspect_due_judgments": {
        "name": "inspect_due_judgments",
        "summary": "Inspect pending judgments due for follow-up verification.",
        "capabilities": ["due_judgments.get"],
    },
    "inspect_active_search_queries": {
        "name": "inspect_active_search_queries",
        "summary": "Inspect active search queries from a SQLite database path.",
        "capabilities": ["active_search_queries.load"],
    },
    "inspect_search_engine_health": {
        "name": "inspect_search_engine_health",
        "summary": "Inspect persisted search-engine health from a SQLite database path or domain DB.",
        "capabilities": ["search_engine_health.load"],
    },
    "inspect_thread_keyword_events": {
        "name": "inspect_thread_keyword_events",
        "summary": "Inspect active event rows used for thread keyword feedback export.",
        "capabilities": ["thread_keyword_events.get"],
    },
    "prepare_briefing_context": {
        "name": "prepare_briefing_context",
        "summary": "Generate and format story-tracking briefing context for research-oriented agent use.",
        "capabilities": [
            "briefing_context.generate",
            "briefing_context.format",
        ],
    },
    "inspect_thread_lifecycle": {
        "name": "inspect_thread_lifecycle",
        "summary": "Inspect lifecycle diagnostics for current thread state.",
        "capabilities": ["thread_lifecycle.diagnostics"],
    },
    "inspect_synthesis_policy": {
        "name": "inspect_synthesis_policy",
        "summary": "Inspect configured higher-scale synthesis thresholds without running synthesis.",
        "capabilities": ["synthesis_policy_config.get"],
    },
}


def list_tasks() -> list[dict[str, Any]]:
    """Return agent-facing task descriptors."""
    return [dict(spec) for spec in AGENT_TASK_REGISTRY.values()]


def get_task(task: str) -> dict[str, Any]:
    """Return one agent-facing task descriptor."""
    if task not in AGENT_TASK_REGISTRY:
        raise KeyError(f"unknown agent task: {task}")
    return dict(AGENT_TASK_REGISTRY[task])


def run_task(task: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one agent-facing task through capability-layer envelopes."""
    if task == "analyze_signal_landscape":
        return _run_signal_landscape_task(arguments)
    if task == "lookup_report_context":
        return _run_single_capability_task(task, "report_context.get", arguments)
    if task == "lookup_story_context":
        return _run_single_capability_task(task, "story_context.get", arguments)
    if task == "inspect_discovery_diagnostics":
        return _run_single_capability_task(task, "discovery_diagnostics.build", arguments)
    if task == "inspect_source_expansion":
        return _run_single_capability_task(task, "source_expansion.evaluate", arguments)
    if task == "evaluate_report_regression":
        return _run_single_capability_task(task, "report_evaluation.run", arguments)
    if task == "generate_followup_watch_queries":
        return _run_single_capability_task(task, "watch_queries.generate", arguments)
    if task == "attach_signal_awareness_to_run":
        return _run_single_capability_task(task, "signal_aware_daily.attach", arguments)
    if task == "inspect_thread_timeline":
        return _run_single_capability_task(task, "thread_timeline.get", arguments)
    if task == "inspect_report_lineage":
        return _run_single_capability_task(task, "report_lineage.trace", arguments)
    if task == "inspect_report_item_evidence":
        return _run_single_capability_task(task, "report_item_evidence.get", arguments)
    if task == "prepare_scale_synthesis_research":
        return _run_single_capability_task(task, "cascade_inputs.get", arguments)
    if task == "inspect_technology_progress":
        return _run_single_capability_task(task, "technology_progress.get", arguments)
    if task == "inspect_due_judgments":
        return _run_single_capability_task(task, "due_judgments.get", arguments)
    if task == "inspect_active_search_queries":
        return _run_single_capability_task(task, "active_search_queries.load", arguments)
    if task == "inspect_search_engine_health":
        capability = "search_engine_health.load" if "db_path" in arguments else "search_engine_health.get"
        return _run_single_capability_task(task, capability, arguments)
    if task == "inspect_thread_keyword_events":
        return _run_single_capability_task(task, "thread_keyword_events.get", arguments)
    if task == "inspect_scale_trends":
        return _run_scale_trends_task(arguments)
    if task == "prepare_briefing_context":
        return _run_briefing_context_task(arguments)
    if task == "inspect_thread_lifecycle":
        return _run_single_capability_task(task, "thread_lifecycle.diagnostics", arguments)
    if task == "inspect_synthesis_policy":
        return _run_single_capability_task(task, "synthesis_policy_config.get", arguments)
    return {
        "version": AGENT_TASK_VERSION,
        "task": task,
        "status": "error",
        "steps": [],
        "result": None,
        "error": {
            "type": "UnknownAgentTask",
            "message": f"unknown task: {task}",
        },
    }


def _run_single_capability_task(
    task: str,
    capability: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    step = call(capability, arguments)
    status = "ok" if step["status"] == "ok" else "error"
    return {
        "version": AGENT_TASK_VERSION,
        "task": task,
        "status": status,
        "steps": [{"capability": capability, "status": step["status"]}],
        "result": step["payload"] if step["status"] == "ok" else None,
        "error": None if step["status"] == "ok" else step["error"],
    }


def _run_signal_landscape_task(arguments: dict[str, Any]) -> dict[str, Any]:
    domain = str(arguments["domain"])
    data_dir = str(arguments["data_dir"])
    run_date = arguments.get("run_date")
    db_context = arguments.get("db_context")
    loaded = load_inputs(data_dir, db_context=db_context)
    config = awareness_config(domain)
    records = arguments.get("records") or _flatten_run_records(loaded)
    terms = arguments.get("terms") or config.get("query_terms", [])

    source_trace = call(
        "source_trace.run",
        {
            "input_dir": data_dir,
            "db_context": db_context,
            "write_csv": arguments.get("write_csv", False),
        },
    )
    signal_bursts = call(
        "signal_bursts.run",
        {
            "terms": terms,
            "data_dir": data_dir,
            "db_context": db_context,
            "historical_baseline": arguments.get("historical_baseline"),
            "run_date": run_date,
        },
    )
    signal_awareness = call(
        "signal_awareness.run",
        {
            "domain": domain,
            "run_date": run_date,
            "records": records,
            "topic_rules": arguments.get("topic_rules") or config.get("topic_rules", []),
            "anchor_registry": arguments.get("anchor_registry") or config.get("anchors", []),
            "historical_snapshots": arguments.get("historical_snapshots"),
            "active_signals": arguments.get("active_signals"),
        },
    )
    steps = [
        {"capability": "source_trace.run", "status": source_trace["status"]},
        {"capability": "signal_bursts.run", "status": signal_bursts["status"]},
        {"capability": "signal_awareness.run", "status": signal_awareness["status"]},
    ]
    failed = next(
        (
            result
            for result in (source_trace, signal_bursts, signal_awareness)
            if result["status"] != "ok"
        ),
        None,
    )
    if failed is not None:
        return {
            "version": AGENT_TASK_VERSION,
            "task": "analyze_signal_landscape",
            "status": "error",
            "steps": steps,
            "result": None,
            "error": failed["error"],
        }
    return {
        "version": AGENT_TASK_VERSION,
        "task": "analyze_signal_landscape",
        "status": "ok",
        "steps": steps,
        "result": {
            "source_trace": source_trace["payload"],
            "signal_bursts": signal_bursts["payload"],
            "signal_awareness": signal_awareness["payload"],
        },
        "error": None,
    }


def _flatten_run_records(loaded: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in (
        "watchlist_observations",
        "discovery_observations",
        "watchlist_candidates",
        "discovery_candidates",
        "watchlist_results",
        "raw",
    ):
        rows = loaded.get(key, [])
        if isinstance(rows, list):
            records.extend(row for row in rows if isinstance(row, dict))
    return records


def _run_scale_trends_task(arguments: dict[str, Any]) -> dict[str, Any]:
    trend_summary = call("trend_summary.get", arguments)
    key_timeline = call("key_timeline.get", arguments)
    judgment_status = call(
        "judgment_status.get",
        {
            "domain": arguments["domain"],
            "scale": arguments.get("scale"),
            "start_period": arguments.get("start_period"),
            "end_period": arguments.get("end_period"),
        },
    )
    steps = [
        {"capability": "trend_summary.get", "status": trend_summary["status"]},
        {"capability": "key_timeline.get", "status": key_timeline["status"]},
        {"capability": "judgment_status.get", "status": judgment_status["status"]},
    ]
    failed = next(
        (
            result
            for result in (trend_summary, key_timeline, judgment_status)
            if result["status"] != "ok"
        ),
        None,
    )
    if failed is not None:
        return {
            "version": AGENT_TASK_VERSION,
            "task": "inspect_scale_trends",
            "status": "error",
            "steps": steps,
            "result": None,
            "error": failed["error"],
        }
    return {
        "version": AGENT_TASK_VERSION,
        "task": "inspect_scale_trends",
        "status": "ok",
        "steps": steps,
        "result": {
            "trend_summary": trend_summary["payload"],
            "key_timeline": key_timeline["payload"],
            "judgment_status": judgment_status["payload"],
        },
        "error": None,
    }


def _run_briefing_context_task(arguments: dict[str, Any]) -> dict[str, Any]:
    generated = call("briefing_context.generate", arguments)
    if generated["status"] != "ok":
        return {
            "version": AGENT_TASK_VERSION,
            "task": "prepare_briefing_context",
            "status": "error",
            "steps": [{"capability": "briefing_context.generate", "status": generated["status"]}],
            "result": None,
            "error": generated["error"],
        }
    formatted = call(
        "briefing_context.format",
        {
            "context": generated["payload"],
            "max_items": arguments.get("max_items", 10),
        },
    )
    steps = [
        {"capability": "briefing_context.generate", "status": generated["status"]},
        {"capability": "briefing_context.format", "status": formatted["status"]},
    ]
    if formatted["status"] != "ok":
        return {
            "version": AGENT_TASK_VERSION,
            "task": "prepare_briefing_context",
            "status": "error",
            "steps": steps,
            "result": None,
            "error": formatted["error"],
        }
    return {
        "version": AGENT_TASK_VERSION,
        "task": "prepare_briefing_context",
        "status": "ok",
        "steps": steps,
        "result": {
            "context": generated["payload"],
            "prompt_block": formatted["payload"],
        },
        "error": None,
    }
