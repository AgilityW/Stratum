# Database Architecture Spec

This spec is governed by the baseline stability rule in
`docs/ENGINEERING_RULES.md`: database architecture changes must not break the
currently working baseline while a future version is being developed.

## Purpose

Stratum's database is the long-lived memory layer for a multi-scale industry
briefing system. Its primary role is not to store rendered reports. Its primary
role is to preserve structured evidence, events, stories, judgments, causal
links, and period snapshots so higher-scale reports can consume lower-scale
work.

The target reporting cascade is:

```text
daily -> weekly -> monthly -> quarterly -> yearly
```

Each scale produces a report, writes structured outputs back to the database,
and becomes part of the input context for higher scales.

## Core Requirement

For any reporting period, the database must support reconstructing the
structured basis of the report:

- which events were active in the period
- which stories or threads those events belonged to
- which entities and terms were involved
- which judgments and causal links were produced or verified
- which report sections and items used those events
- which evidence articles support the events and report items

Rendered Markdown, HTML, and PDF files remain artifacts. The database stores the
queryable structure needed to trace, aggregate, and regenerate the reasoning
behind those artifacts.

## Conceptual Model

### Evidence Layer

The evidence layer is the lowest-level factual substrate. It anchors claims to
search, watchlist, and verification outputs.

It should include lightweight metadata and references:

- article id
- title
- URL
- source
- published date
- locale
- snippet or summary
- source artifact path or hash
- run date and domain

It should not store unbounded raw payloads by default:

- full raw search responses
- full HTML pages
- screenshots
- PDFs
- large LLM traces

Those heavy artifacts should remain on the filesystem, with paths or hashes
recorded in the database when needed.

Current pipeline correspondence:

```text
raw.json -> verified.jsonl -> articles.jsonl
```

`articles.jsonl` is the current normalized article surface closest to the
database's article concept. Articles are evidence units, not report items.

### Event Store Layer

The event store is the main continuity layer. It turns daily evidence into
structured units that can survive across days and scales.

Core objects:

- `threads`: cross-period story containers
- `events`: period-specific facts or developments inside a thread
- `thread_entities`: entity links for each thread
- `causal_edges`: causal relationships between threads
- `judgments`: testable hypotheses and later verification outcomes

Daily reports create or update events and threads. Weekly and higher reports
consume those events and may create higher-scale events, causal links, and
judgments.

### Report Layer

Reports must become structured database objects, not only Markdown files.

Target objects:

- `reports`: one report per domain, scale, and period
- `report_sections`: ordered section keys such as `today`, `industry`,
  `signals`, `focus`, and `contrarian`
- `report_items`: ordered item-level claims or narratives inside sections
- `report_item_events`: links from report items to events
- `report_item_articles`: links from report items to supporting evidence

This layer lets the system answer:

- What did the report say?
- Which event or story produced this item?
- Which article evidence supports this item?
- How did the same story evolve across daily, weekly, monthly, quarterly, and
  yearly reports?

### Aggregation Layer

The aggregation layer supports trend detection and higher-scale synthesis.

Core objects:

- `entity_snapshots`: entity state and article counts per scale and period
- `coverage`: covered threads, missed threads, stale entities, missing
  dimensions, and source contribution
- `cascade_logs`: accounting for multi-scale runs
- query effectiveness records such as `query_run_stats`

This layer helps higher-scale reports distinguish persistent trends from
one-day noise.

### Consumption And Management Layer

The database must expose a dedicated consumption and management layer. This
layer is the public interface for using the database after pipeline ingestion.
Downstream consumers should not scatter ad hoc SQL across report generation,
dashboards, agents, or analysis tools.

Target responsibilities:

- track one story or event thread across time
- retrieve a company's important events over a date range
- retrieve a technology's progress across companies and periods
- retrieve judgments that are due for verification
- retrieve causal links and their supporting events
- retrieve report items by domain, scale, period, section, entity, or thread
- retrieve evidence articles behind an event or report item
- provide rollups for weekly, monthly, quarterly, and yearly report inputs

Example query surfaces:

