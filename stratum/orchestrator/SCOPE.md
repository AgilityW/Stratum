# orchestrator - pipeline orchestration layer

## Purpose

`stratum/orchestrator` is Stratum's command-line orchestration entrypoint. It
connects config, domain assets, stage scripts, watchlist, SQLite story
tracking, and temporal profiles into one complete pipeline run.

The current code entrypoint is `pipeline.py`. Daily runs are orchestrated
directly through the 8-stage chain; weekly/monthly/quarterly/yearly runs are
delegated to the DB-native timescale temporal runner in `stratum/temporal`.

## Modules

| File | Role |
|:---|:---|
| `pipeline.py` | CLI entrypoint and daily/higher-scale dispatch only. It should not own stage algorithms, watchlist strategy logic, or DB persistence details. |
| `run_context.py` | Path resolution, subprocess stage execution, resume gates, manifest writing, locale expansion, and DB-ingest mode gates. |
| `artifacts.py` | Cleanup of legacy run artifacts and raw-data aliases. |
| `watchlist_runtime.py` | Watchlist execution, raw merge, post-collect diagnostics, and watchlist health handoff. |
| `collector_runtime.py` | Narrow compatibility facade for older imports that still point at the pre-watchlist runtime name. |
| `story_runtime.py` | Story context generation and SQLite-backed `thread_keywords.json` export for the daily feedback loop. |
| `db_runtime.py` | Daily SQLite ingest orchestration through DB module contracts for events, entity snapshots, watch queries, and foundation writes. |
| `db_foundation.py` | Opt-in DB foundation 0.1 daily report/evidence bundle assembly after the explicit foundation migration exists. |
| `signal_attach.py` | Review entrypoint that runs or reuses a normal daily report and then attaches signal-awareness outputs for next-run collection-readiness review. |

## Boundaries

### Owns

- Parse runtime arguments: domain, date, config, output-dir, raw-input,
  from-stage, and skip-agent.
- Resolve `output_dir`, `reports_dir`, and `db_dir` from `config.yaml`.
- Write runtime identity into `run_manifest.json`: development runs use
  `mode=development`, while deployment runs are locked by
  `STRATUM_RELEASE_VERSION`, `STRATUM_RELEASE_COMMIT`, and
  `STRATUM_DEPLOYMENT_ID`.
- Export the resolved `db_dir` as `STRATUM_DB_DIR` so DB helpers and the
  pipeline use the same SQLite root.
- Run the 8 daily stages: acquisition, enrich, verify, normalize, cluster, edit,
  validate, and render.
- Delegate weekly/monthly/quarterly/yearly runs to
  `stratum.temporal.timescale` for DB-native exploring, synthesis,
  Markdown, and render orchestration.
- Call `stratum.sourcing.watchlist.collect()` before broad discovery, seed `raw.json` with
  RSS/URL/browser results, then let discovery supplement uncovered areas. This is
  the project-level evidence acquisition priority and applies to any active
  fresh/raw evidence run, not only daily or one domain.
- Consume the previous `thread_keywords.json` before Normalize.
- Generate `story_context.json` from SQLite before Edit.
- Pass `domain.yaml` `companies[].id` into Story Tracking as the coverage
  entity universe so cold-start or uncovered entities can appear in coverage
  gaps.
- Persist structured events, entity stats, and snapshots to SQLite at the end
  of the pipeline.
- Export `thread_keywords.json` from SQLite after structured event ingest so
  the next Normalize run can consume it.

### Does Not Own

- Does not own stage-internal algorithms. Each stage remains responsible for
  its own CLI script.
- Does not call broad discovery APIs directly. Acquisition delegates to
  `stratum.sourcing.discovery`.
- Does not call watchlist strategies directly. Watchlist dispatch belongs to
  `stratum.sourcing.watchlist`.
- Does not contain domain knowledge. Domain data must come from
  `domains/{id}/`.
- Does not duplicate SQLite data models as file-layer JSONL logic.
- Does not keep stacking helpers inside `pipeline.py`. New helpers must first
  be placed in `run_context`, `watchlist_runtime`, `story_runtime`,
  `db_runtime`, `db_foundation`, `artifacts`, or `stratum/temporal`.

## Data Flow

```text
config.yaml + domains/{id}/
        |
        v
watchlist (RSS/direct URL/browser) -> raw.json
        |
        v
Bocha/Tavily discovery supplement -> raw.json
        |
        v
enrich -> verify -> normalize -> cluster
        |
        v
story_context.json -> edit -> {Domain}_{Timescale}_Briefing_{period}.md
        |
        v
validate -> render -> {Domain}_{Timescale}_Briefing_{period}.html/pdf
        |
        v
SQLite ingest
        |
        +--> export thread_keywords.json from SQLite for next run
```

