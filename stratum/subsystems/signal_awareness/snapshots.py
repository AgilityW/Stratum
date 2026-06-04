"""Snapshot assembly and baseline comparison for signal awareness."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any


def build_snapshot(
    *,
    run_date: str | None,
    total_records: int,
    topic_counts: dict[str, int],
    anchor_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the current signal-awareness snapshot."""
    return {
        "date": run_date,
        "total_records": total_records,
        "topic_counts": dict(sorted(topic_counts.items())),
        "anchor_counts": {
            signal["anchor_id"]: signal["mention_count"]
            for signal in anchor_signals
        },
    }


def compute_topic_signals(
    topic_counts: dict[str, int],
    historical_snapshots: list[dict[str, Any]] | None,
    *,
    z_threshold: float = 2.5,
) -> list[dict[str, Any]]:
    """Compare current topic counts against historical snapshots."""
    historical_snapshots = historical_snapshots or []
    signals: list[dict[str, Any]] = []
    for topic_id, current_count in sorted(topic_counts.items()):
        history = [
            int(snapshot.get("topic_counts", {}).get(topic_id, 0))
            for snapshot in historical_snapshots
        ]
        baseline_mean = mean(history) if history else 0.0
        baseline_std = pstdev(history) if len(history) > 1 else 0.0
        if baseline_std > 0:
            z_score: float | None = (current_count - baseline_mean) / baseline_std
        else:
            z_score = None
        signals.append({
            "topic_id": topic_id,
            "current_count": current_count,
            "baseline_mean": round(baseline_mean, 4),
            "baseline_std": round(baseline_std, 4),
            "z_score": round(z_score, 4) if z_score is not None and math.isfinite(z_score) else None,
            "anomalous": (
                z_score is not None and z_score >= z_threshold and current_count > baseline_mean
            ),
            "history_points": len(history),
        })
    return signals


def anchor_decay_streak(
    anchor_id: str,
    *,
    current_count: int,
    historical_snapshots: list[dict[str, Any]] | None,
    sigma_band: float = 1.0,
) -> int:
    """Return how many consecutive snapshots stayed below the baseline band."""
    historical_snapshots = historical_snapshots or []
    history = [
        int(snapshot.get("anchor_counts", {}).get(anchor_id, 0))
        for snapshot in historical_snapshots
    ]
    baseline_mean = mean(history) if history else 0.0
    baseline_std = pstdev(history) if len(history) > 1 else 0.0
    threshold = baseline_mean + baseline_std * sigma_band
    streak = 1 if current_count <= threshold else 0
    for value in reversed(history):
        if value <= threshold:
            streak += 1
        else:
            break
    return streak
