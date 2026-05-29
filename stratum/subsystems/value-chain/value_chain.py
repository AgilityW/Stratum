"""Value Chain Monitor — Runtime config management and evolution.

Deterministic core: runtime-config schema, layer merge, template productivity tracking,
probation/promotion/demotion logic, state.json generation.

LLM-driven discovery and source evaluation is documented in skills/value-chain-monitor/SKILL.md.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

CST = timezone(timedelta(hours=8))

# ── Constants ──

MAX_SEED_SOURCES_PER_LAYER = 15
MAX_TEMPLATES_PER_LAYER = 5
MAX_QUERIES_PER_LAYER = 8
PROBATION_DAYS = 30
PROMOTE_THRESHOLD = 0.70
DEMOTE_THRESHOLD = 0.40
REVIEW_INTERVAL_DAYS = 90

ARCHIVE_THRESHOLDS = {
    "critical": None,   # never auto-archive
    "high": 16,         # weeks
    "medium": 8,
}


def init_runtime_config(layers: list[dict], run_date: str, base_hash: str) -> dict:
    """Initialize runtime-config.json from domain.yaml layers."""
    rc = {
        "base_version": base_hash,
        "last_baseline": run_date,
        "layers": {},
        "audit_log": [],
    }
    for layer in layers:
        rc["layers"][layer["id"]] = {
            "promoted_sources": [],
            "archived_sources": [],
            "template_productivity": {},
            "archived_templates": [],
            "active_demotions": [],
            "cap_overflow": [],
        }
    return rc


def merge_layers(layers: list[dict], rc: dict) -> list[dict]:
    """Merge domain.yaml base layers with runtime-config promoted sources/templates."""
    active = []
    for layer in layers:
        lid = layer["id"]
        rc_layer = rc["layers"].get(lid, {})
        base_sources = {s["name"] for s in layer.get("seed_sources", [])}
        promoted = [s for s in rc_layer.get("promoted_sources", [])
                    if s.get("probation_status") != "demoted"]

        # Cap sources
        available_slots = max(0, MAX_SEED_SOURCES_PER_LAYER - len(base_sources))
        active_promoted = promoted[:available_slots]
        overflow = promoted[available_slots:]

        merged = dict(layer)
        merged["_active_seed_sources"] = layer.get("seed_sources", []) + [
            {"name": p["name"], "aliases": p.get("aliases", {})} for p in active_promoted
        ]
        merged["_overflow_promoted"] = overflow
        merged["_active_templates"] = [
            t for t in layer.get("probe_templates", [])
            if t not in rc_layer.get("archived_templates", [])
        ]
        merged["_template_cap_full"] = len(layer.get("probe_templates", [])) >= MAX_TEMPLATES_PER_LAYER
        active.append(merged)
    return active


def should_probe_layer(layer: dict, today: date, coverage_log: list[dict]) -> bool:
    """Determine if a layer should be probed based on frequency and last probe date."""
    freq = layer.get("frequency", "weekly")
    if freq == "daily":
        return False  # covered by main pipeline

    last_probe = None
    for entry in reversed(coverage_log):
        if entry.get("layer_id") == layer["id"] and entry.get("type") == "probe":
            last_probe = entry
            break

    if last_probe is None:
        return True

    days_since = (today - date.fromisoformat(last_probe["date"])).days
    intervals = {"weekly": 7, "biweekly": 14, "monthly": 28}
    return days_since >= intervals.get(freq, 7)


def archive_stale_templates(layers: list[dict], rc: dict, today: date) -> dict:
    """Archive templates with zero output streaks exceeding thresholds."""
    for layer in layers:
        lid = layer["id"]
        rc_layer = rc["layers"].get(lid, {})
        threshold = ARCHIVE_THRESHOLDS.get(layer.get("criticality"))

        if threshold is None:
            continue

        productivity = rc_layer.get("template_productivity", {})
        for template, stats in productivity.items():
            if stats.get("status") != "active":
                continue
            try:
                last_output = date.fromisoformat(stats["last_output"])
            except (ValueError, KeyError):
                continue
            weeks_since = (today - last_output).days / 7
            if weeks_since >= threshold:
                stats["status"] = "archived"
                rc_layer.setdefault("archived_templates", []).append(template)
                rc.setdefault("audit_log", []).append({
                    "ts": today.isoformat(),
                    "action": "archive_template",
                    "layer": lid,
                    "template": template,
                    "reason": f"{int(weeks_since)}w_no_output",
                })
    return rc


def process_probation(rc: dict, layers: list[dict], today: date) -> dict:
    """Process probation midterm evaluations and 90-day reviews."""
    for layer in layers:
        lid = layer["id"]
        rc_layer = rc["layers"].get(lid, {})
        tier = layer.get("criticality", "medium")

        for source in rc_layer.get("promoted_sources", []):
            # Probation midterm (day 30)
            if (source.get("probation_status") == "active"
                    and source.get("midterm_eval") is None
                    and source.get("probation_end")):
                try:
                    probation_end = date.fromisoformat(source["probation_end"])
                except ValueError:
                    continue
                if today >= probation_end:
                    score = source.get("promote_score", 0.5)
                    source["midterm_eval"] = {"date": today.isoformat(), "score": round(score, 3)}

                    if score >= PROMOTE_THRESHOLD:
                        source["probation_status"] = "confirmed"
                        source["confirmed_at"] = today.isoformat()
                    elif score < DEMOTE_THRESHOLD:
                        source["probation_status"] = "demoted"
                        source["demoted_at"] = today.isoformat()
                        source["demoted_reason"] = f"probation_failed_score_{score:.3f}"
                    else:
                        source["probation_end"] = (today + timedelta(days=30)).isoformat()

            # 90-day review for confirmed sources
            if (source.get("probation_status") == "confirmed"
                    and source.get("confirmed_at")):
                try:
                    confirmed_date = date.fromisoformat(source["confirmed_at"])
                except ValueError:
                    continue
                days_since = (today - confirmed_date).days
                if days_since >= REVIEW_INTERVAL_DAYS and days_since % REVIEW_INTERVAL_DAYS < 7:
                    score = source.get("promote_score", 0.5)
                    source["last_review"] = {"date": today.isoformat(), "score": round(score, 3)}

                    if tier == "critical":
                        if score < 0.5:
                            source["flagged_for_review"] = True
                    elif tier == "high":
                        if score < 0.5:
                            prev_score = source.get("last_review", {}).get("score", 1.0)
                            if prev_score < 0.5:
                                source["probation_status"] = "demoted"
                                source["demoted_at"] = today.isoformat()
                    elif tier == "medium":
                        if score < 0.5:
                            source["probation_status"] = "demoted"
                            source["demoted_at"] = today.isoformat()

    return rc


def build_state(layers: list[dict], rc: dict, coverage_log: list[dict], run_date: str) -> dict:
    """Generate state.json summary for debugging."""
    state = {"date": run_date, "layers": {}}
    for layer in layers:
        lid = layer["id"]
        rc_layer = rc["layers"].get(lid, {})
        promo_count = len([s for s in rc_layer.get("promoted_sources", [])
                           if s.get("probation_status") != "demoted"])
        base_count = len(layer.get("seed_sources", []))
        total = base_count + promo_count

        last_probe = None
        for entry in reversed(coverage_log):
            if entry.get("layer_id") == lid:
                last_probe = entry
                break

        state["layers"][lid] = {
            "label": layer.get("label", lid),
            "criticality": layer.get("criticality", "medium"),
            "base_sources": base_count,
            "promoted_sources": promo_count,
            "total_sources": total,
            "cap": MAX_SEED_SOURCES_PER_LAYER,
            "cap_percent": round(total / MAX_SEED_SOURCES_PER_LAYER * 100),
            "active_templates": len([t for t in layer.get("probe_templates", [])
                                     if t not in rc_layer.get("archived_templates", [])]),
            "archived_templates": len(rc_layer.get("archived_templates", [])),
            "last_probe": last_probe["date"] if last_probe else "never",
        }
    return state
