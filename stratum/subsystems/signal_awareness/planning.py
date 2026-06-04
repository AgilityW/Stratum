"""Action planning for independent signal-awareness detection."""

from __future__ import annotations

from typing import Any

from .snapshots import anchor_decay_streak


def build_activation_plan(
    *,
    run_date: str | None,
    topic_signals: list[dict[str, Any]],
    anchor_signals: list[dict[str, Any]],
    historical_snapshots: list[dict[str, Any]] | None = None,
    active_signals: list[dict[str, Any]] | None = None,
    default_daily_target: int = 8,
    z_threshold: float = 2.5,
) -> dict[str, Any]:
    """Build activation, maintenance, or archive actions without side effects."""
    active_by_id = {
        str(item.get("anchor_id") or item.get("id")): item
        for item in active_signals or []
        if item.get("anchor_id") or item.get("id")
    }
    topic_z = {
        signal["topic_id"]: (signal["z_score"] if signal["z_score"] is not None else 0.0)
        for signal in topic_signals
    }
    actions: list[dict[str, Any]] = []
    for anchor in anchor_signals:
        anchor_id = anchor["anchor_id"]
        active = anchor_id in active_by_id
        max_topic_z = max((topic_z.get(topic_id, 0.0) for topic_id in anchor.get("topics", [])), default=0.0)
        decay_streak = anchor_decay_streak(
            anchor_id,
            current_count=anchor["mention_count"],
            historical_snapshots=historical_snapshots,
        )
        forced_window = anchor["window_status"] in {"lead_window", "live_window"}
        in_teardown = anchor["window_status"] == "teardown_window"
        should_activate = forced_window or (anchor["detected"] and max_topic_z >= z_threshold)
        if active and (in_teardown or decay_streak >= 3):
            action = "archive"
            reason = "signal_decay_or_teardown_window"
        elif active and (anchor["mention_count"] > 0 or forced_window):
            action = "maintain"
            reason = "active_signal_still_present"
        elif should_activate:
            action = "activate"
            reason = "lead_window_or_confirmed_burst"
        else:
            action = "observe"
            reason = "insufficient_signal_for_activation"
        actions.append({
            "anchor_id": anchor_id,
            "anchor_name": anchor["anchor_name"],
            "action": action,
            "reason": reason,
            "confidence": anchor["confidence"],
            "mention_count": anchor["mention_count"],
            "max_topic_z_score": round(max_topic_z, 4) if max_topic_z else 0.0,
            "window_status": anchor["window_status"],
            "decay_streak": decay_streak,
            "daily_target_before": default_daily_target,
            "daily_target_after": (
                {
                    "min": anchor["daily_target_min"],
                    "max": anchor["daily_target_max"],
                }
                if action in {"activate", "maintain"}
                else {"min": default_daily_target, "max": default_daily_target}
            ),
            "temporary_sources": anchor["temporary_sources"] if action in {"activate", "maintain"} else [],
            "direct_fetch_targets": anchor["direct_fetch_targets"] if action in {"activate", "maintain"} else [],
            "query_injections": anchor["query_terms"] if action in {"activate", "maintain"} else [],
        })
    return {
        "run_date": run_date,
        "default_daily_target": default_daily_target,
        "actions": actions,
        "summary": {
            "activate": sum(1 for action in actions if action["action"] == "activate"),
            "maintain": sum(1 for action in actions if action["action"] == "maintain"),
            "archive": sum(1 for action in actions if action["action"] == "archive"),
            "observe": sum(1 for action in actions if action["action"] == "observe"),
        },
    }