## Runtime Outputs

| Output | Path |
|:---|:---|
| stage data | `{reports_dir}/{domain}/data/{date}/` |
| raw acquisition pool | `raw.json` |
| discovery query stats sidecar | `raw.stats.json` |
| watchlist health sidecar | `watchlist_stats.json` |
| verified articles | `verified.jsonl` |
| verification stats sidecar | `verified.stats.json` |
| normalized articles | `articles.jsonl` |
| clusters | `clusters.json` |
| briefing | `{Domain}_{Timescale}_Briefing_{period}.md`, `{Domain}_{Timescale}_Briefing_{period}.html`, `{Domain}_{Timescale}_Briefing_{period}.pdf` |
| edit plan/debug | `briefing_plan.json`, `briefing_chunks.json`, `edit_trace.json` |
| edit context | `story_context.json` |
| run manifest | `run_manifest.json` |
| feedback keywords | `{reports_dir}/{domain}/data/story-tracking/thread_keywords.json` |
| source health records | `{health_data_dir}/{domain}/source-daily.ndjson` |
| SQLite DB | `{db_dir}/{domain}/{domain}.db` |

`reports_dir` and `db_dir` are separate runtime roots. Reports, raw/stage
sidecars, rendered HTML/PDF, and run manifests are artifacts; SQLite is durable
state. The orchestrator resolves both roots before running and rejects configs
where both roots point to the same directory.

For `weekly`, `monthly`, `quarterly`, and `yearly`, artifacts use the same
stable naming rule with the timescale segment:

```text
{Domain}_{Timescale}_Briefing_{period}.md/html/pdf
```

Higher-scale artifacts are written under:

```text
{reports_dir}/{domain}/data/{timescale}/{period}/
```

For user-selected custom windows, `--start-date YYYY-MM-DD --end-date
YYYY-MM-DD` resolves to a stable period id:

```text
custom-{start}_to_{end}
```

The selected `--timescale` remains the report profile/template, while the
custom window controls which lower-scale DB records are consumed. `--date` is
required only for standard periods; custom higher-scale runs can omit it.

Daily runs may also use an explicit evidence window. `--lookback-hours 48`
derives `--start-date`/`--end-date` for acquisition and passes the matching
`--stale-days` window to Verify. Run manifests record both `report_window` and
`evidence_window`, so the source freshness window is visible even when the
delivery period remains a single date.

`raw.json` is the only raw dataset for a domain/date run. Sidecars such as
`raw.stats.json` and `watchlist_stats.json` record diagnostics, not alternate
raw copies.

After acquisition completes, the orchestrator ingests `raw.stats.json` into the
SQLite `queries` table so query hit counters and `last_run` stay current.
When a domain DB exists, the orchestrator still passes
`domains/{id}/queries.yaml` into acquisition as the baseline fallback. The acquisition
stage decides whether to use active DB queries or fall back to YAML, preventing
an empty DB from suppressing the run's query set.
Watchlist health records preserve source status in tags and metadata. Status
`unsupported` is written as `scanned: false` because it represents missing
runtime capability or unsupported configuration, not an upstream source scan.

## Failure Policy

- Core deterministic stages fail hard through `run_stage()`.
- Edit failure is hard-blocking before validate/render so stale briefing artifacts are not republished.
- Before a fresh Edit attempt, canonical Markdown/HTML/PDF delivery artifacts
  are cleared; `run_manifest.json` remains the source of truth if the run fails.
- Watchlist, story context generation, thread keyword export, and DB ingest are best-effort helpers. They log warnings and do not block the main pipeline.
- `run_manifest.json` records stage-level `success`, `skipped`, `provided`,
  `empty`, `failed`, and `failed_nonblocking` statuses plus per-stage metrics
  such as duration, validation counts, and repair counts. On hard stage
  failure, the manifest is written before the process exits.
- Every run manifest includes `runtime`. Development runs may be dirty and are
  marked as such; deployment runs must be launched by the deployment wrapper so
  the manifest carries locked release version, commit, environment, deployment
  id, and deployment manifest path.
- DB ingest is gated by fresh artifact surfaces: event/thread ingestion runs
  only when Edit may have produced new `event-threads.json`, while entity
  counts and snapshots run only when Normalize produced fresh `articles.jsonl`.
  Validate/render-only resumes record DB ingest as skipped.
- When a database has already been explicitly migrated to the DB foundation 0.1,
  DB ingest also persists lightweight article metadata, structured daily report
  sections/items, item evidence links, normalized event-article links, and run
  artifact indexes. Unmigrated databases skip this structured write path.
