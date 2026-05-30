#!/usr/bin/env python3
"""pipeline.py — Stratum deterministic briefing pipeline orchestrator.

Domain-agnostic. Injects domain config into each stage.
Agent stages (search, edit) are clearly marked — they require LLM calls.

Stages:
  1. Agent Search → raw.json       (LLM — external)
  2. enrich      → enriched.json   (deterministic)
  3. verify      → verified.jsonl  (deterministic)
  4. normalize   → articles.jsonl  (deterministic)
  5. cluster     → clusters.json   (deterministic)
  6. Agent Edit  → briefing.md     (LLM — external)
  7. validate    → gate pass/fail  (deterministic)
  8. render      → HTML + PDF      (deterministic)

Usage:
    # Full pipeline (agent handles search & edit)
    python3 pipeline.py --domain storage --date 2026-05-28 --raw-input raw.json

    # Deterministic-only stages (skip LLM steps)
    python3 pipeline.py --domain storage --date 2026-05-28 --raw-input raw.json --skip-agent
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import yaml
from datetime import datetime, timezone, timedelta

from stratum.stages.render.render import artifact_basename

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
    "render",
]


def resolve_paths(domain_id: str, run_date: str, output_dir: str) -> dict:
    """Resolve all file paths for a pipeline run."""

    domain_config = os.path.join(DOMAINS_DIR, domain_id, "domain.yaml")
    data_dir = os.path.join(output_dir, domain_id, "data", run_date)
    artifact_base = artifact_basename(domain_id, "daily", run_date)

    return {
        "domain_config": domain_config,
        "data_dir": data_dir,
        "raw": os.path.join(data_dir, "raw.json"),
        "search_stats": os.path.join(data_dir, "raw.stats.json"),
        "enriched": f"/tmp/strat_enriched_{domain_id}_{run_date}.json",
        "verified": os.path.join(data_dir, "verified.jsonl"),
        "verify_stats": os.path.join(data_dir, "verified.stats.json"),
        "articles": os.path.join(data_dir, "articles.jsonl"),
        "clusters": os.path.join(data_dir, "clusters.json"),
        "briefing_md": os.path.join(data_dir, f"{artifact_base}.md"),
        "briefing_html": os.path.join(data_dir, f"{artifact_base}.html"),
        "briefing_pdf": os.path.join(data_dir, f"{artifact_base}.pdf"),
        "run_manifest": os.path.join(data_dir, "run_manifest.json"),
        # Story-tracking closed loop
        "story_tracking_dir": os.path.join(output_dir, domain_id, "data", "story-tracking"),
        "thread_keywords": os.path.join(output_dir, domain_id, "data", "story-tracking",
                                        "thread_keywords.json"),
    }


def run_stage(stage_name: str, stage_args: list[str], step_label: str) -> bool:
    """Run a pipeline stage script, fail hard on error."""
    script = os.path.join(STAGES_DIR, stage_name, f"{stage_name}.py")
    cmd = [sys.executable, script] + stage_args

    # Ensure stratum modules are importable from subprocess
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = PROJECT_ROOT + ":" + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = PROJECT_ROOT

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  STEP: {step_label}", file=sys.stderr)
    print(f"  CMD:  {' '.join(cmd)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    sys.stderr.write(result.stderr)
    if result.stdout.strip():
        sys.stderr.write(result.stdout[:500])

    if result.returncode != 0:
        print(f"\n❌ {step_label} FAILED (exit {result.returncode})", file=sys.stderr)
        print(result.stderr[-500:], file=sys.stderr)
        return False

    print(f"✅ {step_label} complete", file=sys.stderr)
    return True


def should_run_stage(from_stage: str | None, stage_name: str) -> bool:
    """Return True if stage_name is at or after the requested resume point."""
    start = from_stage or "search"
    try:
        start_idx = PIPELINE_STAGE_ORDER.index(start)
        stage_idx = PIPELINE_STAGE_ORDER.index(stage_name)
    except ValueError as exc:
        valid = ", ".join(PIPELINE_STAGE_ORDER)
        raise ValueError(
            f"Unknown pipeline stage in resume gate: from_stage={from_stage!r}, "
            f"stage_name={stage_name!r}. Valid stages: {valid}"
        ) from exc
    return stage_idx >= start_idx


def record_stage_status(
    pipeline_status: list[dict],
    stage: str,
    status: str,
    output: str | None = None,
    detail: str | None = None,
) -> None:
    """Append a structured stage status record for the run manifest."""
    record = {
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(CST).isoformat(),
    }
    if output:
        record["output"] = output
    if detail:
        record["detail"] = detail
    pipeline_status.append(record)


def write_run_manifest(
    manifest_path: str,
    domain: str,
    run_date: str,
    status: str,
    stages: list[dict],
    paths: dict,
    summary: dict | None = None,
) -> dict:
    """Write the structured pipeline manifest and return its payload."""
    payload = {
        "status": status,
        "domain": domain,
        "date": run_date,
        "generated_at": datetime.now(CST).isoformat(),
        "stages": stages,
        "summary": summary or {},
        "paths": {k: v for k, v in paths.items()},
    }
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def db_ingest_modes(from_stage: str | None, skip_agent: bool = False) -> dict[str, bool]:
    """Return which DB ingest surfaces may have fresh data in this run."""
    return {
        "events": should_run_stage(from_stage, "edit") and not skip_agent,
        "entities": should_run_stage(from_stage, "normalize"),
    }


def expanded_source_locales(config: dict) -> list[str]:
    """Expand configured source_languages into concrete locale tags."""
    source_languages = config.get("source_languages", []) or ["en"]
    locale_expansions = config.get("locales", {}) or {}
    locales = []
    for lang in source_languages:
        expanded = locale_expansions.get(lang)
        if expanded:
            candidates = expanded
        else:
            candidates = [lang]
        for locale in candidates:
            if locale not in locales:
                locales.append(locale)
    return locales or ["en"]


def should_export_thread_keywords_after_ingest(ingest_modes: dict, db_status: dict) -> bool:
    """Return True when SQLite has fresh event data for next-run keywords."""
    return bool(ingest_modes.get("events")) and db_status.get("status") == "success"


def main():
    parser = argparse.ArgumentParser(description="Stratum deterministic briefing pipeline")
    parser.add_argument("--domain", "-d", required=True,
                        help="Domain ID (e.g., 'storage') — resolves to domains/<id>/domain.yaml")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--raw-input", help="Path to raw search results JSON (skip agent search)")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip agent-driven stages (search & edit)")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--from-stage", choices=["enrich", "verify", "normalize", "cluster", "edit", "validate", "render"],
                        help="Start from a specific stage (requires previous output files)")
    parser.add_argument("--web-extract", action="store_true",
                        help="Enable web page fetching to extract dates from HTML meta tags (slow)")
    args = parser.parse_args()

    # Validate domain
    domain_config_path = os.path.join(DOMAINS_DIR, args.domain, "domain.yaml")
    if not os.path.exists(domain_config_path):
        print(f"❌ Domain '{args.domain}' not found at {domain_config_path}", file=sys.stderr)
        print(f"   Available domains: {os.listdir(DOMAINS_DIR)}", file=sys.stderr)
        sys.exit(1)

    # Load config for output_dir and optional overrides
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    output_dir = args.output_dir or config.get("output_dir", "")
    if output_dir:
        output_dir = os.path.expandvars(os.path.expanduser(output_dir))
    else:
        print("❌ No output_dir set. Use --output-dir or configure config.yaml", file=sys.stderr)
        sys.exit(1)

    db_dir = config.get("db_dir", "")
    if db_dir:
        db_dir = os.path.expandvars(os.path.expanduser(db_dir))
    else:
        db_dir = os.path.join(output_dir, "DataBase")
    os.environ["STRATUM_DB_DIR"] = db_dir

    reports_dir = config.get("reports_dir", "")
    if reports_dir:
        reports_dir = os.path.expandvars(os.path.expanduser(reports_dir))
    else:
        reports_dir = output_dir

    health_data_dir = config.get("health_data_dir", "")
    if health_data_dir:
        health_data_dir = os.path.expandvars(os.path.expanduser(health_data_dir))
    else:
        health_data_dir = os.path.join(output_dir, "health-data")

    paths = resolve_paths(args.domain, args.date, reports_dir)
    os.makedirs(paths["data_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(paths["verified"]), exist_ok=True)
    os.makedirs(os.path.dirname(paths["clusters"]), exist_ok=True)
    _remove_legacy_briefing_artifacts(paths)

    pipeline_status = []

    def record(stage: str, status: str, output: str | None = None, detail: str | None = None):
        record_stage_status(pipeline_status, stage, status, output, detail)

    def fail(stage: str, output: str | None = None, detail: str | None = None):
        record(stage, "failed", output, detail)
        write_run_manifest(paths["run_manifest"], args.domain, args.date, "failed",
                           pipeline_status, paths, {"failed_stage": stage})
        sys.exit(1)

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
            db_path = os.path.join(db_dir, args.domain, f"{args.domain}.db")
            queries_path = os.path.join(DOMAINS_DIR, args.domain, "queries.yaml")
            if os.path.exists(db_path):
                if not run_stage("search", [
                    "--domain", args.domain,
                    "--date", args.date,
                    "--config", CONFIG_PATH,
                    "--db", db_path,
                    "--queries", queries_path,
                    "--output", paths["raw"],
                    "--stats", paths["search_stats"],
                ], "1/8 Search"):
                    fail("search", paths["raw"])
                record("search", "success", paths["raw"], "db")
                _try_ingest_search_stats(args.domain, paths["search_stats"], run_date=args.date)
            else:
                if not run_stage("search", [
                    "--domain", args.domain,
                    "--date", args.date,
                    "--config", CONFIG_PATH,
                    "--queries", queries_path,
                    "--output", paths["raw"],
                    "--stats", paths["search_stats"],
                ], "1/8 Search"):
                    fail("search", paths["raw"])
                record("search", "success", paths["raw"], "queries.yaml")
                _try_ingest_search_stats(args.domain, paths["search_stats"], run_date=args.date)

        # ── Stage 1.5: Collect (direct fetch from newsrooms) ──
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
        if not run_stage("verify", [
            "--input", paths["enriched"],
            "--output", paths["verified"],
            "--stats", paths["verify_stats"],
            "--date", args.date,
            "--domain", paths["domain_config"],
        ], "3/8 Verify articles"):
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
        if not run_stage("cluster", [
            "--input", paths["articles"],
            "--output", paths["clusters"],
            "--domain", paths["domain_config"],
            "--date", args.date,
        ], "5/8 Story clustering"):
            fail("cluster", paths["clusters"])
        record("cluster", "success", paths["clusters"])
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
        if not run_stage("edit", [
            "--domain", args.domain,
            "--date", args.date,
            "--articles", paths["articles"],
            "--clusters", paths["clusters"],
            "--context", story_ctx_path,
            "--config", CONFIG_PATH,
            "--output", paths["briefing_md"],
            "--timescale", "daily",
        ], "6/8 Agent Edit (LLM)"):
            print("⚠️  Agent Edit failed — continuing with validate/render anyway", file=sys.stderr)
            record("edit", "failed_nonblocking", paths["briefing_md"])
        else:
            record("edit", "success", paths["briefing_md"])

    # ── Stage 7: Validate ──
    if not should_run_stage(args.from_stage, "validate"):
        print(f"\n⏭️  Skipping validate due to --from-stage {args.from_stage}", file=sys.stderr)
        record("validate", "skipped", None, f"--from-stage {args.from_stage}")
    elif os.path.exists(paths["briefing_md"]) and os.path.exists(paths["articles"]):
        validate_args = [
            "--md", paths["briefing_md"],
            "--articles", paths["articles"],
            "--date", args.date,
            "--domain", paths["domain_config"],
        ]
        event_threads_path = os.path.join(paths["data_dir"], "event-threads.json")
        schemas_dir = os.path.join(STAGES_DIR, "edit", "prompts", "_schemas")
        if os.path.exists(event_threads_path) and os.path.exists(schemas_dir):
            validate_args += [
                "--event-threads", event_threads_path,
                "--schemas-dir", schemas_dir,
            ]
        if not run_stage("validate", validate_args, "7/8 Validate briefing"):
            print("⚠️  Validation failed — check violations above", file=sys.stderr)
            record("validate", "failed_nonblocking", None)
        else:
            record("validate", "success", None)
    else:
        print("\n⚠️  Skipping validate: briefing markdown or articles.jsonl not found", file=sys.stderr)
        record("validate", "skipped", None, "missing briefing markdown or articles.jsonl")

    # ── Stage 8: Render ──
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
        if run_stage("render", [
            "--input", paths["briefing_md"],
            "--output-dir", paths["data_dir"],
            "--title", channel_title,
            "--domain", paths["domain_config"],
            "--domain-id", args.domain,
            "--briefing-type", "daily",
            "--date", args.date,
            "--footer", "由 AI Agent 自动生成 · 每日 7:30 CST",
            "--template", os.path.join(DOMAINS_DIR, args.domain, "templates", "daily.html"),
        ], "8/8 Render HTML + PDF"):
            record("render", "success", paths["briefing_html"])
        else:
            record("render", "failed_nonblocking", paths["briefing_html"])
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

    summary = {"articles": article_count, "clusters": cluster_count}
    write_run_manifest(paths["run_manifest"], args.domain, args.date, "ok",
                       pipeline_status, paths, summary)

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
        "paths": {k: v for k, v in paths.items()},
    }))


# ── Story-Tracking Integration Helpers ──

def _try_ingest_search_stats(domain_id: str, stats_path: str, run_date: str) -> int:
    """Ingest Search query stats sidecar into SQLite query counters."""
    if not os.path.exists(stats_path):
        return 0
    try:
        from stratum.db.ingest import update_query_stats

        with open(stats_path) as f:
            data = json.load(f)
        queries = data.get("queries", []) if isinstance(data, dict) else []
        count = update_query_stats(domain_id, queries, run_date=run_date)
        print(f"💾 DB: {count} search query stats updated", file=sys.stderr)
        return count
    except Exception as e:
        print(f"⚠️  Search query stats ingest skipped: {e}", file=sys.stderr)
        return 0


def _remove_legacy_briefing_artifacts(paths: dict) -> None:
    """Remove stale briefing.* artifacts now that canonical names are used."""
    data_dir = paths.get("data_dir", "")
    if not data_dir:
        return
    canonical_paths = {
        os.path.abspath(paths.get("briefing_md", "")),
        os.path.abspath(paths.get("briefing_html", "")),
        os.path.abspath(paths.get("briefing_pdf", "")),
    }
    for legacy_name in ("briefing.md", "briefing.html", "briefing.pdf"):
        legacy_path = os.path.abspath(os.path.join(data_dir, legacy_name))
        if legacy_path in canonical_paths or not os.path.exists(legacy_path):
            continue
        try:
            os.remove(legacy_path)
        except OSError as exc:
            print(f"⚠️  Could not remove legacy artifact {legacy_path}: {exc}", file=sys.stderr)


def _coverage_entities_from_domain_config(domain_config_path: str) -> list[str]:
    """Load domain entities that should be considered for coverage gaps."""
    try:
        with open(domain_config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []

    entities: list[str] = []
    seen: set[str] = set()
    for company in cfg.get("companies", []) or []:
        entity_id = str(company.get("id") or "").strip()
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            entities.append(entity_id)
    return entities


def _try_generate_story_context(domain_id: str, run_date: str, paths: dict, output_path: str):
    """Generate BriefingContext for the agent, from SQLite story-tracking data."""
    try:
        import sys as _sys
        _sys.path.insert(0, PROJECT_ROOT)
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "stratum", "subsystems", "story-tracking"))
        from briefing_context import generate_context
        from types import SimpleNamespace
        from stratum.db.connection import get_db

        coverage_entities = _coverage_entities_from_domain_config(paths.get("domain_config", ""))
        conn = get_db(domain_id)

        # Check if events exist
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count == 0 and not coverage_entities:
            conn.close()
            return

        # ── Load events ──
        rows = conn.execute(
            "SELECT id, thread_id, title, date, entity_ids, scale, briefing_id, status, priority FROM events"
        ).fetchall()
        events = []
        for r in rows:
            entity_ids = json.loads(r["entity_ids"]) if r["entity_ids"] else []
            events.append(SimpleNamespace(
                id=r["id"],
                thread_id=r["thread_id"] or "",
                title=r["title"] or "",
                status=r["status"] or "emerging",
                priority=r["priority"] or 3,
                entity_tags=entity_ids,
                last_updated=r["date"] or run_date,
                scale_refs=[{"scale": r["scale"], "date": r["date"], "briefing_id": r["briefing_id"]}] if r["scale"] else [],
                open_questions=[],
            ))

        # ── Load causal edges (thread-level → event-level via events table) ──
        edge_rows = conn.execute(
            "SELECT ce.id, ce.cause_thread_id, ce.effect_thread_id, ce.mechanism, ce.confidence,"
            " ce.verified, ce.created_at FROM causal_edges ce"
        ).fetchall()
        # Build thread_id → event_id map (latest event per thread)
        thread_event = {}
        for e in events:
            tid = e.thread_id or e.id
            if tid not in thread_event or e.last_updated > thread_event[tid][1]:
                thread_event[tid] = (e.id, e.last_updated)
        edges = []
        for r in edge_rows:
            cause_id = thread_event.get(r["cause_thread_id"], (r["cause_thread_id"],))[0]
            effect_id = thread_event.get(r["effect_thread_id"], (r["effect_thread_id"],))[0]
            edges.append(SimpleNamespace(
                id=r["id"], cause_id=cause_id, effect_id=effect_id,
                mechanism=r["mechanism"] or "",
                confidence=r["confidence"] or "B",
                created=r["created_at"] or run_date,
                verified=bool(r["verified"]),
            ))

        # ── Load judgments ──
        j_rows = conn.execute(
            "SELECT id, target_type, target_entity_ids, target_thread_ids, hypothesis, confidence,"
            " expected_verification, result, created_at FROM judgments"
        ).fetchall()
        judgments = []
        for r in j_rows:
            target_ids = json.loads(r["target_entity_ids"]) if r["target_entity_ids"] else []
            if not target_ids and r["target_thread_ids"]:
                target_ids = json.loads(r["target_thread_ids"])
            verdict_map = {None: "pending", "pending": "pending", "correct": "correct",
                          "incorrect": "incorrect", "partially_correct": "deferred"}
            judgments.append(SimpleNamespace(
                id=r["id"], target_type=r["target_type"] or "entity",
                target_ids=target_ids,
                hypothesis=r["hypothesis"] or "",
                confidence=r["confidence"] or "B",
                expected_verification=r["expected_verification"] or run_date,
                verdict=verdict_map.get(r["result"], "pending"),
                made_at=r["created_at"] or run_date,
            ))

        conn.close()

        ctx = generate_context(
            domain_id,
            "daily",
            run_date,
            events,
            edges,
            judgments,
            coverage_entities=coverage_entities,
        )
        with open(output_path, "w") as f:
            json.dump({
                "scale": ctx.scale,
                "date": ctx.date,
                "domain_id": ctx.domain_id,
                "carried_forward": ctx.carried_forward,
                "due_judgments": ctx.due_judgments,
                "coverage_gaps": ctx.coverage_gaps,
                "active_causal_chains": ctx.active_causal_chains,
                "unassigned_events": ctx.unassigned_events,
            }, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n📋 Story context written: {output_path} "
              f"({len(ctx.carried_forward)} carried, {len(ctx.due_judgments)} due, "
              f"{len(ctx.coverage_gaps)} gaps)", file=sys.stderr)
    except Exception as e:
        print(f"⚠️  Story context generation skipped: {e}", file=sys.stderr)


def _export_thread_keywords(domain_id: str, paths: dict):
    """Export thread_keywords.json from SQLite events table.

    Reads all active/pending events and extracts title keywords + entities
    for the next day's normalize stage to match articles to event threads.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, PROJECT_ROOT)
        from stratum.db.connection import get_db

        conn = get_db(domain_id)
        rows = conn.execute(
            "SELECT id, thread_id, title, entity_ids, status FROM events"
            " WHERE status IN ('active', 'pending', 'cooling', 'emerging')"
        ).fetchall()
        conn.close()

        if not rows:
            return

        threads_by_id = {}
        for r in rows:
            title = r["title"] or ""
            thread_id = r["thread_id"] or r["id"]
            if thread_id not in threads_by_id:
                threads_by_id[thread_id] = {
                    "thread_id": thread_id,
                    "label": title or r["id"],
                    "status": r["status"] or "active",
                    "keywords": set(),
                    "description": "",
                }
            thread = threads_by_id[thread_id]
            if title and (not thread["label"] or thread["label"] == thread_id):
                thread["label"] = title
            thread["status"] = _merge_thread_export_status(thread["status"], r["status"] or "active")
            thread["keywords"].update(_keywords_from_thread_event(title, r["entity_ids"]))

        threads = []
        for thread in threads_by_id.values():
            threads.append({
                **thread,
                "keywords": sorted(thread["keywords"])[:20],
            })

        if not threads:
            return

        output_path = paths["thread_keywords"]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({"threads": threads, "exported_at": datetime.now(CST).isoformat()},
                       f, ensure_ascii=False, indent=2)

        print(f"\n🔗 Thread keywords exported: {len(threads)} threads → {output_path}",
              file=sys.stderr)
        for t in threads:
            print(f"   [{t['status']}] {t['label'][:60]} ({len(t['keywords'])} keywords)",
                  file=sys.stderr)
    except Exception as e:
        print(f"⚠️  Thread keywords export skipped: {e}", file=sys.stderr)


