# db - SQLite persistence layer

## Purpose

`stratum/db` owns SQLite schema creation, domain seeding, and persistence helpers for story tracking, query selection, coverage records, multi-scale run logs, and entity snapshots.

The DB is the long-lived memory of the pipeline. File outputs under a run date are artifacts; SQLite is the stateful layer.

For the higher-level architecture and scale-cascade contract, see
`ARCHITECTURE.md`.
For project-wide dependency contract rules, see `docs/ENGINEERING_RULES.md`.

## Modules

| File | Role |
|:---|:---|
| `schema.sql` | all table definitions and indexes |
| `ARCHITECTURE.md` | DB architecture, scale-cascade contract, migration contract, and cascade test database contract |
| `connection.py` | resolves DB path and opens schema-initialized connections |
| `seed.py` | seeds sources/entities/terms/keywords/queries from domain configs |
| `ingest.py` | writes pipeline outputs and exposes read helpers |
| `judgment_lifecycle.py` | judgment due-window checks, review-state normalization, verification preservation, and causal-edge review policy |
| `persistence.py` | explicit DB foundation 0.1 write helpers for article metadata, structured report bundles, item evidence links, artifacts, and lineage |
| `read_model.py` | reusable report/fresh-evidence/lineage read-model helpers plus JSON field parsing for DB service APIs |
| `semantic_reads.py` | reusable trend, key-event timeline, judgment-status, evidence-detail, entity-timeline, and technology-tracking read-model algorithms used by DB service APIs |
| `service.py` | semantic consumption and management APIs for report context, tracking, evidence, and cascade inputs; delegates report read-model details to `read_model.py` and semantic aggregation/filtering to `semantic_reads.py` |
| `synthesis/` | DB-native higher-scale synthesis package with engine, policy, ranking, evidence, event-building, and text-policy modules; see `synthesis/SCOPE.md` |
| `migration.py` | explicit production-safe migration inspection, backup, checksum, and ledger helpers |
| `cascade_fixture.py` | deterministic development/test fixture that builds and analyzes an articles-to-yearly cascade in a migrated test DB |
| `manage.py` | explicit CLI for DB inspect, backup, foundation migration, and cascade fixture build/analyze commands |
| `migrations/000010_foundation.sql` | explicit DB foundation 0.1 additive schema expansion for report, evidence, and lineage tables |

## Path Resolution

`connection.py` resolves the database root in this order:

- `STRATUM_DB_DIR` environment override
- project `config.yaml` `db_dir` if present
- fallback: `~/stratum/db`

DB file layout:

```text
{db_dir}/{domain}/{domain}.db
```

The database root is a state store, not the report artifact store. Report files
live under `{reports_dir}/{domain}/data/...`; SQLite lives under
`{db_dir}/{domain}/{domain}.db`. Production and testing can both use the
`storage` domain instance, but they must use different `db_dir` roots when they
should not share state.

acquisition stage has one important exception: when CLI receives `--db`, it reads that explicit SQLite path directly for daily query selection.

The orchestrator sets `STRATUM_DB_DIR` after parsing its runtime `db_dir`, so
story context generation, query-stat ingest, thread keyword export, and final
DB ingest all use the same SQLite root that the pipeline checked.

## Boundaries

### Owns

- Create schema automatically on connection.
- Seed DB from `domains/{domain}/domain.yaml` and `queries.yaml`.
- Ingest event threads, entity snapshots, query stats, keyword links, multi-scale run logs, and coverage records.
- Provide read helpers for Search, monitoring, `stratum.subsystems.story_tracking`, and higher-scale temporal execution consumers.
- Provide a dedicated database consumption and management layer for report
  context, story tracking, company tracking, technology tracking, evidence
  drill-down, and cascade input assembly.
- Keep DB reads and writes behind explicit contracts: writers use persistence
  helpers after explicit migrations; readers use service/synthesis APIs instead
  of ad hoc SQL in downstream modules.
- Provide explicit migration helpers for production schema evolution without
  silently mutating the current baseline runtime path.
