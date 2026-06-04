# Storage Baseline

This document defines the explicit `0.1` baseline for the current Storage daily
report path. It is the canonical checklist for deciding whether the present
pipeline is stable enough to release, deploy, or use as the reference point for
later 0.x work.

The baseline is intentionally narrow:

- one domain: `storage`
- one report shape: daily
- one stable production engine: `stratum/orchestrator/pipeline.py`
- one stable delivery contract: briefing Markdown, HTML, PDF, manifest, and
  required sidecars under the daily run directory

Future MCP, agent, signal review, and higher-scale work may be added around
this baseline, but they do not replace it until they are explicitly promoted.

## Canonical Run Commands

Development baseline run:

```bash
make daily DOMAIN=storage DATE=2026-05-30
```

Equivalent direct CLI:

```bash
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-30
```

Deployment baseline run:

```bash
make run-deployed-daily \
  ENV=production \
  DOMAIN=storage \
  DATE=2026-05-30 \
  DEPLOY_ROOT="$HOME/stratum/deployments"
```

## Required Artifacts

A clean Storage daily `0.1` run must produce these required artifacts in:

```text
{reports_dir}/storage/data/{YYYY-MM-DD}/
```

Required baseline artifacts:

- `raw.json`
- `raw.stats.json`
- `watchlist_stats.json`
- `verified.jsonl`
- `verified.stats.json`
- `articles.jsonl`
- `clusters.json`
- `story_context.json`
- `briefing_plan.json`
- `briefing_chunks.json`
- `edit_trace.json`
- `validate_report.json`
- `repair_report.json`
- `run_manifest.json`
- `Storage_Daily_Briefing_{date}.md`
- `Storage_Daily_Briefing_{date}.html`
- `Storage_Daily_Briefing_{date}.pdf`

Optional artifacts may exist, such as `event-threads.json` or signal-review
attachments, but they are not required to declare the `0.1` baseline healthy.

## Validate And Repair Expectations

The baseline quality gate is:

1. `validate` must write `validate_report.json`
2. if violations exist, `repair` must write `repair_report.json`
3. `validate_recheck` must pass before Render can publish final briefing HTML
   or PDF

For a clean successful baseline run:

- final manifest status is `ok`
- final validate status is `success`
- repair may be `skipped` when no changes are needed
- repair may be `success` when it rewrites or drops invalid items and the
  follow-up validation passes

The baseline is not healthy if Render publishes while unresolved validation
violations remain.

## Deployment Path

The production baseline is deployment-only and tag-locked:

- release from a clean tree with `make release VERSION=v0.1.1`
- deploy with `make deploy ...`
- run production reports only through `scripts/run_daily.sh`

Baseline production runs must carry deployment identity inside
`run_manifest.json`, including runtime mode, release version, release commit,
deployment id, and deployment manifest path.

## Rollback Rule

Rollback is part of the baseline contract. If a deployed Storage daily release
is not trustworthy, production returns to the prior deployed tag with:

```bash
make rollback VERSION=v0.1.0 ENV=production DEPLOY_ROOT="$HOME/stratum/deployments"
```

Rollback does not rebuild code. It reactivates a previously deployed release
directory and preserves the tag-locked deployment model.

## Promotion Rule

This `0.1` baseline remains the canonical Storage daily path until a later
replacement is:

- documented
- tested
- deployed through the same release and rollback discipline
- explicitly promoted as the new baseline in active docs and tests
