"""Attach signal-awareness review outputs to a completed daily run.

This module does not modify the main daily pipeline contract. It reuses the
normal daily run outputs, then computes signal-awareness outputs and a compact
operator markdown summary for next-run collection readiness review.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from stratum.orchestrator import pipeline as daily_pipeline
from stratum.orchestrator import run_context
from stratum.source_trace.loader import load_inputs
from stratum.subsystems.signal_awareness import detect_signal_awareness, write_signal_awareness


PROJECT_ROOT = run_context.PROJECT_ROOT
DOMAINS_DIR = run_context.DOMAINS_DIR
CONFIG_PATH = daily_pipeline.CONFIG_PATH


def load_config(domain_id: str) -> dict[str, Any]:
    """Load the optional domain-owned signal-awareness config."""
    path = Path(DOMAINS_DIR) / domain_id / "signal_awareness.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def shared_paths(reports_dir: str, domain_id: str) -> dict[str, str]:
    """Return shared history/state paths for repeated signal-awareness reviews."""
    base_dir = Path(reports_dir) / domain_id / "data" / "signal-awareness"
    return {
        "base_dir": str(base_dir),
        "history": str(base_dir / "signal_history.jsonl"),
        "state": str(base_dir / "active_signals.json"),
    }


def run_paths(data_dir: str) -> dict[str, str]:
    """Return current-run signal-awareness artifact paths."""
    return {
        "signal_awareness": os.path.join(data_dir, "signal_awareness.json"),
        "signal_activation_plan": os.path.join(data_dir, "signal_plan.json"),
        "signal_review_md": os.path.join(data_dir, "signal_review.md"),
    }


def load_history(history_path: str, *, limit: int = 28) -> list[dict[str, Any]]:
    """Load recent signal-awareness snapshots for baseline comparison."""
    path = Path(history_path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-limit:]


def append_history(history_path: str, snapshot: dict[str, Any]) -> None:
    """Append the current snapshot to shared signal-awareness history."""
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


def load_active_signals(state_path: str) -> list[dict[str, Any]]:
    """Load active signal-preparation state from prior runs."""
    path = Path(state_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return payload.get("active_signals", []) if isinstance(payload, dict) else []


def store_active_signals(state_path: str, activation_plan: dict[str, Any]) -> None:
    """Persist active signal-preparation state derived from the current plan."""
    active_signals = [
        {
            "anchor_id": action["anchor_id"],
            "anchor_name": action["anchor_name"],
            "action": action["action"],
            "daily_target_after": action["daily_target_after"],
            "temporary_sources": action["temporary_sources"],
            "direct_fetch_targets": action["direct_fetch_targets"],
            "query_injections": action["query_injections"],
        }
        for action in activation_plan.get("actions", [])
        if action.get("action") in {"activate", "maintain"}
    ]
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active_signals": active_signals}, ensure_ascii=False, indent=2))


def build_records(data_dir: str) -> list[dict[str, Any]]:
    """Flatten acquisition-side artifacts into one record list for signal sensing."""
    payload = load_inputs(data_dir)
    records: list[dict[str, Any]] = []
    for key in (
        "watchlist_observations",
        "discovery_observations",
        "watchlist_candidates",
        "discovery_candidates",
        "watchlist_results",
        "raw",
    ):
        value = payload.get(key, [])
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def render_review(payload: dict[str, Any]) -> str:
    """Render a compact operator-facing markdown summary for one review run."""
    lines = [
        "# Signal Review",
        "",
        f"- Domain: `{payload.get('domain', '')}`",
        f"- Run date: `{payload.get('run_date', '')}`",
        f"- Records scanned: `{payload.get('diagnostics', {}).get('record_count', 0)}`",
        f"- Anomalous topics: `{payload.get('diagnostics', {}).get('anomalous_topics', 0)}`",
        f"- Detected anchors: `{payload.get('diagnostics', {}).get('detected_anchors', 0)}`",
        "",
        "## Topic Signals",
    ]
    topic_signals = payload.get("topic_signals", [])
    if not topic_signals:
        lines.append("- None")
    else:
        for signal in topic_signals[:8]:
            lines.append(
                f"- `{signal['topic_id']}`: current `{signal['current_count']}`, "
                f"baseline `{signal['baseline_mean']}`, z-score `{signal['z_score']}`"
            )
    lines.extend(["", "## Preparation Actions"])
    actions = payload.get("activation_plan", {}).get("actions", [])
    if not actions:
        lines.append("- None")
    else:
        for action in actions:
            lines.append(
                f"- `{action['anchor_name']}` -> `{action['action']}` "
                f"(reason: `{action['reason']}`, queries: `{len(action['query_injections'])}`, "
                f"temp_sources: `{len(action['temporary_sources'])}`)"
            )
    lines.extend(["", "## Unanchored Clusters"])
    clusters = payload.get("unanchored_clusters", [])
    if not clusters:
        lines.append("- None")
    else:
        for cluster in clusters[:5]:
            lines.append(
                f"- `{cluster['label']}`: `{cluster['record_count']}` records, "
                f"sources `{', '.join(cluster['sources'])}`"
            )
    return "\n".join(lines) + "\n"


def run_attach(
    *,
    domain_id: str,
    run_date: str,
    reports_dir: str,
    data_dir: str,
) -> dict[str, Any]:
    """Run signal awareness over an existing daily run directory."""
    config = load_config(domain_id)
    shared = shared_paths(reports_dir, domain_id)
    current_paths = run_paths(data_dir)
    history = load_history(shared["history"])
    active_signals = load_active_signals(shared["state"])
    records = build_records(data_dir)
    payload = detect_signal_awareness(
        domain=domain_id,
        run_date=run_date,
        records=records,
        topic_rules=config.get("topic_rules", []),
        anchor_registry=config.get("anchors", []),
        historical_snapshots=history,
        active_signals=active_signals,
    )
    written = write_signal_awareness(data_dir, payload)
    Path(current_paths["signal_review_md"]).write_text(
        render_review(payload)
    )
    append_history(shared["history"], payload["snapshot"])
    store_active_signals(shared["state"], payload["activation_plan"])
    return {
        "payload": payload,
        "paths": {
            **written,
            "signal_review_md": current_paths["signal_review_md"],
            "history": shared["history"],
            "state": shared["state"],
        },
    }


def run_daily_pipeline_subprocess(args: argparse.Namespace) -> None:
    """Run the normal daily pipeline unchanged before attaching signal awareness."""
    script = os.path.join(PROJECT_ROOT, "stratum", "orchestrator", "pipeline.py")
    cmd = [
        sys.executable,
        script,
        "--domain", args.domain,
        "--date", args.date,
        "--config", args.config,
    ]
    if args.output_dir:
        cmd.extend(["--output-dir", args.output_dir])
    if args.raw_input:
        cmd.extend(["--raw-input", args.raw_input])
    if args.skip_agent:
        cmd.append("--skip-agent")
    if args.lookback_hours:
        cmd.extend(["--lookback-hours", str(args.lookback_hours)])
    if args.web_extract:
        cmd.append("--web-extract")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attach signal-awareness review outputs to a completed daily run"
    )
    parser.add_argument("--domain", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--output-dir")
    parser.add_argument("--raw-input")
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--web-extract", action="store_true")
    parser.add_argument(
        "--reuse-existing-run",
        action="store_true",
        help="Do not run the normal daily pipeline first; attach signal awareness to existing artifacts only.",
    )
    args = parser.parse_args()

    config_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.config)))
    if os.path.exists(config_path):
        config = yaml.safe_load(Path(config_path).read_text()) or {}
    else:
        config = {}
    runtime_dirs = run_context.resolve_runtime_dirs(config, args.output_dir)
    reports_dir = runtime_dirs.reports_dir
    paths = daily_pipeline.resolve_paths(args.domain, args.date, reports_dir, "daily")

    if not args.reuse_existing_run:
        run_daily_pipeline_subprocess(args)

    result = run_attach(
        domain_id=args.domain,
        run_date=args.date,
        reports_dir=reports_dir,
        data_dir=paths["data_dir"],
    )
    print(json.dumps({
        "status": "ok",
        "mode": "signal_attach",
        "domain": args.domain,
        "date": args.date,
        "paths": result["paths"],
        "diagnostics": result["payload"]["diagnostics"],
        "activation_summary": result["payload"]["activation_plan"]["summary"],
    }))


if __name__ == "__main__":
    main()