- `thread_keywords.json` is exported only after successful event DB ingest. This
  keeps the next run's normalize feedback file aligned with newly persisted
  events instead of the previous SQLite state.
- `thread_keywords.json` is aggregated by `thread_id`. Multiple events in the
  same continuing story contribute a single keyword profile, preventing
  Normalize from treating one thread as several competing candidates.
- Non-daily timescales do not run the daily acquisition/enrich/verify/normalize/edit
  chain. They delegate to `stratum.temporal.timescale`, which uses DB-native
  synthesis to consume all lower-scale structured state plus same-scale fresh
  evidence already written into `articles`, write Markdown, render HTML/PDF
  with the matching timescale artifact name, and write `run_manifest.json`.

## Resume Policy

`--from-stage` starts execution at the named stage and skips earlier stages:

- `--from-stage enrich` expects an existing `raw.json`.
- `--from-stage verify` expects an existing `enriched.json`.
- `--from-stage normalize` expects an existing `verified.jsonl`.
- `--from-stage cluster` expects an existing `articles.jsonl`.
- `--from-stage edit` expects existing `articles.jsonl` and `clusters.json`.
- `--from-stage validate` expects the existing canonical briefing Markdown
  artifact plus `articles.jsonl`; if violations remain, the orchestrator may
  continue into Repair and Revalidate.
- `--from-stage repair` expects the existing canonical briefing Markdown,
  `articles.jsonl`, and `validate_report.json`.
- `--from-stage validate_recheck` expects an already repaired briefing Markdown
  plus `articles.jsonl`.
- `--from-stage render` expects the existing canonical briefing Markdown
  artifact.

Watchlist and discovery only run when acquisition runs, so resume runs do not mutate
an existing `raw.json`.

Resume stage names are validated against the canonical pipeline order. Unknown
stage names fail loudly instead of defaulting to a full run, so typoed internal
calls or future entrypoints cannot silently mutate earlier artifacts.

DB ingest follows the same resume contract: `--from-stage validate`,
`--from-stage repair`, `--from-stage validate_recheck`, and `--from-stage render`
do not re-ingest prior articles/events, preventing re-validation,
post-validate repair, or re-rendering from changing SQLite counters.

## Development vs Deployment

Development entrypoints (`make daily`, direct `pipeline.py`) run from the
working tree and are allowed to change with ongoing edits. Deployment entrypoints
live under `scripts/` and are deliberately separate:

- `scripts/release.sh VERSION` creates an annotated Git tag only from a clean,
  tested worktree.
- `scripts/deploy.sh --version <tag> ...` rejects branches/commits, exports the
  tag into `{deploy_root}/{env}/releases/{version}`, creates a release-local
  virtualenv, copies instance config, writes `deployment_manifest.json`, and
  moves `{deploy_root}/{env}/current`.
- `scripts/run_daily.sh` runs only through the active `current`
  symlink and injects deployment identity into the pipeline process.
- `scripts/healthcheck.sh` validates the active deployment without network/API
  calls.
- `scripts/rollback.sh` reactivates an already deployed release directory.

After fresh event DB ingest, the orchestrator also turns event-thread watch
targets into active SQLite discovery queries. Explicit `watch_signals` are used
when present; otherwise the event-thread engine falls back to the thread's
canonical question or title. The orchestrator expands `config.yaml
source_languages` through `locales`, then writes one thread-bound
`verification` query per watch target and locale with `dimension =
thread_watch`. The next acquisition run can therefore follow emerging, active, and
cooling stories through the normal DB-backed query path even when Agent output
omits optional watch signals.

## Dependencies

- `stratum/stages/*/*.py`
- `stratum/temporal`
- `stratum/sourcing/watchlist`
- `stratum/sourcing/discovery`
- `stratum/subsystems/story_tracking/briefing_context.py`
- `stratum/db`
- `domains/{id}/domain.yaml`
- `domains/{id}/queries.yaml`
- `domains/{id}/templates/daily.html`

Edit profiles are loaded from `stratum/stages/edit/prompts/manifest.yaml`.
The active daily path uses Edit v3 dynamic category blocks and Markdown
templates from `stratum/stages/edit/templates/`. Runtime profiles are defined
in `stratum/temporal/profiles.py`: daily uses the live 8-stage chain, while
weekly/monthly/quarterly/yearly use DB-native synthesis and render. Future
LLM-assisted higher-scale editors should add/adjust a runtime profile first,
then wire the stage implementation behind that profile. Profiles that do not
opt into `budget.edit_mode: v3` fail fast.

The daily Markdown template is organized into five major chunk keys: `today`,
`industry`, `signals`, `focus`, and `contrarian`. Render turns those major
chunks into visually prominent localized section headers and renders dynamic
categories inside the industry chunk as lower-level subsection headers.