def _keywords_from_thread_event(title: str, entity_ids_json: str | None) -> set[str]:
    """Extract stable matching keywords from one persisted event row."""
    keywords = set()
    if title:
        tokens = re.findall(r'[A-Za-z0-9]+|[\u4e00-\u9fff]+', title)
        for t in tokens:
            t = t.lower().strip()
            if len(t) >= 2:
                keywords.add(t)
            if re.search(r'[\u4e00-\u9fff]', t) and len(t) >= 8:
                cjk = re.findall(r'[\u4e00-\u9fff]', t)
                for i in range(len(cjk) - 1):
                    keywords.add(''.join(cjk[i:i+2]))

    try:
        entity_ids = json.loads(entity_ids_json) if entity_ids_json else []
    except (TypeError, json.JSONDecodeError):
        entity_ids = []
    keywords.update(e.lower() for e in entity_ids if e)
    return keywords


def _merge_thread_export_status(current: str, incoming: str) -> str:
    """Keep the most actionable lifecycle status for normalize feedback."""
    rank = {
        "active": 0,
        "emerging": 1,
        "pending": 2,
        "cooling": 3,
    }
    current_rank = rank.get(current or "", 99)
    incoming_rank = rank.get(incoming or "", 99)
    return incoming if incoming_rank < current_rank else current