- `get_report_context(domain, scale, period)`
- `get_thread_timeline(domain, thread_id, start_period, end_period)`
- `get_entity_timeline(domain, entity_id, scale, start_period, end_period)`
- `get_technology_progress(domain, term_id, entity_ids, start_period, end_period)`
- `get_due_judgments(domain, scale, period)`
- `get_report_item_evidence(domain, report_item_id)`
- `get_cascade_inputs(domain, target_scale, target_period)`
- `get_cascade_inputs(domain, target_scale, window_start, window_end)`

This layer should own period logic, joins, lineage traversal, and JSON field
normalization. Report generators and agents consume typed records from this
layer instead of depending on table details.

## Scale Contract

Every structured object produced by a report scale must be period-addressable.

Required identifiers:

- `domain`: reporting domain, such as `storage`
- `scale`: `daily`, `weekly`, `monthly`, `quarterly`, or `yearly`
- `period`: normalized period id, such as `2026-05-30`, `2026-W22`,
  `2026-05`, `2026-Q2`, `2026`, or
  `custom-2026-05-01_to_2026-07-31`
- `report_id`: stable id for a generated report

Report scale and date window are separate concepts. The scale selects the
report profile and template, while the window selects the database records to
consume. A user can therefore request a monthly-style report over several
months without pretending the period is a natural month. In the current
foundation schema, custom windows are encoded in the stable `period` id and
exposed by service/runtime as `report_window`; future schema migrations may add
dedicated `window_start` and `window_end` columns if query pressure justifies it.

For higher-scale outputs, records should also preserve lineage:

- `source_scales`
- `source_periods`
- `source_report_ids`
- source event ids
- source thread ids
- source article ids when evidence-level traceability is needed

## Migration Contract

Production database migrations must be explicit, versioned, and reversible.
Opening a database through normal runtime paths must not silently perform a
large or destructive migration.

Required migration properties:

- inspect the production database before migrating
- take a consistent backup before every production migration
- record applied migrations in a migration ledger
- prefer additive, nullable schema changes while a baseline version is still
  active
- keep old read/write paths working until the new baseline is promoted
- run migrations against a copied production database before touching
  production
- document rollback: restore backup, or keep dual-read compatibility until
  rollback is no longer needed

Current implementation:

- `stratum/db/migration.py` provides read-only inspection, explicit migration
  ledger helpers, checksum support, and consistent SQLite backups.
- `stratum/db/migrations/000010_foundation.sql` defines the first additive
  DB foundation 0.1 migration for report, evidence, and lineage tables.
- The migration framework is not automatically invoked by `get_db()`. This is
  deliberate: baseline runtime behavior remains unchanged until a migration run
  explicitly opts in.

## Cascade Semantics

### Daily

Daily runs consume fresh search and watchlist outputs. They produce:

- normalized articles
- event and thread updates
- daily judgments
- daily causal edges
- daily entity snapshots
- a daily report

Daily records are the base layer for all higher-scale aggregation.

### Weekly

Weekly runs consume:

- the previous seven days of daily reports
- daily events, threads, judgments, causal edges, and entity snapshots
- fresh weekly explore search outputs

Weekly reports should not be a concatenation of daily reports. They should
identify:

- persistent stories
- stories that became more important
- stories that cooled down
- weak signals that became material
- judgments that were supported, challenged, or still pending
- new weekly-level causal relationships

### Monthly, Quarterly, Yearly

Higher scales follow the same pattern. They consume all lower-scale database
state in the covered period plus fresh explore results for their own scale,
then write their own higher-scale structured outputs.

Higher-scale synthesis is not a fixed weighted merge. Each candidate theme must
go through a scale-independent integration policy:

- assess lower-scale database memory: event count, date spread, source lineage,
  judgment history, and whether the theme is persistent or still a single point
- assess same-scale fresh evidence: relevance, source quality, recency,
  independence, incrementality, and direction
- decide the role of fresh evidence: confirm the baseline, supplement it,
  lead a watch item, challenge it, or remain insufficient/noise
- apply the decision to confidence movement, report placement, and next
  validation points

