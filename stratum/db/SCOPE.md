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

`connection.py` reads project `config.yaml`:

- `db_dir` if present
- fallback: `~/WorkSpace/Stratum/DataBase`

DB file layout:

```text
{db_dir}/{domain}/{domain}.db
```

Search stage has one important exception: when CLI receives `--db`, it reads that explicit SQLite path directly for daily query selection.

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
- `update_entities_after_run(domain, entity_stats)`
- `update_query_stats(domain, query_stats, run_date=None)`
- `ingest_keyword_article(domain, article_keywords)`
- `ingest_keyword_event(domain, event_keywords)`
- `ingest_cascade_log(domain, log_data)`
- `ingest_coverage(domain, coverage_data)`

## Testing Notes

Use temporary SQLite files for tests. Do not rely on the user machine's configured DB path for unit tests.

`update_query_stats()` accepts both legacy `id/articles_found` records and the
Search subsystem's `query_id/results_count` records from `raw.stats.json`.

Seeded queries include an optional `dimension` column. Existing databases are
migrated additively by `connection.py`; helper functions remain compatible with
older minimal test tables that do not expose the column.

`ingest_entity_snapshots()` accepts per-run entity article counts from
`articles.jsonl`. When the orchestrator runs daily ingest, the same counts used
to update `entities.article_count_7d` are also written into
`entity_snapshots.article_count`.

`get_entity_events()` and `get_term_events()` read accumulated event rows across
date ranges. This is the retrieval path for questions such as "Samsung's
important storage events over the last six months" or "HBM progress across key
companies". `get_term_company_progress()` groups term-related events by
mentioned entity so storage today and robot later can use the same query shape.

The schema still has `cascade_logs` because the persistence layer supports
multi-scale run accounting, but the old standalone `stratum/cascade.py` runtime
is not part of the current project shape.