def _try_db_ingest(
    domain_id: str,
    run_date: str,
    paths: dict,
    db_dir: str,
    ingest_events: bool = True,
    ingest_entities: bool = True,
    watch_locales: list[str] | None = None,
) -> dict:
    """Ingest pipeline outputs into SQLite database."""
    db_path = os.path.join(db_dir, domain_id, f"{domain_id}.db")
    if not os.path.exists(db_path):
        return {"status": "skipped", "output": db_path, "detail": "database not found"}

    try:
        os.environ["STRATUM_DB_DIR"] = db_dir
        import sys as _sys
        _sys.path.insert(0, os.path.join(PROJECT_ROOT))
        from stratum.db.ingest import (
            ingest_daily_events,
            ingest_entity_snapshots,
            update_entities_after_run,
            upsert_watch_queries,
        )

        # 1. Ingest events/threads/causal/judgments from event-threads.json
        event_stats = None
        if ingest_events:
            event_threads_path = os.path.join(paths["data_dir"], "event-threads.json")
            if not os.path.exists(event_threads_path):
                alt_path = os.path.join(paths["data_dir"], "..", "event-threads", "event-threads.json")
                if os.path.exists(alt_path):
                    event_threads_path = alt_path

            if os.path.exists(event_threads_path):
                event_stats = ingest_daily_events(event_threads_path, domain_id, run_date)
                if event_stats["errors"]:
                    print(f"\n⚠️  DB ingestion errors: {event_stats['errors']}", file=sys.stderr)
                if any(event_stats[k] for k in ['events', 'causal_edges', 'judgments', 'new_threads']):
                    print(f"\n💾 DB: {event_stats['events']} events, {event_stats['causal_edges']} edges, " +
                          f"{event_stats['judgments']} judgments, {event_stats['new_threads']} new threads", file=sys.stderr)
                watch_query_count = _persist_event_watch_queries(
                    domain_id,
                    event_threads_path,
                    watch_locales or ["en"],
                    upsert_watch_queries,
                    run_date,
                )
                event_stats["watch_queries"] = watch_query_count
                if watch_query_count:
                    print(f"💾 DB: {watch_query_count} watch queries upserted", file=sys.stderr)

        # 2. Update entity article counts
        entity_counts = {}
        entity_updates = 0
        snapshots = 0
        if ingest_entities:
            articles_path = paths.get("articles", "")
            if os.path.exists(articles_path):
                with open(articles_path) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        import json as _json
                        a = _json.loads(line)
                        for eid in a.get("entity_ids", a.get("entities", [])):
                            entity_counts[eid] = entity_counts.get(eid, 0) + 1
                if entity_counts:
                    stats_list = [{"id": eid, "article_count_today": c} for eid, c in entity_counts.items()]
                    entity_updates = update_entities_after_run(
                        domain_id, stats_list, run_date=run_date, scale="daily"
                    )
                    print(f"💾 DB: {entity_updates} entities updated", file=sys.stderr)

            # 3. Entity snapshots
            snapshots = ingest_entity_snapshots(domain_id, "daily", run_date, entity_counts)
            print(f"💾 DB: {snapshots} entity snapshots", file=sys.stderr)

        details = [
            f"events={'on' if ingest_events else 'off'}",
            f"entities={'on' if ingest_entities else 'off'}",
            f"entity_updates={entity_updates}",
            f"snapshots={snapshots}",
        ]
        if event_stats:
            details.append(f"events_written={event_stats.get('events', 0)}")
            if "watch_queries" in event_stats:
                details.append(f"watch_queries={event_stats.get('watch_queries', 0)}")
            if event_stats.get("errors"):
                details.append(f"errors={len(event_stats.get('errors', []))}")
        status = "failed_nonblocking" if event_stats and event_stats.get("errors") else "success"
        return {"status": status, "output": db_path, "detail": "; ".join(details)}

    except Exception as e:
        print(f"⚠️  DB ingestion skipped: {e}", file=sys.stderr)
        return {"status": "failed_nonblocking", "output": db_path, "detail": str(e)}


