# db - SQLite persistence layer

## Purpose

`stratum/db` owns SQLite schema creation, domain seeding, and persistence helpers for story tracking, query selection, coverage records, multi-scale run logs, and entity snapshots.

The DB is the long-lived memory of the pipeline. File outputs under a run date are artifacts; SQLite is the stateful layer.

## Modules

| File | Role |
|:---|:---|
| `schema.sql` | all table definitions and indexes |
| `connection.py` | resolves DB path and opens schema-initialized connections |
| `seed.py` | seeds sources/entities/terms/keywords/queries from domain configs |
| `ingest.py` | writes pipeline outputs and exposes read helpers |

## Path Resolution

`connection.py` resolves the database root in this order:

- `STRATUM_DB_DIR` environment override
- project `config.yaml` `db_dir` if present
- fallback: `~/WorkSpace/Stratum/DataBase`

DB file layout:

```text
{db_dir}/{domain}/{domain}.db
```

Search stage has one important exception: when CLI receives `--db`, it reads that explicit SQLite path directly for daily query selection.

The orchestrator sets `STRATUM_DB_DIR` after parsing its runtime `db_dir`, so
story context generation, query-stat ingest, thread keyword export, and final
DB ingest all use the same SQLite root that the pipeline checked.

## Boundaries

### 做什么

- Create schema automatically on connection.
- Seed DB from `domains/{domain}/domain.yaml` and `queries.yaml`.
- Ingest event threads, entity snapshots, query stats, keyword links, multi-scale run logs, and coverage records.
- Provide read helpers for Search, monitoring, story-tracking, and future higher-scale consumers.
- Preserve query coverage dimensions from `queries.yaml` into SQLite so
  DB-backed Search keeps the same coverage diagnostics as YAML-backed Search.

### 不做什么

- Do not call search APIs, LLMs, or collectors.
- Do not contain domain knowledge except what is loaded from domain config.
- Do not render or validate briefings.

## Main Read APIs

- `get_queries_for_scale(domain, scale)`
- `get_upstream_structured_data(domain, from_scale, start_date, end_date)`
- `get_last_cascade_run(domain, scale)`
- `get_entity_timeline(domain, entity_id)` — periodic snapshots, not raw events
- `get_entity_events(domain, entity_id, start_date=None, end_date=None, scale="daily", limit=100, order="desc")`
- `get_term_events(domain, term_id, start_date=None, end_date=None, scale="daily", limit=100, order="desc")`
- `get_term_company_progress(domain, term_id, entity_ids=None, start_date=None, end_date=None, scale="daily", limit_per_entity=50, order="desc")`
- `get_thread_timeline(domain, thread_id)`
- `get_keyword_cooccurrence(domain, keyword_id, min_count=3)`

## Main Write APIs

- `ingest_daily_events(event_threads_path, domain, run_date)`
- `ingest_entity_snapshots(domain, scale, period, entity_article_counts=None)`
- `update_entities_after_run(domain, entity_stats, run_date=None, scale="daily")`
- `update_query_stats(domain, query_stats, run_date=None)`
- `ingest_keyword_article(domain, article_keywords)`
- `ingest_keyword_event(domain, event_keywords)`
- `ingest_cascade_log(domain, log_data)`
- `ingest_coverage(domain, coverage_data)`

## Testing Notes

Use temporary SQLite files for tests. Do not rely on the user machine's configured DB path for unit tests.

`update_query_stats()` accepts both legacy `id/articles_found` records and the
Search subsystem's `query_id/results_count` records from `raw.stats.json`.
It writes a per-query daily ledger in `query_run_stats`, then recomputes
`queries.hit_count_7d`, `queries.hit_count_30d`, and `queries.avg_articles`
from that ledger when the columns exist. This prevents repeated Search runs,
historical backfills, and rolling-window expiration from drifting away from
the recorded daily facts.

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
verification fields.

Seeded queries include optional `dimension` and `include_domains` columns.
Existing databases are migrated additively by `connection.py`; helper functions
remain compatible with older minimal test tables that do not expose either
column. `include_domains` is stored as a JSON array so DB-backed Search can keep
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

`get_entity_events()` and `get_term_events()` read accumulated event rows across
date ranges. This is the retrieval path for questions such as "Samsung's
important storage events over the last six months" or "HBM progress across key
companies". `get_term_company_progress()` groups term-related events by
mentioned entity so storage today and robot later can use the same query shape.
Event timeline read helpers, including `get_thread_timeline()`, return parsed
Python lists for JSON-array fields (`article_ids`, `entity_ids`, `term_ids`,
`source_domains`) so callers do not have to special-case raw SQLite strings.

The schema still has `cascade_logs` because the persistence layer supports
multi-scale run accounting, but the old standalone `stratum/cascade.py` runtime
is not part of the current project shape.
