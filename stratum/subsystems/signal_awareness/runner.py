"""Independent signal-awareness detection runner."""

from __future__ import annotations

import json
import os
from typing import Any

from .anchors import normalize_anchor_registry, summarize_anchor_mentions
from .contracts import SIGNAL_ACTIVATION_PLAN, SIGNAL_AWARENESS, validate_output_payload
from .emergence import detect_unanchored_event_clusters
from .planning import build_activation_plan
from .snapshots import build_snapshot, compute_topic_signals
from .topics import classify_records_by_topic, normalize_topic_rules


def detect_signal_awareness(
    *,
    domain: str,
    run_date: str | None,
    records: list[dict[str, Any]],
    topic_rules: list[Any] | None = None,
    anchor_registry: list[dict[str, Any]] | None = None,
    historical_snapshots: list[dict[str, Any]] | None = None,
    active_signals: list[dict[str, Any]] | None = None,
    default_daily_target: int = 8,
    z_threshold: float = 2.5,
) -> dict[str, Any]:
    """Detect early signal changes from current records and historical context."""
    normalized_topics = normalize_topic_rules(topic_rules)
    normalized_anchors = normalize_anchor_registry(anchor_registry)
    topic_counts, annotated_records = classify_records_by_topic(records, normalized_topics)
    anchor_signals = summarize_anchor_mentions(
        annotated_records,
        normalized_anchors,
        run_date=run_date,
    )
    topic_signals = compute_topic_signals(
        topic_counts,
        historical_snapshots,
        z_threshold=z_threshold,
    )
    unanchored_clusters = detect_unanchored_event_clusters(annotated_records, anchor_signals)
    activation_plan = build_activation_plan(
        run_date=run_date,
        topic_signals=topic_signals,
        anchor_signals=anchor_signals,
        historical_snapshots=historical_snapshots,
        active_signals=active_signals,
        default_daily_target=default_daily_target,
        z_threshold=z_threshold,
    )
    snapshot = build_snapshot(
        run_date=run_date,
        total_records=len(records),
        topic_counts=topic_counts,
        anchor_signals=anchor_signals,
    )
    return {
        "version": "0.1",
        "domain": domain,
        "run_date": run_date,
        "snapshot": snapshot,
        "topic_signals": topic_signals,
        "anchor_signals": anchor_signals,
        "unanchored_clusters": unanchored_clusters,
        "activation_plan": activation_plan,
        "diagnostics": {
            "record_count": len(records),
            "topic_rule_count": len(normalized_topics),
            "anchor_count": len(normalized_anchors),
            "active_signal_count": len(active_signals or []),
            "anomalous_topics": sum(1 for signal in topic_signals if signal["anomalous"]),
            "detected_anchors": sum(1 for signal in anchor_signals if signal["detected"]),
            "cluster_count": len(unanchored_clusters),
        },
    }


def write_signal_awareness(output_dir: str, payload: dict[str, Any]) -> dict[str, str]:
    """Write signal-awareness outputs to stable JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    signal_awareness = dict(payload)
    activation_plan = signal_awareness.pop("activation_plan")
    validate_output_payload(SIGNAL_AWARENESS.key, signal_awareness)
    validate_output_payload(SIGNAL_ACTIVATION_PLAN.key, activation_plan)
    awareness_path = os.path.join(output_dir, SIGNAL_AWARENESS.filename)
    plan_path = os.path.join(output_dir, SIGNAL_ACTIVATION_PLAN.filename)
    with open(awareness_path, "w") as handle:
        json.dump(signal_awareness, handle, ensure_ascii=False, indent=2)
    with open(plan_path, "w") as handle:
        json.dump(activation_plan, handle, ensure_ascii=False, indent=2)
    return {
        SIGNAL_AWARENESS.key: awareness_path,
        SIGNAL_ACTIVATION_PLAN.key: plan_path,
    }
