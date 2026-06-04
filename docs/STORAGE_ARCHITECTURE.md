# Storage Daily Architecture

This document describes Stratum through the Storage daily report path. It is an
end-to-end map of module relationships, stage order, and the key data flow from
domain configuration to rendered report and SQLite feedback.

## Module Relationships

```text
domains/storage
  -> orchestrator
  -> sourcing/watchlist + sourcing/discovery
  -> stages/acquisition
  -> stages/enrich
  -> stages/verify
  -> stages/normalize
  -> stages/cluster
  -> db + story_tracking context
  -> stages/edit
  -> stages/validate
  -> stages/repair
  -> stages/validate (recheck)
  -> stages/render
  -> db ingest + monitoring feedback
```

Ownership summary:

| Module | Role in Storage daily |
|:---|:---|
| `domains/storage` | Domain-owned companies, terms, source registry, query templates, editorial rules, boilerplate rules, and HTML templates. |
| `stratum/orchestrator` | CLI/runtime coordination, path resolution, manifest writing, acquisition/stage execution, story context setup, DB ingest handoff. |
| `stratum/sourcing/watchlist` | Source-first acquisition from RSS, direct URL fetch, and browser-backed configured sources. |
| `stratum/sourcing/discovery` | Bocha/Tavily routing, query performance, engine health, curation, and supplemental broad search. |
| `stratum/stages` | Daily stage scripts and stage-local artifact contracts. |
| `stratum/subsystems/story_tracking` | Deterministic story context selection and prompt-ready context formatting. |
| `stratum/subsystems/event_thread` | Event-thread lifecycle, matching, update, archive, and watch-query generation helpers. |
| `stratum/db` | SQLite state store for search queries, events, threads, judgments, entity snapshots, report persistence, evidence links, and semantic reads. |
| `stratum/contracts` | Shared schemas and small shared data contracts such as artifact specs and report windows. |
| `stratum/subsystems/monitoring` | Health, coverage, and feedback diagnostics. |

`stratum/` must stay domain-agnostic. Storage-specific knowledge enters through
`domains/storage/domain.yaml`, `domains/storage/queries.yaml`, and
`domains/storage/templates/`.

## Daily Stage Flow

The daily path is orchestrated by `stratum/orchestrator/pipeline.py`.
Watchlist are a source-first sidecar before the numbered acquisition stage.

| Step | Owner | Main input | Main output | Contract |
|:---|:---|:---|:---|:---|
| Watchlist | `stratum.sourcing.watchlist` via orchestrator | `domain.yaml` source registry, run date | seeded `raw.json`, `watchlist_stats.json` | Watchlist records are `search_result.json`-compatible. |
| Acquisition | `stages/acquisition`, `sourcing/discovery` | config, DB queries or `queries.yaml`, seeded `raw.json` | merged `raw.json`, `raw.stats.json` | Discovery supplements watchlist evidence and preserves query diagnostics. |
| Enrich | `stages/enrich` | `raw.json` | `enriched.json` | Adds publication-date lineage. |
| Verify | `stages/verify` | `enriched.json`, `domain.yaml` | `verified.jsonl`, `verified.stats.json` | Applies freshness, source, duplicate, blocklist, and evidence acceptance gates. |
| Normalize | `stages/normalize` | `verified.jsonl`, `domain.yaml`, optional `thread_keywords.json` | `articles.jsonl` | Builds ArticleRecord rows with canonical entities, terms, source metadata, and typed claims. |
| Cluster | `stages/cluster` | `articles.jsonl` | `clusters.json` | Groups related articles by thread anchors and entity/term overlap. |
| Story context | `orchestrator.story_runtime`, `db`, `stratum.subsystems.story_tracking` | SQLite events, judgments, coverage universe | `story_context.json` | Supplies carried-forward stories, due judgments, gaps, and causal context for Edit. |
| Edit | `stages/edit` | `articles.jsonl`, `clusters.json`, `story_context.json` | `Storage_Daily_Briefing_{date}.md`, plan/chunk/trace sidecars, optional `event-threads.json` | Builds dynamic report categories, LLM-edited blocks, source lines, and structured story state. |
| Validate | `stages/validate` | `Storage_Daily_Briefing_{date}.md`, `articles.jsonl`, optional event-thread schemas | `validate_report.json` / exit status | Checks citations, dates, structured output, source support, and overclaim rules. |
| Repair | `stages/repair` | `Storage_Daily_Briefing_{date}.md`, `articles.jsonl`, `validate_report.json` | rewritten Markdown, `repair_report.json` | Rewrites or drops invalid items using validate telemetry and support-article evidence. |
| Validate Recheck | `stages/validate` | repaired `Storage_Daily_Briefing_{date}.md`, `articles.jsonl`, optional event-thread schemas | final `validate_report.json` / exit status | Confirms the repaired artifact is valid before render or DB publish steps continue. |
| Render | `stages/render` | `Storage_Daily_Briefing_{date}.md`, Storage HTML template | `Storage_Daily_Briefing_{date}.html`, optional `Storage_Daily_Briefing_{date}.pdf` | Converts Markdown to template-backed delivery artifacts. |
| DB ingest | `orchestrator.db_runtime`, `db` | fresh daily artifacts | SQLite rows, thread watch queries | Persists events, judgments, entity snapshots, query stats, optional foundation report/evidence rows. |

