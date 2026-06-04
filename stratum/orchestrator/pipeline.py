#!/usr/bin/env python3
"""Stratum orchestration entrypoint.

Daily runs execute the watchlist/acquisition -> enrich -> verify -> normalize
-> cluster -> edit -> validate -> render chain, then hand fresh artifacts to
SQLite ingest and next-run feedback export.

Higher-scale runs (`weekly`, `monthly`, `quarterly`, `yearly`) dispatch into
the DB-native temporal runner instead of reusing the daily stage chain.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import yaml
from datetime import datetime, timedelta, timezone

from stratum.contracts.report_window import custom_period_id, resolve_report_window
from stratum.deployment import runtime_identity
from stratum.orchestrator import artifacts as artifacts_runtime
from stratum.orchestrator import db_runtime
from stratum.orchestrator import run_context
from stratum.orchestrator import story_runtime
from stratum.orchestrator import watchlist_runtime
from stratum.temporal import TemporalServices, run_higher_scale_output
from stratum.stages.render import artifact_basename

CST = timezone(timedelta(hours=8))

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGES_DIR = os.path.join(PROJECT_ROOT, "stratum", "stages")
DOMAINS_DIR = os.path.join(PROJECT_ROOT, "domains")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

PIPELINE_STAGE_ORDER = [
    "search",
    "enrich",
    "verify",
    "normalize",
    "cluster",
    "edit",
    "validate",
    "repair",
    "validate_recheck",
    "render",
]


def resolve_paths(domain_id: str, run_date: str, output_dir: str, briefing_type: str = "daily") -> dict:
    """Resolve all file paths for a pipeline run."""
    return run_context.resolve_paths(domain_id, run_date, output_dir, briefing_type)


def run_stage(stage_name: str, stage_args: list[str], step_label: str, timeout: int = 120) -> bool:
    """Run a pipeline stage script, fail hard on error."""
    return run_context.run_stage(stage_name, stage_args, step_label, timeout=timeout)


def should_run_stage(from_stage: str | None, stage_name: str) -> bool:
    """Return True if stage_name is at or after the requested resume point."""
    return run_context.should_run_stage(from_stage, stage_name)


def record_stage_status(
    pipeline_status: list[dict],
    stage: str,
    status: str,
    output: str | None = None,
    detail: str | None = None,
    metrics: dict | None = None,
) -> None:
    """Append a structured stage status record for the run manifest."""
    run_context.record_stage_status(pipeline_status, stage, status, output, detail, metrics)


def write_run_manifest(
    manifest_path: str,
    domain: str,
    run_date: str,
    status: str,
    stages: list[dict],
    paths: dict,
    summary: dict | None = None,
    runtime: dict | None = None,
) -> dict:
    """Write the structured pipeline manifest and return its payload."""
    return run_context.write_run_manifest(
        manifest_path,
        domain,
        run_date,
        status,
        stages,
        paths,
        summary,
        runtime,
    )


def db_ingest_modes(from_stage: str | None, skip_agent: bool = False) -> dict[str, bool]:
    """Return which DB ingest surfaces may have fresh data in this run."""
    return run_context.db_ingest_modes(from_stage, skip_agent)


def expanded_source_locales(config: dict) -> list[str]:
    """Expand configured source_languages into concrete locale tags."""
    return run_context.expanded_source_locales(config)


def should_export_thread_keywords_after_ingest(ingest_modes: dict, db_status: dict) -> bool:
    """Return True when SQLite has fresh event data for next-run keywords."""
    return run_context.should_export_thread_keywords_after_ingest(ingest_modes, db_status)


def main():
    parser = argparse.ArgumentParser(description="Stratum deterministic briefing pipeline")
    parser.add_argument("--domain", "-d", required=True,
                        help="Domain ID (e.g., 'storage') — resolves to domains/<id>/domain.yaml")
    parser.add_argument("--date", help="Run date or target period")
    parser.add_argument("--raw-input", help="Path to raw search results JSON (skip agent search)")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip agent-driven stages (search & edit)")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--config", default=CONFIG_PATH,
                        help="Path to config.yaml (default: project config.yaml)")
    parser.add_argument(
        "--timescale",
        default="daily",
        choices=["daily", "weekly", "monthly", "quarterly", "yearly"],
        help="Report timescale",
    )
    parser.add_argument("--start-date", help="Optional custom window start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional custom window end date YYYY-MM-DD")
    parser.add_argument("--lookback-hours", type=int, help="Daily evidence-window lookback in hours")
    parser.add_argument("--from-stage", choices=["enrich", "verify", "normalize", "cluster", "edit", "validate", "repair", "validate_recheck", "render"],
                        help="Start from a specific stage (requires previous output files)")
    parser.add_argument("--web-extract", action="store_true",
                        help="Enable web page fetching to extract dates from HTML meta tags (slow)")
    args = parser.parse_args()
    if args.timescale == "daily" and not args.date:
        print("❌ Daily runs require --date YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)
    if args.lookback_hours and args.timescale != "daily":
        print("❌ --lookback-hours is only supported for --timescale daily", file=sys.stderr)
        sys.exit(1)
    if args.from_stage and args.timescale != "daily":
        print("❌ --from-stage is only supported for --timescale daily", file=sys.stderr)
        sys.exit(1)

    # Validate domain
    domain_config_path = os.path.join(DOMAINS_DIR, args.domain, "domain.yaml")
    if not os.path.exists(domain_config_path):
        print(f"❌ Domain '{args.domain}' not found at {domain_config_path}", file=sys.stderr)
        print(f"   Available domains: {os.listdir(DOMAINS_DIR)}", file=sys.stderr)
        sys.exit(1)

    config_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.config)))
    os.environ["STRATUM_CONFIG_PATH"] = config_path
    runtime = runtime_identity()
    if runtime.get("mode") == "deployment" and not runtime.get("locked"):
        print("❌ Deployment runtime is not locked to version + commit + deployment id", file=sys.stderr)
        sys.exit(1)

    # Load config for output_dir and optional overrides
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    try:
        runtime_dirs = run_context.resolve_runtime_dirs(config, args.output_dir)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
    output_dir = runtime_dirs.output_dir
    db_dir = runtime_dirs.db_dir
    os.environ["STRATUM_DB_DIR"] = db_dir
    reports_dir = runtime_dirs.reports_dir
    health_data_dir = runtime_dirs.health_data_dir

    target_period = args.date
    if args.timescale != "daily" and args.start_date and args.end_date and not target_period:
        target_period = custom_period_id(args.start_date, args.end_date)
    elif not target_period:
        print("❌ Non-daily standard runs require --date; custom runs require --start-date and --end-date", file=sys.stderr)
        sys.exit(1)

    paths = resolve_paths(args.domain, target_period, reports_dir, args.timescale)
    paths["config"] = config_path
    paths["output_dir"] = output_dir
    paths["reports_dir"] = reports_dir
    paths["db_dir"] = db_dir
    paths["health_data_dir"] = health_data_dir
    os.makedirs(paths["data_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(paths["verified"]), exist_ok=True)
    os.makedirs(os.path.dirname(paths["clusters"]), exist_ok=True)
    _remove_legacy_briefing_artifacts(paths)
    _remove_legacy_raw_artifacts(paths)

    pipeline_status = []

    def record(stage: str, status: str, output: str | None = None, detail: str | None = None, metrics: dict | None = None):
        record_stage_status(pipeline_status, stage, status, output, detail, metrics)

    def fail(stage: str, output: str | None = None, detail: str | None = None, metrics: dict | None = None):
        record(stage, "failed", output, detail, metrics)
        write_run_manifest(paths["run_manifest"], args.domain, target_period, "failed",
                           pipeline_status, paths, {"failed_stage": stage}, runtime)
        sys.exit(1)

    def timed_run(stage_name: str, stage_args: list[str], step_label: str, timeout: int = 120) -> tuple[bool, float]:
        start = time.monotonic()
        ok = run_stage(stage_name, stage_args, step_label, timeout=timeout)
        return ok, round(time.monotonic() - start, 3)

    def load_report(path: str) -> dict:
        if not path or not os.path.exists(path):
            return {}
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    if args.timescale != "daily":
        result = run_higher_scale_output(
            args.domain,
            args.timescale,
            target_period,
            paths,
            runtime,
            pipeline_status,
            record,
            fail,
            TemporalServices(
                run_stage=run_stage,
                write_manifest=write_run_manifest,
                domains_dir=DOMAINS_DIR,
            ),
            window_start=args.start_date,
            window_end=args.end_date,
        )
        print(json.dumps(result))
        return

    evidence_window = _daily_evidence_window(args)

    # ── Stage 1: Search (deterministic — calls engine APIs directly) ──
    if not should_run_stage(args.from_stage, "search"):
        print(f"\n⏭️  Skipping search/collect due to --from-stage {args.from_stage}",
              file=sys.stderr)
        record("search", "skipped", paths["raw"], f"--from-stage {args.from_stage}")
        record("collectors", "skipped", paths["raw"], f"--from-stage {args.from_stage}")
    else:
        if args.raw_input:
            # Use provided raw input
            if args.raw_input != paths["raw"]:
                import shutil
                shutil.copy(args.raw_input, paths["raw"])
            record("search", "provided", paths["raw"], args.raw_input)
            print(f"\n📥 Using provided raw input: {paths['raw']}", file=sys.stderr)
        elif args.skip_agent:
            if not os.path.exists(paths["raw"]):
                print(f"❌ --skip-agent but no raw input at {paths['raw']}", file=sys.stderr)
                fail("search", paths["raw"], "--skip-agent missing raw.json")
            record("search", "skipped", paths["raw"], "--skip-agent")
        else:
            # ── Stage 1.0: Collect high-priority fixed sources first ──
            # RSS/direct/browser sources are cheaper and more trusted than broad
            # web search. They seed raw.json; Bocha/Tavily then supplement only
            # broad gaps and domain-scoped queries not already covered here.
            collector_status = _run_collector(
                args.domain,
                PROJECT_ROOT,
                args.date,
                paths["raw"],
                health_data_dir,
                merge_existing=False,
            )
            record("collectors", collector_status.get("status", "unknown"),
                   collector_status.get("output", paths["raw"]), collector_status.get("detail"))

            db_path = os.path.join(db_dir, args.domain, f"{args.domain}.db")
            queries_path = os.path.join(DOMAINS_DIR, args.domain, "queries.yaml")
            if os.path.exists(db_path):
                search_args = _append_daily_acquisition_window([
                    "--domain", args.domain,
                    "--date", args.date,
                    "--config", config_path,
                    "--db", db_path,
                    "--queries", queries_path,
                    "--output", paths["raw"],
                    "--stats", paths["search_stats"],
                    "--existing-raw", paths["raw"],
                    "--skip-covered-domain-queries",
                ], evidence_window)
                if not run_stage("search", search_args, "1/8 Search", timeout=300):
                    fail("search", paths["raw"])
                search_status, search_detail = _search_stage_status(paths["search_stats"])
                record("search", search_status, paths["raw"], search_detail or "db")
                _update_post_collect_search_stats(paths["raw"], _load_raw_results(paths["raw"]))
                _try_ingest_search_stats(args.domain, paths["search_stats"], run_date=args.date)
            else:
                search_args = _append_daily_acquisition_window([
                    "--domain", args.domain,
                    "--date", args.date,
                    "--config", config_path,
                    "--queries", queries_path,
                    "--output", paths["raw"],
                    "--stats", paths["search_stats"],
                    "--existing-raw", paths["raw"],
                    "--skip-covered-domain-queries",
                ], evidence_window)
                if not run_stage("search", search_args, "1/8 Search", timeout=300):
                    fail("search", paths["raw"])
                search_status, search_detail = _search_stage_status(paths["search_stats"])
                record("search", search_status, paths["raw"], search_detail or "queries.yaml")
                _update_post_collect_search_stats(paths["raw"], _load_raw_results(paths["raw"]))
                _try_ingest_search_stats(args.domain, paths["search_stats"], run_date=args.date)
        if args.raw_input or args.skip_agent:
            # Preserve previous behavior for explicit raw-input/resume modes:
            # deterministic collectors may still refresh/augment the provided
            # raw pool unless the caller starts from a later stage.
            collector_status = _run_collector(args.domain, PROJECT_ROOT, args.date, paths["raw"], health_data_dir)
            record("collectors", collector_status.get("status", "unknown"),
                   collector_status.get("output", paths["raw"]), collector_status.get("detail"))

    # ── Stage 2: Enrich ──
    enrich_cmd = [
        "--input", paths["raw"],
        "--output", paths["enriched"],
        "--date", args.date,
    ]
    if getattr(args, "web_extract", False):
        enrich_cmd.append("--web-extract")
    if should_run_stage(args.from_stage, "enrich"):
        if not run_stage("enrich", enrich_cmd, "2/8 Enrich dates"):
            fail("enrich", paths["enriched"])
        record("enrich", "success", paths["enriched"])
    else:
        print(f"\n⏭️  Skipping enrich due to --from-stage {args.from_stage}", file=sys.stderr)
        record("enrich", "skipped", paths["enriched"], f"--from-stage {args.from_stage}")

    # ── Stage 3: Verify ──
    if should_run_stage(args.from_stage, "verify"):
        verify_args = [
            "--input", paths["enriched"],
            "--output", paths["verified"],
            "--stats", paths["verify_stats"],
            "--date", args.date,
            "--domain", paths["domain_config"],
        ]
        if evidence_window:
            verify_args += ["--stale-days", str(evidence_window["stale_days"])]
        if not run_stage("verify", verify_args, "3/8 Verify articles"):
            fail("verify", paths["verified"])
        record("verify", "success", paths["verified"])
    else:
        print(f"\n⏭️  Skipping verify due to --from-stage {args.from_stage}", file=sys.stderr)
        record("verify", "skipped", paths["verified"], f"--from-stage {args.from_stage}")

    # ── Stage 4: Normalize ──
    normalize_args = [
        "--input", paths["verified"],
        "--output", paths["articles"],
        "--domain", paths["domain_config"],
    ]
    # Closed-loop: feed previous day's thread_keywords to normalize
    if os.path.exists(paths["thread_keywords"]):
        normalize_args += ["--thread-keywords", paths["thread_keywords"]]
    if should_run_stage(args.from_stage, "normalize"):
        if not run_stage("normalize", normalize_args, "4/8 Normalize articles"):
            fail("normalize", paths["articles"])
        record("normalize", "success", paths["articles"])
    else:
        print(f"\n⏭️  Skipping normalize due to --from-stage {args.from_stage}",
              file=sys.stderr)
        record("normalize", "skipped", paths["articles"], f"--from-stage {args.from_stage}")

    # ── Stage 5: Cluster ──
    if should_run_stage(args.from_stage, "cluster"):
        ok, duration = timed_run("cluster", [
            "--input", paths["articles"],
            "--output", paths["clusters"],
            "--domain", paths["domain_config"],
            "--date", args.date,
            "--threshold", "0.50",
        ], "5/10 Story clustering")
        if not ok:
            fail("cluster", paths["clusters"])
        record("cluster", "success", paths["clusters"], metrics={"duration_seconds": duration})
    else:
        print(f"\n⏭️  Skipping cluster due to --from-stage {args.from_stage}", file=sys.stderr)
        record("cluster", "skipped", paths["clusters"], f"--from-stage {args.from_stage}")

    # ── Stage 6: Agent Edit (LLM) ──
    # Generate story context before the agent runs
    story_ctx_path = os.path.join(paths["data_dir"], "story_context.json")
    if should_run_stage(args.from_stage, "edit"):
        _try_generate_story_context(args.domain, args.date, paths, story_ctx_path)

    if not should_run_stage(args.from_stage, "edit"):
        print(f"\n⏭️  Skipping edit due to --from-stage {args.from_stage}", file=sys.stderr)
        record("edit", "skipped", paths["briefing_md"], f"--from-stage {args.from_stage}")
    elif args.skip_agent:
        if not os.path.exists(paths["briefing_md"]):
            print(f"⚠️  --skip-agent but no briefing markdown at {paths['briefing_md']}", file=sys.stderr)
        record("edit", "skipped", paths["briefing_md"], "--skip-agent")
    else:
        # Deterministic LLM call via edit.py
        ok, duration = timed_run("edit", [
            "--domain", args.domain,
            "--date", args.date,
            "--articles", paths["articles"],
            "--clusters", paths["clusters"],
            "--context", story_ctx_path,
            "--config", config_path,
            "--output", paths["briefing_md"],
            "--plan-output", paths["briefing_plan"],
            "--chunks-output", paths["briefing_chunks"],
            "--trace-output", paths["edit_trace"],
            "--timescale", "daily",
        ], "6/10 Agent Edit (LLM)", timeout=720)
        if not ok:
            print("❌ Agent Edit failed — stopping before validate/render to avoid reusing stale briefing artifacts", file=sys.stderr)
            fail("edit", paths["briefing_md"])
        else:
            trace = load_report(paths["edit_trace"])
            record(
                "edit",
                "success",
                paths["briefing_md"],
                metrics={
                    "duration_seconds": duration,
                    "planned_total_items": trace.get("plan_counts", {}).get("total_items"),
                    "planned_main_items": trace.get("plan_counts", {}).get("main_items"),
                    "planned_edge_items": trace.get("plan_counts", {}).get("edge_items"),
                },
            )

    # ── Stage 7: Validate ──
    event_threads_path = os.path.join(paths["data_dir"], "event-threads.json")
    schemas_dir = os.path.join(STAGES_DIR, "edit", "prompts", "_schemas")
    validate_args = [
        "--md", paths["briefing_md"],
        "--articles", paths["articles"],
        "--date", args.date,
        "--domain", paths["domain_config"],
        "--output-report", paths["validate_report"],
    ]
    if os.path.exists(event_threads_path) and os.path.exists(schemas_dir):
        validate_args += [
            "--event-threads", event_threads_path,
            "--schemas-dir", schemas_dir,
        ]

    if not should_run_stage(args.from_stage, "validate"):
        print(f"\n⏭️  Skipping validate due to --from-stage {args.from_stage}", file=sys.stderr)
        record("validate", "skipped", None, f"--from-stage {args.from_stage}")
    elif os.path.exists(paths["briefing_md"]) and os.path.exists(paths["articles"]):
        ok, duration = timed_run("validate", validate_args, "7/10 Validate briefing")
        validate_report = load_report(paths["validate_report"])
        validate_metrics = {
            "duration_seconds": duration,
            "violations": validate_report.get("violations"),
            "invalid_items": validate_report.get("summary", {}).get("invalid_items"),
        }
        if ok:
            record("validate", "success", paths["validate_report"], metrics=validate_metrics)
        else:
            record("validate", "violations", paths["validate_report"], metrics=validate_metrics)
    else:
        print("\n⚠️  Skipping validate: briefing markdown or articles.jsonl not found", file=sys.stderr)
        record("validate", "skipped", None, "missing briefing markdown or articles.jsonl")

    # ── Stage 8: Repair ──
    validate_report = load_report(paths["validate_report"])
    needs_repair = validate_report.get("status") == "violations"
    if not should_run_stage(args.from_stage, "repair"):
        print(f"\n⏭️  Skipping repair due to --from-stage {args.from_stage}", file=sys.stderr)
        record("repair", "skipped", paths["repair_report"], f"--from-stage {args.from_stage}")
    elif not needs_repair and args.from_stage != "repair":
        with open(paths["repair_report"], "w") as f:
            json.dump({
                "status": "no_changes",
                "input_status": validate_report.get("status"),
                "input_violations": int(validate_report.get("violations") or 0),
                "validate_rounds": 1,
                "rewritten_items": 0,
                "dropped_items": 0,
                "unchanged_invalid_items": 0,
                "item_actions": [],
            }, f, ensure_ascii=False, indent=2)
        record("repair", "skipped", paths["repair_report"], "validate passed; repair not needed")
    elif os.path.exists(paths["briefing_md"]) and os.path.exists(paths["articles"]) and os.path.exists(paths["validate_report"]):
        ok, duration = timed_run("repair", [
            "--md", paths["briefing_md"],
            "--articles", paths["articles"],
            "--date", args.date,
            "--domain", paths["domain_config"],
            "--validate-report", paths["validate_report"],
            "--output-report", paths["repair_report"],
        ], "8/10 Repair briefing")
        repair_report = load_report(paths["repair_report"])
        metrics = {
            "duration_seconds": duration,
            "rewritten_items": repair_report.get("rewritten_items"),
            "dropped_items": repair_report.get("dropped_items"),
            "unchanged_invalid_items": repair_report.get("unchanged_invalid_items"),
            "validate_rounds": repair_report.get("validate_rounds"),
        }
        if not ok:
            fail("repair", paths["repair_report"], metrics=metrics)
        record("repair", "success", paths["repair_report"], metrics=metrics)
    else:
        print("\n⚠️  Skipping repair: briefing markdown, articles.jsonl, or validate_report.json not found", file=sys.stderr)
        record("repair", "skipped", paths["repair_report"], "missing briefing markdown, articles.jsonl, or validate_report.json")

    # ── Stage 9: Revalidate repaired briefing ──
    if not should_run_stage(args.from_stage, "validate_recheck"):
        print(f"\n⏭️  Skipping validate_recheck due to --from-stage {args.from_stage}", file=sys.stderr)
        record("validate_recheck", "skipped", paths["validate_report"], f"--from-stage {args.from_stage}")
    elif needs_repair or args.from_stage in {"repair", "validate_recheck"}:
        ok, duration = timed_run("validate_recheck", validate_args, "9/10 Revalidate repaired briefing")
        validate_report = load_report(paths["validate_report"])
        metrics = {
            "duration_seconds": duration,
            "violations": validate_report.get("violations"),
            "invalid_items": validate_report.get("summary", {}).get("invalid_items"),
        }
        if not ok:
            print("❌ Revalidation failed — stopping before render/DB ingest to avoid publishing invalid artifacts", file=sys.stderr)
            fail("validate_recheck", paths["validate_report"], metrics=metrics)
        record("validate_recheck", "success", paths["validate_report"], metrics=metrics)
    else:
        record("validate_recheck", "skipped", paths["validate_report"], "repair not needed")

    # ── Stage 10: Render ──
    if not should_run_stage(args.from_stage, "render"):
        print(f"\n⏭️  Skipping render due to --from-stage {args.from_stage}", file=sys.stderr)
        record("render", "skipped", paths["briefing_html"], f"--from-stage {args.from_stage}")
    elif os.path.exists(paths["briefing_md"]):
        # Resolve channel title from domain config
        channel_title = "Briefing"
        try:
            with open(paths["domain_config"]) as f:
                domain_cfg = yaml.safe_load(f)
            channel_title = domain_cfg.get("domain", {}).get("title", "Briefing")
        except Exception:
            pass
        ok, duration = timed_run("render", [
            "--input", paths["briefing_md"],
            "--output-dir", paths["data_dir"],
            "--title", channel_title,
            "--domain", paths["domain_config"],
            "--domain-id", args.domain,
            "--briefing-type", "daily",
            "--date", args.date,
            "--footer", "由 AI Agent 自动生成 · 每日 7:30 CST",
            "--template", os.path.join(DOMAINS_DIR, args.domain, "templates", "daily.html"),
        ], "10/10 Render HTML + PDF")
        if ok:
            record("render", "success", paths["briefing_html"], metrics={"duration_seconds": duration})
        else:
            record("render", "failed_nonblocking", paths["briefing_html"], metrics={"duration_seconds": duration})
    else:
        print("\n⚠️  Skipping render: briefing markdown not found", file=sys.stderr)
        record("render", "skipped", paths["briefing_html"], "missing briefing markdown")
    print(f"{'='*60}", file=sys.stderr)

    # ── DB Ingestion: write structured data to SQLite ──
    # NOTE: old file-layer story writes are deprecated.
    # DB ingest writes directly to SQLite from event-threads.json.
    # Story-tracking reads (_try_generate_story_context, _export_thread_keywords) now query SQLite.
    ingest_modes = db_ingest_modes(args.from_stage, args.skip_agent)
    if any(ingest_modes.values()):
        db_status = _try_db_ingest(
            args.domain,
            args.date,
            paths,
            db_dir,
            ingest_events=ingest_modes["events"],
            ingest_entities=ingest_modes["entities"],
            watch_locales=expanded_source_locales(config),
        )
        record(
            "db_ingest",
            db_status.get("status", "unknown"),
            db_status.get("output"),
            db_status.get("detail"),
        )
        if should_export_thread_keywords_after_ingest(ingest_modes, db_status):
            _export_thread_keywords(args.domain, paths)
    else:
        record("db_ingest", "skipped", None, f"--from-stage {args.from_stage}")

    # ── Summary ──
    article_count = 0
    if os.path.exists(paths["articles"]):
        with open(paths["articles"]) as f:
            article_count = sum(1 for _ in f)

    cluster_count = 0
    if os.path.exists(paths["clusters"]):
        with open(paths["clusters"]) as f:
            clusters_data = json.load(f)
            cluster_count = len(clusters_data.get("clusters", []))

    summary = {
        "timescale": "daily",
        "articles": article_count,
        "clusters": cluster_count,
        "report_window": resolve_report_window("daily", args.date).to_dict(),
    }
    if evidence_window:
        summary["evidence_window"] = evidence_window
    if os.path.exists(paths["validate_report"]):
        validate_report = load_report(paths["validate_report"])
        summary["quality"] = {
            "validate_status": validate_report.get("status"),
            "validate_violations": validate_report.get("violations"),
            "invalid_items": validate_report.get("summary", {}).get("invalid_items"),
        }
    if os.path.exists(paths["repair_report"]):
        repair_report = load_report(paths["repair_report"])
        summary["quality"] = {
            **summary.get("quality", {}),
            "validate_rounds": repair_report.get("validate_rounds"),
            "rewritten_items": repair_report.get("rewritten_items"),
            "dropped_items": repair_report.get("dropped_items"),
            "unchanged_invalid_items": repair_report.get("unchanged_invalid_items"),
        }
    write_run_manifest(paths["run_manifest"], args.domain, args.date, "ok",
                       pipeline_status, paths, summary, runtime)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  PIPELINE COMPLETE", file=sys.stderr)
    print(f"  Domain:    {args.domain}", file=sys.stderr)
    print(f"  Date:      {args.date}", file=sys.stderr)
    print(f"  Articles:  {article_count}", file=sys.stderr)
    print(f"  Clusters:  {cluster_count}", file=sys.stderr)
    print(f"  Data dir:  {paths['data_dir']}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    print(json.dumps({
        "status": "ok",
        "domain": args.domain,
        "date": args.date,
        "articles": article_count,
        "clusters": cluster_count,
        "runtime": runtime,
        "paths": {k: v for k, v in paths.items()},
    }))


# ── Story-Tracking Integration Helpers ──

def _try_ingest_search_stats(domain_id: str, stats_path: str, run_date: str) -> int:
    """Compatibility wrapper for DB query-stat ingest."""
    return db_runtime.try_ingest_search_stats(domain_id, stats_path, run_date)


def _search_stage_status(search_stats_path: str) -> tuple[str, str | None]:
    """Return manifest status/detail for the daily broad-discovery stage."""
    if not os.path.exists(search_stats_path):
        return "success", None
    try:
        with open(search_stats_path) as f:
            stats = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "success", None

    queries = [
        query
        for query in (stats.get("queries") or [])
        if query.get("status") != "skipped_covered"
    ]
    if not queries:
        return "success", None

    discovery_raw = stats.get("diagnostics", {}).get("search_raw")
    if discovery_raw is None:
        discovery_raw = int(stats.get("total_raw") or 0)

    if int(discovery_raw or 0) == 0 and all(query.get("status") == "failed" for query in queries):
        return "failed_nonblocking", "all discovery queries failed"
    return "success", None


def _remove_legacy_briefing_artifacts(paths: dict) -> None:
    artifacts_runtime.remove_legacy_briefing_artifacts(paths)


def _remove_legacy_raw_artifacts(paths: dict) -> None:
    artifacts_runtime.remove_legacy_raw_artifacts(paths)


def _try_generate_story_context(domain_id: str, run_date: str, paths: dict, output_path: str):
    story_runtime.try_generate_story_context(domain_id, run_date, paths, output_path)


def _export_thread_keywords(domain_id: str, paths: dict):
    story_runtime.export_thread_keywords(domain_id, paths)


def _try_db_ingest(
    domain_id: str,
    run_date: str,
    paths: dict,
    db_dir: str,
    ingest_events: bool = True,
    ingest_entities: bool = True,
    watch_locales: list[str] | None = None,
) -> dict:
    return db_runtime.try_db_ingest(
        domain_id,
        run_date,
        paths,
        db_dir,
        ingest_events=ingest_events,
        ingest_entities=ingest_entities,
        watch_locales=watch_locales,
    )


def _persist_event_watch_queries(
    domain_id: str,
    event_threads_path: str,
    watch_locales: list[str],
    upsert_fn,
    run_date: str,
) -> int:
    return db_runtime.persist_event_watch_queries(
        domain_id,
        event_threads_path,
        watch_locales,
        upsert_fn,
        run_date,
    )


def _normalize_thread_priority(priority) -> str:
    return db_runtime.normalize_thread_priority(priority)


def _run_watchlist(
    domain: str,
    workspace: str,
    run_date: str,
    raw_path: str,
    health_data_dir: str | None = None,
    merge_existing: bool = True,
):
    return watchlist_runtime.run_watchlist(
        domain,
        workspace,
        run_date,
        raw_path,
        health_data_dir=health_data_dir,
        merge_existing=merge_existing,
    )


def _run_collector(
    domain: str,
    workspace: str,
    run_date: str,
    raw_path: str,
    health_data_dir: str | None = None,
    merge_existing: bool = True,
):
    """Compatibility alias for older tests and callers."""
    return _run_watchlist(
        domain,
        workspace,
        run_date,
        raw_path,
        health_data_dir=health_data_dir,
        merge_existing=merge_existing,
    )


def _load_raw_results(raw_path: str) -> list[dict]:
    return watchlist_runtime.load_raw_results(raw_path)


def _update_post_collect_search_stats(raw_path: str, merged_results: list[dict]) -> None:
    watchlist_runtime.CONFIG_PATH = CONFIG_PATH
    watchlist_runtime.update_post_collect_search_stats(raw_path, merged_results)


def _coverage_entities_from_domain_config(domain_config_path: str) -> list[str]:
    return story_runtime.coverage_entities_from_domain_config(domain_config_path)


def _daily_evidence_window(args: argparse.Namespace) -> dict | None:
    """Resolve an explicit daily evidence window for acquisition and verify."""
    if getattr(args, "timescale", "daily") != "daily":
        return None
    start_date = getattr(args, "start_date", None)
    end_date = getattr(args, "end_date", None)
    lookback_hours = getattr(args, "lookback_hours", None)
    run_date = getattr(args, "date")

    if lookback_hours:
        end_dt = datetime.fromisoformat(run_date)
        window_days = max(1, int((int(lookback_hours) + 23) // 24))
        start_dt = end_dt - timedelta(days=window_days - 1)
        start_date = start_dt.date().isoformat()
        end_date = end_dt.date().isoformat()
    elif start_date or end_date:
        window = resolve_report_window("daily", run_date, start_date=start_date, end_date=end_date)
        start_date = window.start_date
        end_date = window.end_date
        window_days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days + 1
    else:
        return None

    return {
        "start_date": start_date,
        "end_date": end_date,
        "stale_days": window_days,
        "window_days": window_days,
        "lookback_hours": lookback_hours,
    }


def _append_daily_acquisition_window(stage_args: list[str], evidence_window: dict | None) -> list[str]:
    """Append acquisition window args when a daily evidence window is active."""
    if not evidence_window:
        return list(stage_args)
    return list(stage_args) + [
        "--start-date", evidence_window["start_date"],
        "--end-date", evidence_window["end_date"],
    ]


if __name__ == "__main__":
    main()