def _persist_event_watch_queries(
    domain_id: str,
    event_threads_path: str,
    watch_locales: list[str],
    upsert_fn,
    run_date: str,
) -> int:
    """Generate and persist DB Search queries from event-thread watch signals."""
    try:
        with open(event_threads_path) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0

    threads_payload = payload.get("threads") or []
    if not threads_payload:
        return 0

    import sys as _sys
    event_thread_dir = os.path.join(PROJECT_ROOT, "stratum", "subsystems", "event-thread")
    if event_thread_dir not in _sys.path:
        _sys.path.insert(0, event_thread_dir)
    from event_thread import EventThread, generate_watch_queries

    threads = {}
    for item in threads_payload:
        thread_id = item.get("thread_id") or item.get("id")
        watch_signals = item.get("watch_signals") or []
        if not thread_id:
            continue
        threads[thread_id] = EventThread(
            id=thread_id,
            title=item.get("title") or item.get("label") or thread_id,
            canonical_question=item.get("canonical_question") or item.get("description") or "",
            status=item.get("status") or "active",
            priority=_normalize_thread_priority(item.get("priority", "medium")),
            created=item.get("created") or run_date,
            last_updated=item.get("last_updated") or run_date,
            watch_signals=watch_signals,
            open_questions=item.get("open_questions") or [],
            close_conditions=item.get("close_conditions") or [],
        )

    if not threads:
        return 0

    watch_queries = generate_watch_queries(threads, locales=watch_locales)
    return upsert_fn(domain_id, watch_queries, run_date=run_date)