## Key Data Flow

```text
domain.yaml + queries.yaml + config.yaml
        |
        v
watchlist seed raw.json
        |
        v
discovery supplements raw.json and writes raw.stats.json
        |
        v
enriched.json
        |
        v
verified.jsonl + verified.stats.json
        |
        v
articles.jsonl
        |
        v
clusters.json
        |
        +--------------------+
        |                    |
        v                    v
SQLite story state      story_context.json
        |                    |
        +----------> edit <--+
                     |
                     v
Storage_Daily_Briefing_{date}.md + edit sidecars + event-threads.json
                     |
                     v
validate -> repair (if needed) -> validate_recheck -> render -> HTML/PDF
                     |
                     v
DB ingest -> SQLite feedback for the next run
```

Important feedback loops:

- `raw.stats.json` updates query yield and search-engine health in SQLite.
- `articles.jsonl` updates entity counts and entity snapshots.
- `event-threads.json` updates threads, events, causal edges, and judgments.
- DB event-thread watch signals become future thread-bound Search queries.
- DB story records become the next run's `story_context.json`.
- DB thread keywords become the next run's `thread_keywords.json` for Normalize.

## Artifact And State Roots

Daily artifacts live under:

```text
{reports_dir}/storage/data/{date}/
```

Typical daily artifacts:

Rendered delivery artifacts use the canonical basename pattern
`{Domain}_{Timescale}_Briefing_{Period}`. For example, a Storage daily run on
`2026-05-30` writes `Storage_Daily_Briefing_2026-05-30.md`,
`Storage_Daily_Briefing_2026-05-30.html`, and
`Storage_Daily_Briefing_2026-05-30.pdf`.

