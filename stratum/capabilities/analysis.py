"""Capability wrappers around stable analysis surfaces."""

from __future__ import annotations

from typing import Any

import yaml

from stratum.signal_bursts import detect_signal_bursts
from stratum.source_trace import build_outputs, load_inputs, run_source_trace
from stratum.subsystems.signal_awareness import detect_signal_awareness


def source_trace(
    *,
    input_dir: str,
    output_dir: str | None = None,
    db_context: dict[str, Any] | None = None,
    write_csv: bool = False,
) -> dict[str, Any]:
    """Run SourceTrace through a capability-oriented stable call surface."""
    return run_source_trace(
        input_dir,
        output_dir=output_dir,
        db_context=db_context,
        write_csv=write_csv,
    )


def signal_bursts(
    *,
    terms: list[Any],
    data_dir: str | None = None,
    records_by_layer: dict[str, Any] | None = None,
    source_trace_outputs: dict[str, Any] | None = None,
    db_context: dict[str, Any] | None = None,
    historical_baseline: dict[str, Any] | None = None,
    run_date: str | None = None,
) -> dict[str, Any]:
    """Run Signal Bursts from explicit records or from a run data directory."""
    if data_dir and not records_by_layer:
        loaded = load_inputs(data_dir, db_context=db_context)
        records_by_layer = {
            key: loaded.get(key, [])
            for key in (
                "watchlist_observations",
                "discovery_observations",
                "watchlist_candidates",
                "discovery_candidates",
                "watchlist_results",
                "raw",
            )
        }
        if source_trace_outputs is None:
            source_trace_outputs = build_outputs(
                loaded,
                loaded.get("db_context", {}),
            )
    return detect_signal_bursts(
        terms=terms,
        records_by_layer=records_by_layer or {},
        source_trace_outputs=source_trace_outputs or {},
        db_context=db_context or {},
        historical_baseline=historical_baseline,
        run_date=run_date,
    )


def signal_awareness(
    *,
    domain: str,
    run_date: str | None,
    records: list[dict[str, Any]],
    topic_rules: list[Any] | None = None,
    anchor_registry: list[dict[str, Any]] | None = None,
    historical_snapshots: list[dict[str, Any]] | None = None,
    active_signals: list[dict[str, Any]] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Run Signal Awareness with explicit inputs or an optional domain config file."""
    if config_path and (topic_rules is None or anchor_registry is None):
        with open(config_path) as handle:
            config = yaml.safe_load(handle) or {}
        if topic_rules is None:
            topic_rules = config.get("topic_rules", [])
        if anchor_registry is None:
            anchor_registry = config.get("anchors", [])
    return detect_signal_awareness(
        domain=domain,
        run_date=run_date,
        records=records,
        topic_rules=topic_rules or [],
        anchor_registry=anchor_registry or [],
        historical_snapshots=historical_snapshots,
        active_signals=active_signals,
    )