- Preserve query coverage dimensions from `queries.yaml` into SQLite so
  DB-backed Search keeps the same coverage diagnostics as YAML-backed Search.

### Does Not Own

- Do not call search APIs, LLMs, or watchlist.
- Do not contain domain knowledge except what is loaded from domain config.
- Do not render or validate briefings.
- Do not hide synthesis ranking or policy algorithms inside DB read/write
  services. `synthesis/engine.py` orchestrates payload assembly, while rankers,
  policies, event builders, evidence matchers, and text-policy builders own
  tunable decisions.
- Do not hide trend, key-event, or judgment-status ranking decisions inside
  public DB service functions. `semantic_reads.py` owns deterministic semantic
  aggregation over rows that service APIs have already loaded.
- Do not hide judgment lifecycle decisions inside SQL filters or ingest
  replacement code. `judgment_lifecycle.py` owns pending/due checks,
  supported/challenged/invalidated/deferred/expired review-state
  normalization, confidence effects, and preservation of existing verification
  fields for judgments and causal edges.

## Main Read APIs

- `get_queries_for_scale(domain, scale)`
- `get_upstream_structured_data(domain, from_scale, start_date, end_date)`
- `get_last_cascade_run(domain, scale)`
- `get_entity_timeline(domain, entity_id)` — periodic snapshots, not raw events
- `get_entity_events(domain, entity_id, start_date=None, end_date=None, scale="daily", limit=100, order="desc")`
- `get_term_events(domain, term_id, start_date=None, end_date=None, scale="daily", limit=100, order="desc")`
- `get_term_company_progress(domain, term_id, entity_ids=None, start_date=None, end_date=None, scale="daily", limit_per_entity=50, order="desc")`
- `get_thread_timeline(domain, thread_id)`
- `get_story_context_records(domain)`
- `get_thread_keyword_events(domain)`
- `load_active_search_queries_from_path(db_path)`
- `get_keyword_cooccurrence(domain, keyword_id, min_count=3)`

The target management layer should also expose higher-level semantic APIs such
as `get_report_context()`, `get_cascade_inputs()`,
`get_technology_progress()`, `get_due_judgments()`, and
`get_report_item_evidence()`. It also exposes `get_key_timeline()` for
date/period-level key-event analysis. These APIs should hide table joins, JSON
parsing, period normalization, and lineage traversal from downstream report
generators and agents.

## Migration Policy

Production migrations are explicit operations. `connection.py` may keep small
additive compatibility checks for existing baseline columns, but larger schema
expansion must use the migration workflow:

- inspect the current DB
- back it up
- rehearse against a copied production DB
- apply a versioned migration
- record it in `schema_migrations`
- verify baseline and new read paths

This preserves the current baseline while version 0.x database capabilities are
introduced.

## Main Write APIs

- `ingest_daily_events(event_threads_path, domain, run_date)`
- `ingest_entity_snapshots(domain, scale, period, entity_article_counts=None)`
- `update_entities_after_run(domain, entity_stats, run_date=None, scale="daily")`
- `update_query_stats(domain, query_stats, run_date=None)`
- `get_latest_search_engine_health(domain)`
- `load_latest_search_engine_health_from_path(db_path)`
- `ingest_keyword_article(domain, article_keywords)`
- `ingest_keyword_event(domain, event_keywords)`
- `ingest_cascade_log(domain, log_data)`
- `ingest_coverage(domain, coverage_data)`
- `upsert_articles(domain, articles, run_date, artifact_path=None, scale="daily")` — explicit foundation evidence metadata persistence after foundation migration; higher-scale exploring writes same-scale articles with `scale=<weekly|monthly|quarterly|yearly>` and `run_date=<target period>`
- `upsert_report_bundle(domain, report, sections=None, items=None, item_events=None, item_threads=None, item_articles=None, artifacts=None, lineage=None)` — explicit foundation structured report persistence after foundation migration
- `link_event_articles(domain, links)` — explicit DB foundation 0.1 event-to-article evidence linking after foundation migration
- `foundation_schema_ready(conn)` — explicit foundation write-contract readiness check used by orchestrator DB ingest