def _normalize_thread_priority(priority) -> str:
    """Normalize DB/LLM priority shapes to event-thread priority labels."""
    if isinstance(priority, str):
        value = priority.lower().strip()
        if value in {"high", "medium", "low"}:
            return value
        if value.isdigit():
            priority = int(value)
    if isinstance(priority, (int, float)):
        if priority <= 1:
            return "high"
        if priority == 2:
            return "medium"
    return "low" if priority == 3 else "medium"


def _run_collector(
    domain: str,
    workspace: str,
    run_date: str,
    raw_path: str,
    health_data_dir: str | None = None,
):
    """Run all collectors (direct_fetch, rss) and merge results into raw.json."""
    try:
        from stratum.collectors import collect_with_stats
        collector_run = collect_with_stats(domain, workspace, run_date)
        collector_results = collector_run.results

        stats_path = os.path.join(os.path.dirname(raw_path), "collector_stats.json")

        if not collector_results:
            _set_collector_selected_counts(collector_run.source_stats, {})
            with open(stats_path, "w") as f:
                json.dump(collector_run.stats_json(domain, run_date), f, ensure_ascii=False, indent=2)
            _write_collector_health(domain, run_date, collector_run.source_stats, health_data_dir)
            return {"status": "empty", "output": stats_path, "detail": "no collector results"}

        # Read existing raw.json (search results)
        search_results = []
        if os.path.exists(raw_path):
            with open(raw_path) as f:
                data = json.load(f)
                search_results = data if isinstance(data, list) else data.get("results", [])

        from stratum.subsystems.search.models import canonicalize_url

        # Merge: collector first, search results appended (collector wins on URL conflict)
        seen_urls = set()
        merged = []
        selected_by_source = {}
        for r in collector_results:
            d = r.to_dict() if hasattr(r, 'to_dict') else r
            url = d.get("url", "")
            canonical = d.get("canonical_url") or canonicalize_url(url)
            if url and canonical not in seen_urls:
                d["canonical_url"] = canonical
                seen_urls.add(canonical)
                merged.append(d)
                source_id = _collector_source_id(d)
                if source_id:
                    selected_by_source[source_id] = selected_by_source.get(source_id, 0) + 1

        for r in search_results:
            url = r.get("url", "")
            canonical = r.get("canonical_url") or canonicalize_url(url)
            if url and canonical not in seen_urls:
                r["canonical_url"] = canonical
                seen_urls.add(canonical)
                merged.append(r)

        with open(raw_path, "w") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        _set_collector_selected_counts(collector_run.source_stats, selected_by_source)
        with open(stats_path, "w") as f:
            json.dump(collector_run.stats_json(domain, run_date), f, ensure_ascii=False, indent=2)
        _write_collector_health(domain, run_date, collector_run.source_stats, health_data_dir)
        _update_post_collect_search_stats(raw_path, merged)

        added = len(collector_results)
        total = len(merged)
        print(f"\n📡 Collector: +{added} direct-fetch → {total} total in raw.json",
              file=sys.stderr)
        return {"status": "success", "output": stats_path, "detail": f"{added} collected; {total} total"}

    except Exception as e:
        print(f"⚠️  Collector skipped: {e}", file=sys.stderr)
        return {"status": "failed_nonblocking", "output": raw_path, "detail": str(e)}