| Artifact | Producer | What It Contains | Used By |
|:---|:---|:---|:---|
| `raw.json` | watchlist sidecar + acquisition stage | The single raw evidence pool for the run. Watchlist records are written first, then Bocha/Tavily discovery supplements uncovered areas. | Enrich, DB foundation article persistence, debugging raw coverage. |
| `watchlist_observations.jsonl` | watchlist parsers/extractors | The first structured RSS, direct URL, and browser observations after fetch and parse, before admission, scoring, ranking, dedupe, or candidate decisions. | Parser review, source extraction debugging, admission-denominator analysis. |
| `watchlist_results.json` | orchestrator watchlist runtime | The unmerged RSS, direct URL, and browser watchlist result set for the run, before broad discovery supplements or raw-pool dedupe. | Source review, watchlist yield analysis, source tuning, debugging configured-source coverage. |
| `watchlist_candidates.jsonl` | orchestrator watchlist runtime | Watchlist admission audit records, including accepted, weak-signal, and rejected candidates with scores and reasons. | Admission tuning, missed-signal review, source parser debugging. |
| `discovery_observations.jsonl` | discovery subsystem + acquisition stage | The first normalized Bocha/Tavily observations after provider result normalization, before curation scoring, ranking, pruning, or selected/rejected status. | Provider yield review, query debugging, curation-denominator analysis. |
| `discovery_candidates.jsonl` | acquisition stage | Broad discovery raw candidates with curator selected/rejected status after scoring, ranking, and pruning. | Curation tuning, Bocha/Tavily yield review, query diagnostics. |
| `raw.stats.json` | acquisition stage | Per-query status, engine attempt chains, engine health, coverage diagnostics, query performance, skipped-query stats, and rewrite hints. | Orchestrator DB ingest, discovery feedback, source/query maintenance. |
| `watchlist_stats.json` | orchestrator watchlist runtime | Source-level watchlist health and acquisition diagnostics. | Monitoring, source health review, future acquisition priority. |
| `enriched.json` | Enrich stage | Raw records with publication-date fields and `date_source` lineage repaired or added. | Verify. |
| `verified.jsonl` | Verify stage | Accepted evidence records after freshness, source, duplicate, URL, and quality gates. | Normalize, Validate, evidence audit. |
| `verified.stats.json` | Verify stage | Verification totals, rejection reasons, date-confidence counts, quality flags, and corroboration levels. | Diagnostics, future verification calibration. |
| `articles.jsonl` | Normalize stage | ArticleRecord rows with stable ids, canonical URLs, source metadata, entities, terms, typed numeric claims, and optional event-thread matches. | Cluster, Edit, Validate, DB ingest, entity snapshots. |
| `clusters.json` | Cluster stage | Story clusters keyed by article ids, entity/term overlap, optional thread anchors, and confidence diagnostics. | Edit, monitoring coverage checks. |
| `story_context.json` | orchestrator story runtime + `stratum.subsystems.story_tracking` + DB reads | Carried-forward stories, due judgments, coverage gaps, causal chains, and unassigned events for the current run. | Edit prompt context. |
| `Storage_Daily_Briefing_{date}.md` | Edit stage | The generated Storage daily Markdown report before final rendering. | Validate, Render, DB foundation report persistence. |
| `validate_report.json` | Validate stage | Structured item-level validation findings, counts, cited-source/date context, and schema diagnostics. | Repair, orchestrator quality telemetry, operator/debug review. |
| `repair_report.json` | Repair stage | Rewrite/drop actions, support-article lineage, and repair counters for the current report. | Orchestrator quality telemetry, operator/debug review, DB artifact audit. |
| `briefing_plan.json` | Edit stage | Deterministic report plan: selected items, categories, evidence links, omitted/dropped candidates, and planning metadata. | DB foundation report item persistence, debugging report selection. |
| `briefing_chunks.json` | Edit stage | LLM-edited category block outputs and item text; kept under the historical filename for compatibility. | DB foundation report item persistence, debugging generated blocks. |
| `edit_trace.json` | Edit stage | Prompt/block diagnostics, plan counts, fallback decisions, boilerplate checks, and edit/runtime trace data. | Debugging and report-quality review. |
| `event-threads.json` | Edit stage | Optional structured threads, causal edges, and judgments produced from the report. | Validate schema checks, DB event/judgment ingest, next-run story tracking. |
| `Storage_Daily_Briefing_{date}.html` | Render stage | Template-backed HTML delivery artifact. | User delivery, deployment/report archive. |
| `Storage_Daily_Briefing_{date}.pdf` | Render stage | PDF rendering of the HTML report when local Chrome/PDF support is available. | User delivery, deployment/report archive. |
| `run_manifest.json` | orchestrator run context | Runtime identity, stage statuses, artifact paths, summary counts, per-stage durations, validate/repair quality telemetry, and failure/nonblocking diagnostics. | Audit, deployment, resume/debug review. |

Durable SQLite state lives separately under:

```text
{db_dir}/storage/storage.db
```

Reports and sidecars are artifacts. SQLite is the durable state layer used for
query feedback, story continuity, judgment tracking, higher-scale synthesis,
and future report context.

## Boundary Principles

- Domain data belongs in `domains/storage`, not in framework code.
- Stages own orchestration, artifact I/O, and stage contract handoff.
- Algorithm modules own scoring, ranking, matching, policy decisions, and
  validation rules.
- DB services own persistence and semantic reads, not Discovery APIs, watchlist,
  LLMs, or rendering.
- Structured handoffs are tracked in `docs/CONTRACT_INVENTORY.yaml`.
- Higher-scale reports consume the SQLite state produced by daily runs; the
  daily flow is therefore the base memory layer for weekly/monthly/quarterly
  and yearly synthesis.
