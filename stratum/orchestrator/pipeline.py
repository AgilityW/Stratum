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
import argparse
import json
import os
import subprocess
import sys
import yaml
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGES_DIR = os.path.join(PROJECT_ROOT, "stratum", "stages")
DOMAINS_DIR = os.path.join(PROJECT_ROOT, "domains")


def resolve_paths(domain_id: str, run_date: str, output_dir: str = None) -> dict:
    """Resolve all file paths for a pipeline run."""
    if output_dir is None:
        output_dir = os.path.expanduser("~/WorkSpace/Stratum")

    domain_config = os.path.join(DOMAINS_DIR, domain_id, "domain.yaml")
    prompts_dir = os.path.join(DOMAINS_DIR, domain_id, "prompts")
    data_dir = os.path.join(output_dir, domain_id, "data", run_date)

    return {
        "domain_config": domain_config,
        "prompts_dir": prompts_dir,
        "data_dir": data_dir,
        "raw": os.path.join(data_dir, "raw.json"),
        "enriched": f"/tmp/strat_enriched_{domain_id}_{run_date}.json",
        "verified": os.path.join(data_dir, "verified.jsonl"),
        "articles": os.path.join(data_dir, "articles.jsonl"),
        "clusters": os.path.join(data_dir, "clusters.json"),
        "briefing_md": os.path.join(data_dir, "briefing.md"),
        "briefing_html": os.path.join(data_dir, "briefing.html"),
        "briefing_pdf": os.path.join(data_dir, "briefing.pdf"),
    }