def _update_post_collect_search_stats(raw_path: str, merged_results: list[dict]) -> None:
    """Annotate raw.stats.json with final raw.json coverage after collectors merge."""
    stats_path = os.path.join(os.path.dirname(raw_path), "raw.stats.json")
    if not os.path.exists(stats_path):
        return
    try:
        with open(stats_path) as f:
            stats = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    by_type: dict[str, int] = {}
    by_locale: dict[str, int] = {}
    for result in merged_results:
        source_type = str(result.get("source_type_hint") or "unknown")
        locale = str(result.get("locale") or "unknown")
        by_type[source_type] = by_type.get(source_type, 0) + 1
        by_locale[locale] = by_locale.get(locale, 0) + 1

    minimums = {}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            minimums = cfg.get("curation", {}).get("min_per_source_type", {}) or {}
    except Exception:
        minimums = {}

    final_gaps = []
    for source_type, minimum in sorted(minimums.items()):
        available = by_type.get(source_type, 0)
        if available < int(minimum):
            final_gaps.append({
                "source_type": source_type,
                "minimum": int(minimum),
                "raw_available": available,
                "shortfall": int(minimum) - available,
            })

    diagnostics = stats.setdefault("diagnostics", {})
    diagnostics["post_collect_total_raw"] = len(merged_results)
    diagnostics["post_collect_by_source_type"] = by_type
    diagnostics["post_collect_by_locale"] = by_locale
    diagnostics["post_collect_source_type_gaps"] = final_gaps

    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def _set_collector_selected_counts(source_stats: list, selected_by_source: dict[str, int]) -> None:
    """Attach post-merge selected counts to mutable collector stats."""
    for stat in source_stats:
        if hasattr(stat, "source"):
            stat.selected = int(selected_by_source.get(stat.source, 0) or 0)
        else:
            stat["selected"] = int(selected_by_source.get(stat.get("source", ""), 0) or 0)