This policy is shared by weekly, monthly, quarterly, and yearly reports. It is
implemented as an encapsulated policy object with tunable thresholds and a
single evaluation entry point. Weekly, monthly, quarterly, and yearly profiles
use different threshold configurations through the same policy object, so future
algorithmic work can add source scoring, directionality, conflict detection,
weighting, or scale-specific calibration without scattering decision logic
through report assembly code. The display structure can vary by scale, but the
decision layer should not fork into separate ad hoc algorithms.

The expected direction is:

```text
weekly = daily state + weekly fresh explore
monthly = daily state + weekly synthesis + monthly fresh explore
quarterly = daily state + weekly synthesis + monthly synthesis + quarterly fresh explore
yearly = daily state + weekly synthesis + monthly synthesis + quarterly synthesis + yearly fresh explore
```

Higher-scale reports should produce trend, judgment, and causal structure that
can be traced back to lower-scale evidence.

## Cascade Test Database Contract

The cascade test database is a replayable history system, not a static bag of
rows. It must validate the same dependency order the product relies on:

```text
persist daily history
-> synthesize and persist weekly
-> synthesize and persist monthly
-> synthesize and persist quarterly
-> synthesize and persist yearly
```

Each step uses the same temporary SQLite database. Higher-scale tests must not
hand-write their final weekly/monthly/quarterly/yearly reports as isolated
fixtures. They should first persist lower-scale output, then call the same DB
consumption and synthesis APIs used by runtime code.

The test database builder must manage these layers explicitly:

- daily evidence articles, events, judgments, causal edges, entity snapshots,
  and daily structured reports
- same-scale fresh explore evidence stored as article metadata with
  `scale = weekly|monthly|quarterly|yearly`
- generated higher-scale reports written back through `upsert_report_bundle`
- synthesized higher-scale events written back to the event store
- report lineage linking higher-scale items to source reports, events, threads,
  and evidence articles

The required cascade input contract is:

- weekly consumes daily reports/events/judgments in the target week plus weekly
  fresh evidence
- monthly consumes daily and weekly state in the target month plus monthly
  fresh evidence
- quarterly consumes daily, weekly, and monthly state in the target quarter plus
  quarterly fresh evidence
- yearly consumes daily, weekly, monthly, and quarterly state in the target year
  plus yearly fresh evidence

Each scale then applies the same synthesis policy to decide whether lower-scale
state or same-scale fresh evidence should dominate a theme. For example, a
monthly report can let weekly synthesis dominate when the theme has persistent
multi-week continuity, while monthly fresh evidence can confirm, challenge, or
promote an otherwise weak signal to a watch item. Quarterly and yearly reports
use the same policy with longer validation windows and stronger thresholds for
claiming structural change.

This makes the test database a small controlled history. It can prove that a
future weekly/monthly/quarterly/yearly implementation is reading the correct
lower-scale records, preserving lineage, and writing its own output back for the
next scale to consume.

Current implementation:

- `stratum/db/cascade_fixture.py` builds the replayable fixture.
- `stratum/db/synthesis/` performs each higher-scale synthesis step.
- `tests/test_cascade.py` asserts the staged input counts, source-scale
  ordering, fresh evidence inclusion, trend summaries, judgment status, evidence
  links, and yearly lineage.

## Implementation Checkpoints

The current DB foundation 0.1 is intentionally additive:

- runtime connections still initialize from `stratum/db/schema.sql`.
- foundation report/evidence/lineage tables are created only through the explicit
  migration helper.
- Structured writes live in `stratum/db/persistence.py` and are opt-in.
- The daily orchestrator calls the structured write layer only after detecting
  that the explicit DB foundation 0.1 tables and article columns already exist.
  Unmigrated databases continue through the legacy ingest path.
- Semantic reads live in `stratum/db/service.py` and degrade to empty report
  structures when a database has not been migrated.
- The cascade test fixture builds
  `articles -> daily events/report items -> weekly synthesis -> monthly
  synthesis -> quarterly/yearly synthesis` on a temporary migrated database so
  daily-to-yearly behavior can be validated without production data.
