# event-thread - event lifecycle and cross-temporal linking

## Purpose

`stratum/subsystems/event-thread` provides deterministic event-thread mechanics: lifecycle status, cluster-to-thread matching, watch query generation, archive rules, and cross-scale linking.

It is a computational subsystem. Long-lived persistence currently belongs to `stratum/db`.

## Modules

| File | Role |
|:---|:---|
| `event_thread.py` | daily thread lifecycle, matching, updates, watch queries |
| `cross_temporal.py` | daily/weekly/monthly/quarterly/yearly appearance registration and rollup tracing |
| `__init__.py` | package marker |

## Boundaries

### 做什么

- Define `EventThread` and timeline entry dataclasses for deterministic operations.
- Compute lifecycle: `emerging -> active -> cooling -> resolved -> archived`.
- Match new clusters to existing event threads by watch signals and entity overlap.
- Generate watch queries from emerging, active, and cooling threads.
- Register appearances across time scales.
- Roll up lower-scale threads into higher-scale parent threads.
- Trace a thread's scale chain.

### 不做什么

- Does not call LLMs.
- Does not own SQLite persistence.
- Does not validate briefing claims.
- Does not extract entities/terms from articles.
- Does not define domain-specific taxonomy.

## Data Contracts

Cross-temporal contracts live in `stratum/contracts/event_thread.py` and are re-exported by `stratum.contracts`.

Daily thread mechanics use local dataclasses in `event_thread.py` because they are implementation details of this subsystem.

## Lifecycle and Matching Notes

- A newly created thread stays `emerging` on its first disclosure day. A later
  confirmation/update makes it `active`.
- Lifecycle status is computed from timeline entries visible at the target
  `run_date`; future timeline entries are ignored for historical backfills, and
  timeline entries are sorted by date before choosing the latest observed
  update.
- `add_update()` keeps `last_updated`, lifecycle `status`, current
  `confidence`, and `confidence_history` aligned with the new timeline entry.
- `cooling` threads still generate watch queries, because they need explicit
  follow-up before becoming resolved.
- Search DB query loading must preserve the same lifecycle policy:
  thread-bound queries for `emerging`, `active`, and `cooling` threads are
  eligible for daily Search; resolved/archived/dormant threads are not.
- Cluster matching ignores `resolved` and `archived` threads; inactive stories
  should not be accidentally revived by lexical overlap.
- Cluster matching uses watch signals first, but also falls back to stable
  thread descriptors such as title, canonical question, open/close conditions,
  and timeline summaries. This keeps threads matchable when upstream structured
  output omitted explicit watch signals.
- Watch query generation prioritizes high-priority threads before medium/low
  threads when the daily query cap is reached. Within the same priority, more
  recently updated threads win the cap, because they are usually the stories
  most likely to produce fresh follow-up Search results.
- Watch query generation accepts a locale list for domain-aware follow-up and
  deduplicates repeated `query + locale` pairs before they consume the daily cap.
- If a still-active thread has no explicit watch signals, watch-query
  generation falls back to the canonical question or title rather than dropping
  the story from next-run Search entirely.
- The daily orchestrator persists generated watch queries into SQLite as
  thread-bound `verification` queries with `dimension = thread_watch`, using
  the configured source locales. This keeps Event Thread follow-up connected to
  the next Search run without making this subsystem own persistence.
- Automatic thread creation respects `MAX_THREADS` so a noisy day cannot grow
  the active thread set without bound.
- New thread IDs are allocated from the highest existing `et-{domain}-NNNN`
  suffix plus one, not from `len(threads)`, so sparse/deleted histories do not
  collide with existing story identities.

## Cross-Temporal Notes

- `CrossTemporalLink.add_appearance()` is idempotent by `scale + briefing_id`.
  Re-running the same briefing replaces that appearance instead of appending a
  duplicate, so traces and scale summaries remain stable under reruns.
- Cross-scale traces follow `merged_into` parent links upward and report which
  expected higher scales are still missing from the chain.

## Dependencies

- `stratum/contracts/event_thread.py`
- Stage 5 cluster output shape
- Story-tracking context generation may consume compatible thread/event data from SQLite.

## Testing

- `test_event_thread.py` covers lifecycle, matching, creation/update, watch query generation, and evolution.
- `test_cross_temporal.py` covers appearance registration, rollup, trace, resolution, and summaries.