def run_stage(stage_name: str, stage_args: list[str], step_label: str) -> bool:
    """Run a pipeline stage script, fail hard on error."""
    script = os.path.join(STAGES_DIR, stage_name, f"{stage_name}.py")
    cmd = [sys.executable, script] + stage_args

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  STEP: {step_label}", file=sys.stderr)
    print(f"  CMD:  {' '.join(cmd)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    sys.stderr.write(result.stderr)
    if result.stdout.strip():
        sys.stderr.write(result.stdout[:500])

    if result.returncode != 0:
        print(f"\n❌ {step_label} FAILED (exit {result.returncode})", file=sys.stderr)
        print(result.stderr[-500:], file=sys.stderr)
        return False

    print(f"✅ {step_label} complete", file=sys.stderr)
    return True


def print_agent_placeholder(stage_name: str, step_label: str,
                             input_hint: str, output_path: str) -> dict:
    """Print instructions for agent-driven stages (search, edit).
    Returns status dict for pipeline output.
    """
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  STEP: {step_label} (AGENT-DRIVEN)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Input hint: {input_hint}", file=sys.stderr)
    print(f"  Output:     {output_path}", file=sys.stderr)
    print(f"  ⚠️  This stage requires LLM agent execution.", file=sys.stderr)

    if stage_name == "search":
        print(f"  Action: Call web_search with domain queries, save to {output_path}", file=sys.stderr)
    elif stage_name == "edit":
        print(f"  Action: Generate briefing MD from articles + clusters, save to {output_path}", file=sys.stderr)

    return {"stage": stage_name, "status": "pending_agent", "output": output_path}


def main():
    parser = argparse.ArgumentParser(description="Stratum deterministic briefing pipeline")
    parser.add_argument("--domain", "-d", required=True,
                        help="Domain ID (e.g., 'storage') — resolves to domains/<id>/domain.yaml")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--raw-input", help="Path to raw search results JSON (skip agent search)")
    parser.add_argument("--skip-agent", action="store_true",
                        help="Skip agent-driven stages (search & edit)")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--from-stage", choices=["enrich", "verify", "normalize", "cluster", "validate", "render"],
                        help="Start from a specific stage (requires previous output files)")
    args = parser.parse_args()

    # Validate domain
    domain_config_path = os.path.join(DOMAINS_DIR, args.domain, "domain.yaml")
    if not os.path.exists(domain_config_path):
        print(f"❌ Domain '{args.domain}' not found at {domain_config_path}", file=sys.stderr)
        print(f"   Available domains: {os.listdir(DOMAINS_DIR)}", file=sys.stderr)
        sys.exit(1)

    paths = resolve_paths(args.domain, args.date, args.output_dir)
    os.makedirs(paths["data_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(paths["verified"]), exist_ok=True)
    os.makedirs(os.path.dirname(paths["clusters"]), exist_ok=True)

    pipeline_status = []

    # ── Stage 1: Agent Search (LLM) ──
    if args.raw_input:
        # Use provided raw input
        if args.raw_input != paths["raw"]:
            import shutil
            shutil.copy(args.raw_input, paths["raw"])
        pipeline_status.append({"stage": "search", "status": "provided", "output": paths["raw"]})
        print(f"\n📥 Using provided raw input: {paths['raw']}", file=sys.stderr)
    elif args.skip_agent:
        if not os.path.exists(paths["raw"]):
            print(f"❌ --skip-agent but no raw input at {paths['raw']}", file=sys.stderr)
            sys.exit(1)
        pipeline_status.append({"stage": "search", "status": "skipped", "output": paths["raw"]})
    else:
        status = print_agent_placeholder(
            "search", "1/8 Agent Search",
            f"domain={args.domain}, date={args.date}",
            paths["raw"]
        )
        pipeline_status.append(status)
        print(f"\n⏸️  Pipeline paused. Run agent search to produce {paths['raw']}, then re-run with --raw-input", file=sys.stderr)
        print(json.dumps({"status": "agent_search_needed", "raw_output_path": paths["raw"]}))
        sys.exit(0)

    # ── Stage 2: Enrich ──
    if not run_stage("enrich", [
        "--input", paths["raw"],
        "--output", paths["enriched"],
        "--date", args.date,
    ], "2/8 Enrich dates"):
        sys.exit(1)

    # ── Stage 3: Verify ──
    if not run_stage("verify", [
        "--input", paths["enriched"],
        "--output", paths["verified"],
        "--date", args.date,
        "--domain", paths["domain_config"],
    ], "3/8 Verify articles"):
        sys.exit(1)

    # ── Stage 4: Normalize ──
    if not run_stage("normalize", [
        "--input", paths["verified"],
        "--output", paths["articles"],
        "--domain", paths["domain_config"],
    ], "4/8 Normalize articles"):
        sys.exit(1)

    # ── Stage 5: Cluster ──
    if not run_stage("cluster", [
        "--input", paths["articles"],
        "--output", paths["clusters"],
        "--domain", paths["domain_config"],
        "--date", args.date,
    ], "5/8 Story clustering"):
        sys.exit(1)

    # ── Stage 6: Agent Edit (LLM) ──
    # Generate story context before the agent runs
    story_ctx_path = os.path.join(paths["data_dir"], "story_context.json")
    _try_generate_story_context(args.domain, args.date, paths, story_ctx_path)

    if args.skip_agent:
        if not os.path.exists(paths["briefing_md"]):
            print(f"⚠️  --skip-agent but no briefing.md at {paths['briefing_md']}", file=sys.stderr)
        pipeline_status.append({"stage": "edit", "status": "skipped", "output": paths["briefing_md"]})
    else:
        status = print_agent_placeholder(
            "edit", "6/8 Agent Edit",
            f"articles={paths['articles']}, clusters={paths['clusters']}",
            paths["briefing_md"]
        )
        pipeline_status.append(status)

    # ── Stage 7: Validate ──
    if os.path.exists(paths["briefing_md"]) and os.path.exists(paths["articles"]):
        if not run_stage("validate", [
            "--md", paths["briefing_md"],
            "--articles", paths["articles"],
            "--date", args.date,
            "--domain", paths["domain_config"],
        ], "7/8 Validate briefing"):
            print("⚠️  Validation failed — check violations above", file=sys.stderr)
    else:
        print("\n⚠️  Skipping validate: briefing.md or articles.jsonl not found", file=sys.stderr)

    # ── Stage 8: Render ──
    if os.path.exists(paths["briefing_md"]):
        run_stage("render", [
            "--input", paths["briefing_md"],
            "--output-dir", paths["data_dir"],
            "--domain", paths["domain_config"],
            "--footer", "由 AI Agent 自动生成 · 每日 7:30 CST",
            "--template", os.path.join(DOMAINS_DIR, args.domain, "templates", "daily.html"),
        ], "8/8 Render HTML + PDF")
    else:
        print("\n⚠️  Skipping render: briefing.md not found", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # ── Story Bridge: ingest event-threads into Story-Tracking EventStore ──
    _try_ingest_event_threads(args.domain, args.date, paths)

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

def _try_generate_story_context(domain_id: str, run_date: str, paths: dict, output_path: str):
    """Generate BriefingContext for the agent, if story-tracking storage exists."""
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "stratum", "subsystems", "story-tracking"))
        from briefing_context import generate_context
        from repository import JsonlEventRepository, JsonlCausalRepository, JsonlJudgmentRepository
        from taxonomy import Taxonomy

        output_dir = os.path.expanduser("~/WorkSpace/Stratum")
        data_dir = os.path.join(output_dir, domain_id, "data", "story-tracking")
        if not os.path.isdir(data_dir):
            return  # No story-tracking data yet, skip

        events = JsonlEventRepository(data_dir, domain_id).all()
        if not events:
            return  # Empty store, nothing to carry forward

        edges = JsonlCausalRepository(data_dir).all()
        judgments = JsonlJudgmentRepository(data_dir).all()
        taxonomy_path = os.path.join(DOMAINS_DIR, domain_id, "taxonomy.yaml")
        taxonomy = Taxonomy(taxonomy_path)

        ctx = generate_context(domain_id, "daily", run_date, events, edges, judgments)
        import json as _json
        with open(output_path, "w") as f:
            _json.dump({
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


def _try_ingest_event_threads(domain_id: str, run_date: str, paths: dict):
    """Ingest Agent-produced event-threads.json into the Story-Tracking EventStore."""
    event_threads_path = os.path.join(paths["data_dir"], "..", "event-threads", "event-threads.json")
    # Also check the alternate path
    alt_path = os.path.join(paths["data_dir"], "event-threads.json")
    if os.path.exists(alt_path):
        event_threads_path = alt_path

    if not os.path.exists(event_threads_path):
        return  # No event-threads produced yet

    try:
        import json as _json
        with open(event_threads_path) as f:
            data = _json.load(f)
        threads = data.get("threads", [])

        if not threads:
            return

        import sys as _sys
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "stratum", "subsystems", "story-tracking"))
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "stratum", "orchestrator"))
        from story_bridge import ingest_batch
        from repository import JsonlEventRepository, StateManager
        from taxonomy import Taxonomy

        output_dir = os.path.expanduser("~/WorkSpace/Stratum")
        data_dir = os.path.join(output_dir, domain_id, "data", "story-tracking")
        repo = JsonlEventRepository(data_dir, domain_id)
        state = StateManager(data_dir)
        taxonomy_path = os.path.join(DOMAINS_DIR, domain_id, "taxonomy.yaml")
        taxonomy = Taxonomy(taxonomy_path)

        briefing_id = f"daily-{run_date}"
        stats = ingest_batch(threads, domain_id, run_date, repo, state, taxonomy,
                            briefing_id=briefing_id)

        print(f"\n📊 Story Bridge: {stats['ingested']} ingested, {stats['rejected']} rejected "
              f"→ {data_dir}/events.jsonl ({repo.count()} total)", file=sys.stderr)
        if stats["errors"]:
            for err in stats["errors"]:
                print(f"  ⚠️  {err}", file=sys.stderr)
    except Exception as e:
        print(f"⚠️  Story Bridge ingestion skipped: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
