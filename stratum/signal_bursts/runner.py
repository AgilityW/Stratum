"""Signal burst detection runner."""

from __future__ import annotations

import json
import os
from typing import Any

from .contracts import SIGNAL_BURSTS, normalize_db_context, normalize_records_by_layer, validate_payload
from .graph import build_co_occurrence
from .grouping import group_signal_terms
from .handoff import build_handoff
from .recommendations import generate_recommendations
from .scoring import score_bursts
from .telemetry import compute_term_telemetry
from .terms import normalize_terms


def detect_signal_bursts(
    *,
    terms: list[Any],
    records_by_layer: dict[str, Any] | None = None,
    source_trace_outputs: dict[str, Any] | None = None,
    db_context: dict[str, Any] | None = None,
    historical_baseline: dict[str, Any] | None = None,
    run_date: str | None = None,
) -> dict[str, Any]:
    """Detect signal bursts from SourceTrace records, outputs, DB context, and terms."""
    normalized_terms = normalize_terms(terms)
    records = normalize_records_by_layer(records_by_layer)
    db = normalize_db_context(db_context)
    source_trace_outputs = source_trace_outputs or {}
    telemetry = compute_term_telemetry(records, db, normalized_terms, run_date=run_date)
    co_occurrence = build_co_occurrence(telemetry["matched_records"])
    candidates = group_signal_terms(telemetry, co_occurrence)
    bursts = score_bursts(
        candidates,
        source_trace_outputs=source_trace_outputs,
        db_context=db,
        normalized_terms=normalized_terms,
        historical_baseline=historical_baseline,
    )
    handoff = build_handoff(bursts)
    recommendations = generate_recommendations(bursts)
    payload = {
        "version": "0.1",
        "terms": telemetry["terms"],
        "co_occurrence": co_occurrence,
        "burst_candidates": candidates,
        "bursts": bursts,
        "report_handoff": handoff,
        "recommendations": recommendations,
        "diagnostics": {
            "telemetry_mode": telemetry["telemetry_mode"],
            "db_context_available": telemetry["db_context_available"],
            "term_count": len(normalized_terms),
            "matched_terms": telemetry["totals"]["matched_terms"],
            "matched_records": telemetry["totals"]["matched_records"],
            "db_records": telemetry["totals"].get("db_records", 0),
            "burst_count": len(bursts),
        },
    }
    validate_payload(payload)
    return payload


def write_signal_bursts(output_dir: str, payload: dict[str, Any]) -> str:
    """Write the Signal Bursts payload to signal_bursts.json."""
    os.makedirs(output_dir, exist_ok=True)
    validate_payload(payload)
    path = os.path.join(output_dir, SIGNAL_BURSTS.filename)
    with open(path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