## Testing Notes

Use temporary SQLite files for tests. Do not rely on the user machine's configured DB path for unit tests.

Cascade tests use one replayable temporary SQLite database. The fixture first
persists daily history, then runs DB-native weekly, monthly, quarterly, and
yearly synthesis in order. Tests should assert that each scale consumes the
lower-scale records already written by earlier steps instead of hand-writing
isolated higher-scale reports.

`update_query_stats()` accepts both legacy `id/articles_found` records and the
discovery subsystem's `query_id/results_count` records from `raw.stats.json`.
It writes a per-query daily ledger in `query_run_stats`, then recomputes
`queries.hit_count_7d`, `queries.hit_count_30d`, and `queries.avg_articles`
from that ledger when the columns exist. This prevents repeated acquisition runs,
historical backfills, and rolling-window expiration from drifting away from
the recorded daily facts.
It also persists Search `engine_health` diagnostics in `search_engine_health`
by `(engine, run_date)`. Stage acquisition can read the latest health records from
the explicit `--db` path and pass them into routing so unhealthy engines are
deprioritized before the next run starts.

`ingest_daily_events()` uses deterministic event ids
`ev-{run_date}-{thread_id}`. Re-ingesting the same run date replaces the event
payload but does not increment `threads.event_count_daily` again; a new daily
event for the same thread still increments the counter once.
Daily structured output can express priority as labels (`high`, `medium`,
`low`) or numeric ranks. DB ingest normalizes those values before writing
`threads.priority` and `events.priority`: high/P1/urgent = 1, medium/P2 = 2,
and low/P3/unknown = 3. Lower numbers sort first in timeline and watch-query
selection code.
After each event upsert, `thread_entities` subject links are rebuilt from all
stored events for that thread. This preserves historical entity associations
while removing stale entities from corrected same-day event payloads.
Before writing causal edges and judgments for a daily briefing, pending rows
from the same `source_briefing` are removed so corrected Agent output does not
leave stale hypotheses in future story context. Rows that already carry
verification outcomes are preserved, and replacement writes keep their
verification fields through `JudgmentLifecyclePolicy`.
`get_due_judgments()` and `stratum.subsystems.story_tracking` prompt context delegate pending/due
logic to the same policy. When `expected_verification` contains an ISO date,
that date controls whether the judgment is due for the requested window;
otherwise the policy falls back to `created_at` so legacy free-text
verification windows remain compatible. `pending` and `deferred` judgments are
still eligible for follow-up; completed outcomes are not.

Seeded queries include optional `dimension` and `include_domains` columns.
Existing databases are migrated additively by `connection.py`; helper functions
remain compatible with older minimal test tables that do not expose either
column. `include_domains` is stored as a JSON array so DB-backed acquisition can keep
the same source-first filters that query YAML supports. YAML seed, DB ingest,
and Search execution all share the same include-domain normalizer, so URL-like
or prefixed values collapse to host-only domains and malformed shapes fail
loudly.
`upsert_watch_queries()` persists event-thread watch signals as active
`verification` queries with `dimension = thread_watch` and a `thread_id`. Query
ids are deterministic from thread, locale, and query text, so reruns update the
same watch query instead of creating duplicates or erasing query-quality
rollups.
`get_queries_for_scale(domain, "daily")` includes both baseline `detection`
queries and active thread-bound `verification` queries for emerging, active,
and cooling threads. This keeps the public DB helper aligned with the Search
stage's direct SQLite loader and prevents cooling stories from disappearing
before they resolve. When a query has `include_domains`, the helper returns it
with the query so downstream Search execution does not degrade to broad web
search.

`ingest_entity_snapshots()` accepts per-run entity article counts from
`articles.jsonl`. When the orchestrator runs daily ingest, the same counts used
to update `entities.article_count_7d` are also written into
`entity_snapshots.article_count`.
`update_entities_after_run()` accepts the pipeline run date explicitly so
backfills and historical replays do not mark entity `last_seen` as the machine's
execution date.
It writes the current period's article count into `entity_snapshots`, then
recomputes `entities.article_count_7d` and `entities.article_count_30d` from
that snapshot ledger when the columns exist. This keeps same-day reruns,
historical backfills, and rolling-window expiration aligned with the recorded
period facts.

