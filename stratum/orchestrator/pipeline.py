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
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def resolve_paths(domain_id: str, run_date: str, output_dir: str) -> dict:
    """Resolve all file paths for a pipeline run."""

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

    reports_dir = config.get("reports_dir", "")
    if reports_dir:
        reports_dir = os.path.expandvars(os.path.expanduser(reports_dir))
    else:
        reports_dir = output_dir

    paths = resolve_paths(args.domain, args.date, reports_dir)
    os.makedirs(paths["data_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(paths["verified"]), exist_ok=True)
    os.makedirs(os.path.dirname(paths["clusters"]), exist_ok=True)

    pipeline_status = []

    # ── Stage 1: Search (deterministic — calls engine APIs directly) ──
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
        db_path = os.path.join(db_dir, args.domain, f"{args.domain}.db")
        if os.path.exists(db_path):
            if not run_stage("search", [
                "--domain", args.domain,
                "--date", args.date,
                "--config", CONFIG_PATH,
                "--db", db_path,
                "--output", paths["raw"],
            ], "1/8 Search"):
                sys.exit(1)
        else:
            queries_path = os.path.join(DOMAINS_DIR, args.domain, "queries.yaml")
            if not run_stage("search", [
                "--domain", args.domain,
                "--date", args.date,
                "--config", CONFIG_PATH,
                "--queries", queries_path,
                "--output", paths["raw"],
            ], "1/8 Search"):
                sys.exit(1)

    # ── Stage 1.5: Collect (direct fetch from newsrooms) ──
    _run_collector(args.domain, PROJECT_ROOT, args.date, paths["raw"])

    # ── Stage 2: Enrich ──
    enrich_cmd = [
        "--input", paths["raw"],
        "--output", paths["enriched"],
        "--date", args.date,
    ]
    if getattr(args, "web_extract", False):
        enrich_cmd.append("--web-extract")
    if not run_stage("enrich", enrich_cmd, "2/8 Enrich dates"):
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
    normalize_args = [
        "--input", paths["verified"],
        "--output", paths["articles"],
        "--domain", paths["domain_config"],
    ]
    # Closed-loop: feed previous day's thread_keywords to normalize
    if os.path.exists(paths["thread_keywords"]):
        normalize_args += ["--thread-keywords", paths["thread_keywords"]]
    if not run_stage("normalize", normalize_args, "4/8 Normalize articles"):
        sys.exit(1)

    # ── Stage 5: Cluster ──
    if not run_stage("cluster", [
        "--input", paths["articles"],
        "--output", paths["clusters"],
        "--domain", paths["domain_config"],
        "--date", args.date,
    ], "5/8 Story clustering"):
        sys.exit(1)

    # ── Closed-loop: export thread_keywords for next day's normalize ──
    _export_thread_keywords(args.domain, paths)

    # ── Stage 6: Agent Edit (LLM) ──
    # Generate story context before the agent runs
    story_ctx_path = os.path.join(paths["data_dir"], "story_context.json")
    _try_generate_story_context(args.domain, args.date, paths, story_ctx_path)

    if args.skip_agent:
        if not os.path.exists(paths["briefing_md"]):
            print(f"⚠️  --skip-agent but no briefing.md at {paths['briefing_md']}", file=sys.stderr)
        pipeline_status.append({"stage": "edit", "status": "skipped", "output": paths["briefing_md"]})
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

    # ── Stage 7: Validate ──
    if os.path.exists(paths["briefing_md"]) and os.path.exists(paths["articles"]):
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
    else:
        print("\n⚠️  Skipping validate: briefing.md or articles.jsonl not found", file=sys.stderr)

    # ── Stage 8: Render ──
    if os.path.exists(paths["briefing_md"]):
        # Resolve channel title from domain config
        channel_title = "Briefing"
        try:
            with open(paths["domain_config"]) as f:
                domain_cfg = yaml.safe_load(f)
            channel_title = domain_cfg.get("domain", {}).get("title", "Briefing")
        except Exception:
            pass
        run_stage("render", [
            "--input", paths["briefing_md"],
            "--output-dir", paths["data_dir"],
            "--title", channel_title,
            "--domain", paths["domain_config"],
            "--footer", "由 AI Agent 自动生成 · 每日 7:30 CST",
            "--template", os.path.join(DOMAINS_DIR, args.domain, "templates", "daily.html"),
        ], "8/8 Render HTML + PDF")
    else:
        print("\n⚠️  Skipping render: briefing.md not found", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # ── DB Ingestion: write structured data to SQLite ──
    # NOTE: Story Bridge JSONL writes (_try_ingest_event_threads, _try_ingest_causal_and_judgments)
    # are deprecated. DB ingest writes directly to SQLite from event-threads.json.
    # Story-tracking reads (_try_generate_story_context, _export_thread_keywords) now query SQLite.
    _try_db_ingest(args.domain, args.date, paths, db_dir)

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
    """Generate BriefingContext for the agent, from SQLite story-tracking data."""
    try:
        import sys as _sys
        _sys.path.insert(0, PROJECT_ROOT)
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "stratum", "subsystems", "story-tracking"))
        from briefing_context import generate_context
        from types import SimpleNamespace
        from stratum.db.connection import get_db

        conn = get_db(domain_id)

        # Check if events exist
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count == 0:
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
            "SELECT id, target_type, target_entity_ids, hypothesis, confidence,"
            " expected_verification, result, created_at FROM judgments"
        ).fetchall()
        judgments = []
        for r in j_rows:
            target_ids = json.loads(r["target_entity_ids"]) if r["target_entity_ids"] else []
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

        ctx = generate_context(domain_id, "daily", run_date, events, edges, judgments)
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

        threads = []
        for r in rows:
            keywords = set()
            title = r["title"] or ""
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

            entity_ids = json.loads(r["entity_ids"]) if r["entity_ids"] else []
            keywords.update(e.lower() for e in entity_ids if e)

            threads.append({
                "thread_id": r["thread_id"] or r["id"],
                "label": title or r["id"],
                "status": r["status"] or "active",
                "keywords": sorted(keywords)[:20],
                "description": "",
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


def _try_db_ingest(domain_id: str, run_date: str, paths: dict, db_dir: str):
    """Ingest pipeline outputs into SQLite database."""
    db_path = os.path.join(db_dir, domain_id, f"{domain_id}.db")
    if not os.path.exists(db_path):
        return

    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(PROJECT_ROOT))
        from stratum.db.ingest import ingest_daily_events, update_entities_after_run, update_query_stats, ingest_entity_snapshots, ingest_keyword_article, ingest_keyword_event

        # 1. Ingest events/threads/causal/judgments from event-threads.json
        event_threads_path = os.path.join(paths["data_dir"], "event-threads.json")
        if not os.path.exists(event_threads_path):
            alt_path = os.path.join(paths["data_dir"], "..", "event-threads", "event-threads.json")
            if os.path.exists(alt_path):
                event_threads_path = alt_path

        if os.path.exists(event_threads_path):
            stats = ingest_daily_events(event_threads_path, domain_id, run_date)
            if stats["errors"]:
                print(f"\n⚠️  DB ingestion errors: {stats['errors']}", file=sys.stderr)
            if any(stats[k] for k in ['events', 'causal_edges', 'judgments', 'new_threads']):
                print(f"\n💾 DB: {stats['events']} events, {stats['causal_edges']} edges, " +
                      f"{stats['judgments']} judgments, {stats['new_threads']} new threads", file=sys.stderr)

        # 2. Update entity article counts
        articles_path = paths.get("articles", "")
        if os.path.exists(articles_path):
            entity_counts = {}
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
                n = update_entities_after_run(domain_id, stats_list)
                print(f"💾 DB: {n} entities updated", file=sys.stderr)

        # 3. Entity snapshots
        n = ingest_entity_snapshots(domain_id, "daily", run_date)
        print(f"💾 DB: {n} entity snapshots", file=sys.stderr)

    except Exception as e:
        print(f"⚠️  DB ingestion skipped: {e}", file=sys.stderr)


def _run_collector(domain: str, workspace: str, run_date: str, raw_path: str):
    """Run direct_fetch collector and merge results into raw.json."""
    try:
        from stratum.collectors.direct_fetch import collect
        collector_results = collect(domain, workspace, run_date)

        if not collector_results:
            return

        # Read existing raw.json (search results)
        search_results = []
        if os.path.exists(raw_path):
            with open(raw_path) as f:
                data = json.load(f)
                search_results = data if isinstance(data, list) else data.get("results", [])

        # Merge: collector first, search results appended (collector wins on URL conflict)
        seen_urls = set()
        merged = []
        for r in collector_results:
            d = r.to_dict() if hasattr(r, 'to_dict') else r
            url = d.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(d)

        for r in search_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(r)

        with open(raw_path, "w") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        added = len(collector_results)
        total = len(merged)
        print(f"\n📡 Collector: +{added} direct-fetch → {total} total in raw.json",
              file=sys.stderr)

    except Exception as e:
        print(f"⚠️  Collector skipped: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
