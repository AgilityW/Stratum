# monitoring - health and coverage checks

## Purpose

`stratum/subsystems/monitoring` is the deterministic health layer. It tracks source activity, dry streaks, contributor concentration, HTTP errors, and coverage gaps in produced clusters.

## Modules

| File | Role |
|:---|:---|
| `health.py` | daily source records, aggregate stats, source alerts, dry sources, contributors |
| `coverage.py` | coverage gap detection and follow-up query generation |
| `__init__.py` | package marker |

## Boundaries

### Owns

- Write and load daily source-health records.
- Rebuild source stats from records.
- Detect dry sources and top contributors.
- Emit threshold-based source-health alerts.
- Aggregate search engine health from per-query attempt chains.
- Detect missing source-type/locale coverage in story clusters.
- Generate follow-up queries from detected gaps.

### Does Not Own

- Does not fetch sources. Watchlist owns fetching.
- Does not maintain source lifecycle state.
- Does not call search APIs directly.
- Does not decide editorial inclusion.

## Data Contracts

### Health Records

`health.py` writes NDJSON-style daily records with source id, domain/channel,
date, record counts, signal metrics, optional HTTP error fields, duration,
error text, and metadata.

Watchlist runs feed this contract through the orchestrator:

- sidecar: `{reports_dir}/{domain}/data/{date}/watchlist_stats.json`
- health append: `{health_data_dir}/{domain}/source-daily.ndjson`

Watchlist sidecars accept source statuses `ok`, `empty`, `error`, and
`unsupported`. Unsupported watchlist access methods use `access: unknown` in
the stable sidecar/health contract while the error message preserves the
configured access string.
For watchlist records, `hits` is acquisition output and `selected` is the
post-merge contribution that survived canonical URL dedupe into `raw.json`.
`unsupported` is an infrastructure/configuration capability signal, not a
source-quality scan. The orchestrator writes those records with `scanned: false`
and `metadata.status: unsupported`; `rebuild_stats()` also recognizes historical
unsupported records from tags or metadata and excludes them from scan, dry
streak, selected dry streak, and HTTP-error counters while preserving
first/last-seen observability.

`rebuild_stats()` groups records by source and sorts each source's records by
date before computing `dry_streak`, `selected_dry_streak`, `first_seen`, and `last_seen`. This keeps
health stats stable when historical records are backfilled, merged, or replayed
out of append order.
Because source health is a daily signal, repeated appends for the same
`source`/`date` are collapsed to the latest record before aggregation. This
keeps reruns from inflating `total_scans` or turning multiple same-day misses
into a false multi-day dry streak.
Records with `scanned: false` are retained for first/last-seen observability,
but they do not increment `total_scans`, `dry_streak`, `selected_dry_streak`,
or HTTP error counters. A deliberately skipped source should not look like a
failed source.
`dry_streak` tracks acquisition droughts (`hits == 0`), while
`selected_dry_streak` tracks contribution droughts (`selected == 0`). The
second signal matters for watchlist because a source can keep producing
duplicate candidates that never survive canonical URL merge into `raw.json`.
When watchlist records include `metadata.dated`, `rebuild_stats()` also
computes `total_dated`, `dated_hits_observed`, and `dated_rate` as dated hits
divided by hits from records that actually reported dated metadata. Historical
records without dated metadata do not receive a synthetic zero dated rate, so
old health logs do not become false quality alerts.

`get_source_alerts()` turns aggregate source stats into deterministic alerts
for acquisition droughts, selected-record droughts, HTTP error counts, and low
dated metadata coverage. Thresholds are caller-configurable so daily domains
can run stricter policies than exploratory domains without changing the record
contract.
HTTP error alerts use `http_error_streak`, the current consecutive scanned-day
error run, rather than the lifetime `http_errors` counter. The lifetime counter
remains available for historical source reliability review, while alerting
stays focused on sources that are broken now.

`engine_health.py` owns `EngineHealthScorer`, the algorithm that turns
`raw.stats.json` query-level `engine_attempts` into per-engine attempt counts,
failure rates, health scores, and routing recommendations (`healthy`, `watch`,
`deprioritize`, `avoid`). `coverage.py` re-exports
`score_search_engine_health()` for compatibility and Search diagnostics, but
monitoring orchestration should not grow engine-health policy logic directly.
`provider_exhausted` attempts are scored as hard failures with an `avoid`
recommendation because quota, billing, and authorization errors are not useful
retry targets within the same run.

### Coverage

`coverage.py` consumes:

- clusters from Stage 5
- source records or article-like records
- cluster-level `source_types`, `locales`, and `source_domains` as a fallback
  when detailed source records are unavailable

It emits gap dictionaries with severity, missing source type/locale coverage,
cluster `entities`/`terms`, and generated follow-up query candidates. Entity
context is required for useful official-source follow-up queries.
Coverage normalizes source type and locale labels before comparison. Missing
locale metadata is treated as unknown, not as English coverage, so incomplete
source records do not hide real locale gaps.

Severity uses current StoryCluster confidence labels (`high`, `medium`, `low`)
and still accepts historical `A/B/C/D` fixture labels. Low-confidence clusters
with two or fewer watchlist domains are high severity when they miss ideal
source type or core locale coverage.

## Dependencies

- Pipeline output records
- Stage 5 clusters
- Domain/source identifiers

## Testing

`test_monitoring.py` covers the health tracker and coverage monitor pure functions.
