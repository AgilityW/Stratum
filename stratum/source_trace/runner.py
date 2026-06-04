"""Run SourceTrace analyzers and write observability outputs."""

from __future__ import annotations

import json
import os
from typing import Any

from .charts import build_charts, charts_markdown
from .contracts import OUTPUT_FILES, validate_output_payload
from .conversion import build_conversion_trace
from .db_context import normalize_db_context
from .export import export_csvs
from .funnel import build_funnel
from .issues import mine_issues
from .loader import load_inputs
from .missed_signals import find_missed_signals
from .observation_health import assess_observation_health
from .observations import summarize_observations
from .provenance import build_provenance
from .quality import score_sources
from .recommendations import generate_recommendations
from .report_impact import compute_report_impact
from .summary import build_summary
from .temporal_profile import build_temporal_profile
from .thread_attribution import attribute_threads


def run_source_trace(
    input_dir: str,
    *,
    output_dir: str | None = None,
    db_context: dict[str, Any] | None = None,
    write_csv: bool = False,
) -> dict[str, Any]:
    """Run SourceTrace from artifact files and optional DB context."""
    output_dir = output_dir or os.path.join(input_dir, "source_trace")
    os.makedirs(output_dir, exist_ok=True)

    inputs = load_inputs(input_dir, db_context=db_context)
    db = normalize_db_context(inputs.get("db_context"))
    outputs = build_outputs(inputs, db)
    _write_outputs(output_dir, outputs)
    if write_csv:
        outputs["csv_exports"] = export_csvs(output_dir, {**outputs, "funnel": outputs["funnel"]})
    return outputs


def build_outputs(inputs: dict[str, Any], db_context: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build all SourceTrace output payloads without filesystem writes."""
    watchlist_observations = inputs.get("watchlist_observations", [])
    discovery_observations = inputs.get("discovery_observations", [])
    watchlist_candidates = inputs.get("watchlist_candidates", [])
    discovery_candidates = inputs.get("discovery_candidates", [])
    watchlist_results = inputs.get("watchlist_results", [])
    raw_results = inputs.get("raw", [])
    input_errors = _input_errors(inputs)
    input_status = _input_status(
        watchlist_observations=watchlist_observations,
        discovery_observations=discovery_observations,
        watchlist_candidates=watchlist_candidates,
        discovery_candidates=discovery_candidates,
        watchlist_results=watchlist_results,
    )

    observations = summarize_observations(watchlist_observations, discovery_observations)
    observation_health = assess_observation_health(
        watchlist_observations,
        discovery_observations,
        watchlist_candidates=watchlist_candidates,
        discovery_candidates=discovery_candidates,
    )
    conversion = build_conversion_trace(
        watchlist_observations,
        discovery_observations,
        watchlist_candidates,
        discovery_candidates,
        watchlist_results,
        raw_results,
        db_context=db_context,
    )
    funnel = build_funnel(
        watchlist_candidates + discovery_candidates,
        watchlist_results,
        raw_results,
        verified_articles=db_context.get("articles", []),
        normalized_articles=db_context.get("articles", []),
        report_evidence=db_context.get("evidence_links", []),
        persisted_articles=db_context.get("persisted_articles", []),
    )
    report_impact = compute_report_impact(
        db_context.get("report_items", []),
        db_context.get("evidence_links", []),
        db_context.get("articles", []),
    )
    quality = score_sources(funnel, impact=report_impact)
    later_records = (
        db_context.get("events", [])
        + db_context.get("threads", [])
        + db_context.get("report_items", [])
        + db_context.get("judgments", [])
    )
    missed_signals = find_missed_signals(watchlist_candidates + discovery_candidates, later_records)
    dedupe_loss = build_provenance(
        watchlist_results,
        raw_results,
        discovery_candidates=discovery_candidates,
    )
    thread_attribution = attribute_threads(
        db_context.get("articles", []),
        db_context.get("events", []),
        db_context.get("threads", []),
    )
    temporal_profile = build_temporal_profile(
        watchlist_observations
        + discovery_observations
        + watchlist_candidates
        + discovery_candidates
        + watchlist_results
        + raw_results
        + db_context.get("articles", [])
    )
    issues = mine_issues(
        observation_health=observation_health,
        funnel=funnel,
        missed_signals=missed_signals,
        provenance=dedupe_loss,
        quality=quality,
        input_errors=input_errors,
    )
    policy_recommendations = generate_recommendations(
        quality,
        missed_signals=missed_signals,
        provenance=dedupe_loss,
        temporal_profile=temporal_profile,
        observation_health=observation_health,
        issues=issues,
    )
    source_trace_summary = build_summary(
        observations=observations,
        funnel=funnel,
        quality=quality,
        missed_signals=missed_signals,
        provenance=dedupe_loss,
        observation_health=observation_health,
        issues=issues,
        recommendations=policy_recommendations,
        input_status=input_status,
        input_errors=input_errors,
        conversion=conversion,
    )
    source_trace_charts = charts_markdown(build_charts(
        summary=source_trace_summary,
        quality=quality,
        observation_health=observation_health,
    ))
    return {
        "source_trace_summary": source_trace_summary,
        "source_quality": quality,
        "missed_signals": missed_signals,
        "dedupe_loss": dedupe_loss,
        "thread_attribution": thread_attribution,
        "report_impact": report_impact,
        "temporal_profile": temporal_profile,
        "policy_recommendations": policy_recommendations,
        "observation_health": observation_health,
        "issues": issues,
        "source_trace_charts": source_trace_charts,
        "observations": observations,
        "conversion": conversion,
        "funnel": funnel,
    }


def _input_errors(inputs: dict[str, Any]) -> dict[str, int]:
    return {
        key[:-7]: len(value)
        for key, value in inputs.items()
        if key.endswith("_errors") and isinstance(value, list) and value
    }


def _input_status(
    *,
    watchlist_observations: list[dict[str, Any]],
    discovery_observations: list[dict[str, Any]],
    watchlist_candidates: list[dict[str, Any]],
    discovery_candidates: list[dict[str, Any]],
    watchlist_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return SourceTrace input availability without failing partial runs."""
    watchlist_count = len(watchlist_observations) + len(watchlist_candidates) + len(watchlist_results)
    discovery_count = len(discovery_observations) + len(discovery_candidates)
    has_watchlist = watchlist_count > 0
    has_discovery = discovery_count > 0
    if has_watchlist and has_discovery:
        mode = "watchlist_and_discovery"
        status = "ok"
        message = "watchlist and discovery inputs are available"
    elif has_watchlist:
        mode = "watchlist_only"
        status = "ok"
        message = "only watchlist inputs are available; continuing SourceTrace analysis"
    elif has_discovery:
        mode = "discovery_only"
        status = "ok"
        message = "only discovery inputs are available; continuing SourceTrace analysis"
    else:
        mode = "no_input"
        status = "error"
        message = "no watchlist or discovery inputs were found; wrote empty SourceTrace outputs"
    return {
        "status": status,
        "mode": mode,
        "has_watchlist": has_watchlist,
        "has_discovery": has_discovery,
        "watchlist_records": watchlist_count,
        "discovery_records": discovery_count,
        "message": message,
    }


def _write_outputs(output_dir: str, outputs: dict[str, Any]) -> None:
    for spec in OUTPUT_FILES:
        payload = outputs.get(spec.key)
        if payload is None:
            continue
        validate_output_payload(spec.key, payload)
        with open(os.path.join(output_dir, spec.filename), "w") as f:
            if spec.file_format == "markdown":
                f.write(payload)
            else:
                json.dump(payload, f, ensure_ascii=False, indent=2)