def _collector_source_id(result: dict) -> str:
    """Return the collector source id from a raw SearchResult dict."""
    engine = str(result.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]

    query_id = str(result.get("query_id") or "")
    for prefix in ("df-", "rss-", "b-"):
        if query_id.startswith(prefix):
            query_id = query_id[len(prefix):]
            break
    if query_id.endswith("-fallback"):
        query_id = query_id[:-len("-fallback")]
    if query_id.endswith("-list"):
        query_id = query_id[:-len("-list")]
    return query_id


def _write_collector_health(
    domain: str,
    run_date: str,
    source_stats: list,
    health_data_dir: str | None,
) -> None:
    """Append collector source health records to monitoring NDJSON."""
    if not health_data_dir or not source_stats:
        return
    try:
        from stratum.subsystems.monitoring.health import ensure_channel_dir, write_daily_record

        channel_dir = ensure_channel_dir(health_data_dir, domain)
        for stat in source_stats:
            data = stat.to_dict() if hasattr(stat, "to_dict") else dict(stat)
            status = data.get("status", "")
            http_code = 200 if status in {"ok", "empty"} else 500
            scanned = status != "unsupported"
            tags = ["collector", data.get("access", "unknown"), status]
            write_daily_record(
                channel_dir=channel_dir,
                run_date=run_date,
                source=data.get("source", "unknown"),
                hits=int(data.get("hits", 0) or 0),
                selected=int(data.get("selected", 0) or 0),
                scanned=scanned,
                http_code=http_code,
                tags=tags,
                duration_ms=data.get("duration_ms"),
                error=data.get("error") or None,
                metadata={
                    "locale": data.get("locale", ""),
                    "category": data.get("category", ""),
                    "dated": data.get("dated", 0),
                    "status": status,
                },
            )
    except Exception as e:
        print(f"⚠️  Collector health write skipped: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