- `stratum/db/cascade_fixture.py` exposes that fixture as a reusable
  development utility, including an analysis snapshot for key events, trends,
  key timelines, judgment status, technology progress, report-item evidence,
  and lineage.
- `python -m stratum.db.manage` exposes explicit management commands for
  inspection, backup, applying the foundation migration, building the cascade
  fixture, analyzing an existing fixture, and synthesizing a higher-scale
  report from DB inputs.
- `stratum/db/synthesis/engine.py` is the deterministic DB-native synthesis engine. It
  consumes all lower-scale reports, events, and judgments plus same-scale fresh
  evidence already written to `articles`; writes the target scale's structured
  report; creates synthesized scale-level events for top threads; and records
  lineage to source reports, events, threads, and evidence. Structured payload
  assembly lives in `stratum/db/synthesis/payload.py`; report-facing wording,
  section labels, and language filtering live in `stratum/db/synthesis/text.py`
  so orchestration does not own payload shape or expression policy.
- `stratum/temporal/profiles.py` defines the shared timescale stage contracts.
- `stratum/temporal/timescale.py` is the deterministic DB-native higher-scale
  runtime used by the orchestrator.
- The orchestrator supports `--timescale weekly|monthly|quarterly|yearly` as
  output runs. These runs delegate to `stratum/temporal`, write Markdown under
  `{reports_dir}/{domain}/data/{timescale}/{period}/`, render HTML/PDF with
  `{Domain}_{Timescale}_Briefing_{period}` filenames, and write a run manifest.

## Article Storage Policy

Articles should be stored as lightweight evidence indexes, not as unlimited raw
content.

Store in the database:

- canonical id
- title
- URL
- source
- date
- locale
- snippet or short summary
- entity and term links
- source artifact path
- content hash where useful

Keep on the filesystem:

- `raw.json`
- `verified.jsonl`
- `articles.jsonl`
- extracted full text
- HTML/PDF/Markdown artifacts
- edit traces and LLM prompts

This keeps SQLite small and queryable while preserving auditability through
artifact paths and hashes.

## Current Implementation Status

The current working baseline already provides part of the event store and
aggregation layers:

- seeded `sources`, `entities`, `terms`, `keywords`, and `queries`
- `query_run_stats` and query rollups
- `threads`, `events`, `thread_entities`
- `causal_edges`
- `judgments`
- `entity_snapshots`

Additional DB foundation 0.1 work now exists behind an explicit migration:

- `articles.jsonl` can be persisted as lightweight article metadata.
- daily reports can be persisted as `reports`, `report_sections`, and
  `report_items`.
- daily report items can be linked to events, threads, and evidence articles.
- event-to-article links can be normalized through `event_articles`.
- run artifacts can be indexed through `report_artifacts`.
- cascade and analysis service APIs can read migrated test databases across
  daily, weekly, monthly, quarterly, and yearly fixtures.

Remaining gaps relative to this spec:

- Production scheduling outside the CLI still needs an explicit operational
  policy. The orchestrator CLI supports `--timescale
  weekly|monthly|quarterly|yearly`, and the DB-native temporal runner runs same-scale
  exploring before synthesis.
- production has not been migrated to the DB foundation 0.1.
- Coverage and source profile tables exist but are not fully connected to the
  production daily pipeline.
- Higher-scale lineage is supported by the foundation schema, cascade fixture,
  and DB-native synthesis path; production lineage depends on running against a
  migrated production DB.

## Non-Goals

The database must not replace the artifact store. It should not become a blob
archive for every raw response, rendered file, or prompt trace.

The database must not call search APIs, watchlist, renderers, or LLMs. It owns
persistence contracts and retrieval surfaces only.

The database must not depend on a single report scale. Daily, weekly, monthly,
quarterly, and yearly reports should share the same structural concepts while
using scale-specific templates and aggregation rules.

## Design Principle

The database should make the following trace possible:

```text
yearly judgment
  -> quarterly synthesis
  -> monthly story
  -> weekly thread
  -> daily event
  -> article evidence
  -> source artifact
```

This trace is the reason the database exists.