On databases that have explicitly applied `migrations/000010_foundation.sql`,
the daily orchestrator also writes foundation structured records after the legacy
event/entity ingest succeeds: article metadata, daily report identity,
template-level sections, report items from `briefing_plan.json` and
`briefing_chunks.json`, item-event/thread/article links, event-article links,
and report artifact indexes. If those foundation tables or article columns are
absent, this branch is skipped so the current baseline remains unchanged.

`cascade_fixture.py` can build a deterministic migrated test database and return
an analysis snapshot for the cascade contract. It is intentionally separate from
the production pipeline and is used to verify trend, judgment, key-event,
key-timeline, evidence, and lineage reads across daily, weekly, monthly,
quarterly, and yearly scales.
`python -m stratum.db.manage` exposes the same operational boundary at the
command line: `inspect`, `backup`, `apply-foundation`,
`build-cascade-fixture`, `analyze-cascade-fixture`, and `synthesize-report`.
The migration command requires a backup directory unless the caller explicitly
uses `--no-backup` for disposable test databases.

`synthesis/engine.py` consumes all lower-scale DB state through `get_cascade_inputs`
and same-scale fresh evidence from `articles.scale + run_date` or evidence
dates inside the requested custom window, then writes the target scale back
through `upsert_report_bundle`. It calls named synthesis algorithm components
instead of embedding tunable decisions in DB read/write code:
`synthesis.ranker.ThemeRanker` ranks candidate thread groups,
`synthesis.events.SynthesizedEventBuilder` creates target-scale event rows with
title, confidence, priority, source-event lineage, and field-limit policy,
`synthesis.evidence.CitationRanker` selects representative evidence with
source/source-type diversity and counter-evidence inclusion, and
`synthesis.policy.evaluate_theme` assesses lower-scale baseline strength,
same-scale fresh evidence quality, and the integration decision for each
candidate theme before report text or confidence movement is written. Trend
report items persist this policy output in `policy_decision`, making the
baseline/fresh/decision fields available to downstream validation, review, and
calibration without reparsing report prose. The policy objects own tunable
thresholds so future scoring, weighting, conflict detection, and scale-specific
calibration can be added without changing report assembly code. Synthesis then creates a structured report,
trend/judgment/lineage/fresh-evidence items, synthesized scale-level events for
top threads, item-event/thread/article links, and report lineage.
Weekly reports use an executive-briefing structure instead of a daily digest
rollup: Executive Summary, Core Themes, Signal vs Noise, Judgment Tracker,
Fresh Exploration Coverage, Next Week Watchlist, and source/confidence
boundaries. Each core theme must keep daily database evidence separate from
weekly exploring evidence, then synthesize executive implications,
confidence movement, and next validation points.
This gives `stratum/temporal` a deterministic DB-native consumption contract
while future LLM or search-assisted versions are developed on the same
persistence contract.
The top-level import `stratum.db.synthesis` is now the stable package surface.
Callers should use package exports or explicit package modules such as
`stratum.db.synthesis.policy`; older sibling `synthesis_*.py` wrapper modules
have been removed.

`get_entity_events()` and `get_term_events()` read accumulated event rows across
date ranges. This is the retrieval path for questions such as "Samsung's
important storage events over the last six months" or "HBM progress across key
companies". `get_term_company_progress()` groups term-related events by
mentioned entity so storage today and robot later can use the same query shape.
Event timeline read helpers, including `get_thread_timeline()`, return parsed
Python lists for JSON-array fields (`article_ids`, `entity_ids`, `term_ids`,
`source_domains`) so callers do not have to special-case raw SQLite strings.

The schema still has `cascade_logs` because the persistence layer supports
multi-scale run accounting, but the old standalone cascade runtime is not part
of the current project shape.
