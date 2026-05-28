# Multi-Scale Industry Intelligence Architecture

## 1. Purpose

This project should evolve from a daily news summarizer into a multi-scale industry intelligence system.

The system should not treat articles as the final unit of analysis. Articles are evidence. The real analysis units are:

```text
ArticleRecord
  -> StoryCluster
  -> EventThread
  -> TrendTheme
  -> QuarterlyThesis
  -> AnnualNarrative
```

The goal is to support:

```text
Daily Brief
Weekly Brief
Monthly Brief
Quarterly Review
Yearly Review
```

Each layer should preserve judgment continuity and make future reviews more accurate.

## 2. Core Principle

The system must move from:

```text
source/article-centered
```

to:

```text
story/event/judgment-centered
```

Meaning:

- Sources are evidence providers.
- Articles are evidence records.
- StoryClusters represent same-day developments.
- EventThreads represent continuing stories.
- TrendThemes represent monthly direction.
- QuarterlyTheses represent assumptions under review.
- AnnualNarratives represent structural industry change.

The final output should answer:

```text
What changed our judgment?
What was confirmed?
What was contradicted?
What is still unresolved?
What should we watch next?
```

Not merely:

```text
What articles were published today?
```

## 3. Existing Architecture

Current modules:

```text
stratum
  Main framework / orchestration spec

stratum-{channel}
  Domain/channel package, e.g. storage

locale-router
  Source language expansion and engine routing

source-manager
  Source URL health check and repair

verify-engine
  Deterministic validation: date, magnitude, fiscal year

source-graph-engine
  Entity / Term / Channel graph evolution

health-tracker
  Source hit-rate and long-term health stats

render-engine
  Markdown -> HTML/PDF rendering
```

Current domain package:

```text
skills/stratum-storage/
  SKILL.md
  data/domain.yaml
  references/
```

The existing architecture already separates:

```text
how to run        -> public framework modules
what to monitor   -> domain.yaml / channel package
how to judge      -> editorial standards
```

This separation should be preserved.

## 4. Target Intelligence Layers

### 4.1 Daily Brief

Core unit:

```text
StoryCluster + EventThread update
```

Daily answers:

```text
What happened today?
Which existing events changed?
Which new events are worth tracking?
Which signals are rehash/background?
```

Daily should output:

```text
articles.jsonl
story-clusters.json
event-updates.json
daily-brief.md
daily-tldr.json
```

### 4.2 Weekly Brief

Core unit:

```text
EventThread
```

Weekly answers:

```text
Which threads upgraded?
Which cooled down?
Which reversed?
Which new signals became real events?
What should be watched next week?
```

Weekly should not summarize raw articles. It should read:

```text
7 days of StoryClusters
active EventThreads
daily TLDRs
```

Weekly output:

```text
weekly-thread-summary.json
weekly-brief.md
weekly-tldr.json
```

### 4.3 Monthly Brief

Core unit:

```text
TrendTheme
```

Monthly answers:

```text
Which trends formed this month?
Which trends were confirmed?
Which were contradicted?
How did our industry judgment change?
```

Monthly input:

```text
weekly summaries
event-thread trajectories
source performance stats
source-graph changes
```

Monthly output:

```text
trend-themes.json
monthly-brief.md
monthly-tldr.json
```

### 4.4 Quarterly Review

Core unit:

```text
QuarterlyThesis
```

Quarterly answers:

```text
Which assumptions were strengthened?
Which were weakened?
Which were wrong?
Which signals did we miss?
Which signals were false positives?
```

Quarterly input:

```text
3 monthly trend summaries
major EventThreads
JudgmentLog
SourcePerformance
```

Quarterly output:

```text
theses.json
quarterly-review.md
thesis-outcomes.json
```

### 4.5 Yearly Review

Core unit:

```text
AnnualNarrative
```

Yearly answers:

```text
What was the industry's main narrative this year?
Which structural changes happened?
Which theses were validated or invalidated?
Which sources were most useful?
What should we watch next year?
```

Yearly input:

```text
4 quarterly reviews
annual source performance
judgment logs
major event trajectories
```

Yearly output:

```text
annual-narrative.json
yearly-review.md
source-review.json
model-review.json
```

## 5. Target Pipeline

### 5.1 Daily Pipeline

```text
config/domain load
  -> locale-router
  -> query-planner
  -> collection
  -> source-manager
  -> verify-engine
  -> article-normalizer
  -> story-cluster-engine
  -> event-thread-engine
  -> source-graph-engine update
  -> daily editorial assembly
  -> render-engine
  -> health-tracker / source-performance update
```

`story-cluster-engine` must run before editorial assembly. The editorial layer should receive StoryClusters and EventThread updates, not raw article lists.

### 5.2 Weekly Pipeline

```text
load last 7 daily artifacts
  -> summarize EventThread changes
  -> identify upgrades/cooling/reversals
  -> update thread priorities and watch signals
  -> generate weekly brief
```

### 5.3 Monthly Pipeline

```text
load weekly summaries
  -> inspect event-thread trajectories
  -> synthesize TrendThemes
  -> update monthly watchlist
  -> generate monthly brief
```

### 5.4 Quarterly Pipeline

```text
load monthly TrendThemes
  -> evaluate QuarterlyTheses
  -> record validated/weakened/failed assumptions
  -> record missed and false signals
  -> generate quarterly review
```

### 5.5 Yearly Pipeline

```text
load quarterly reviews
  -> synthesize AnnualNarrative
  -> evaluate source performance
  -> evaluate model/judgment quality
  -> generate yearly review
```

## 6. Core Data Objects

### 6.1 ArticleRecord

Represents one normalized article or item.

```yaml
ArticleRecord:
  id: string
  url: string
  canonical_url: string
  title: string
  source: string
  source_type: official | media | analyst | blog | social | financial | other
  source_locale: string
  published_at: string
  fetched_at: string
  snippet: string
  extracted_summary: string
  content_hash: string
  entities: [string]
  terms: [string]
  numeric_claims: [string]
  verification_status: verified | rejected | uncertain
  rejection_reason: duplicate | stale | no_date | low_relevance | rehash | other
  discovery_mode: baseline_seed | event_followup | gap_search | source_watch | exploratory
  cluster_id: string
  event_thread_id: string
```

### 6.2 StoryCluster

Represents a same-day story built from related articles.

```yaml
StoryCluster:
  id: string
  date: string
  title: string
  article_ids: [string]
  source_urls: [string]
  canonical_summary: string
  confirmed_claims: [string]
  disputed_claims: [string]
  repeated_claims: [string]
  new_claims: [string]
  novelty: first_disclosure | update | rehash | rumor | confirmation | contradiction
  confidence: A | B | C | D
  impact_tags: [price, customer, supply, technology, competitor, capital, policy]
  linked_entities: [string]
  linked_terms: [string]
  source_diversity: low | medium | high
  update_type: new_claim | confirmation | contradiction | quantification | second_order_signal | rehash | background
  linked_event_thread_id: string
```

### 6.3 EventThread

Represents a continuing story across days or weeks.

```yaml
EventThread:
  id: string
  channel: string
  title: string
  canonical_question: string
  first_seen: string
  last_seen: string
  status: emerging | active | cooling | resolved | archived
  priority: low | medium | high
  linked_entities: [string]
  linked_terms: [string]
  linked_clusters: [string]
  timeline:
    - date: string
      cluster_id: string
      update_type: string
      summary: string
      confidence_after: string
  current_assessment: string
  confidence: A | B | C | D
  confidence_history:
    - date: string
      confidence: string
      reason: string
  open_questions: [string]
  watch_signals: [string]
  search_controls:
    watch_queries: [string]
    followup_frequency: daily | every_2_days | weekly | none
    watch_until: string
  close_conditions: [string]
```

### 6.4 TrendTheme

Represents a monthly trend.

```yaml
TrendTheme:
  id: string
  month: string
  domain: string
  title: string
  linked_event_threads: [string]
  supporting_clusters: [string]
  opposing_clusters: [string]
  current_judgment: string
  judgment_change: string
  confidence: string
  confidence_delta: string
  evidence_for: [string]
  evidence_against: [string]
  risks_to_judgment: [string]
  next_month_watch: [string]
```

### 6.5 QuarterlyThesis

Represents a quarterly assumption under review.

```yaml
QuarterlyThesis:
  id: string
  quarter: string
  title: string
  starting_assumption: string
  linked_trend_themes: [string]
  linked_event_threads: [string]
  evidence_for: [string]
  evidence_against: [string]
  judgment_change: string
  confidence_start: string
  confidence_end: string
  outcome: strengthened | weakened | reversed | delayed | inconclusive
  missed_signals: [string]
  false_signals: [string]
  next_quarter_watch: [string]
```

### 6.6 AnnualNarrative

Represents the yearly structural review.

```yaml
AnnualNarrative:
  year: string
  domain: string
  dominant_themes: [string]
  regime_changes: [string]
  turning_points:
    - date: string
      event_thread_id: string
      why_it_mattered: string
  failed_signals: [string]
  validated_theses: [string]
  invalidated_theses: [string]
  source_review: object
  model_review: object
  next_year_questions: [string]
```

## 7. Storage Architecture

Recommended runtime layout:

```text
~/WorkSpace/Stratum/{channel}/
  daily/
    2026-05-28/
      raw-search.jsonl.gz
      rejected.jsonl.gz
      articles.jsonl
      story-clusters.json
      event-updates.json
      daily-brief.md
      daily-tldr.json

  event-threads/
    active/
      hbm4-supply-tightness.json
    archived/
      2026-Q2.jsonl

  weekly/
    2026-W22/
      weekly-thread-summary.json
      weekly-brief.md
      weekly-tldr.json

  monthly/
    2026-05/
      trend-themes.json
      monthly-brief.md
      monthly-tldr.json

  quarterly/
    2026-Q2/
      theses.json
      thesis-outcomes.json
      quarterly-review.md

  yearly/
    2026/
      annual-narrative.json
      source-review.json
      model-review.json
      yearly-review.md

  indexes/
    article-index.sqlite
    judgment-log.ndjson
    source-performance.json
```

Recommended storage formats:

```text
JSONL     append-only evidence records
JSON      current state objects
SQLite    searchable index
Markdown  human-readable outputs
gzip      raw/rejected temporary data
```

## 8. Retention Policy

```yaml
retention:
  raw_search:
    keep_days: 7
    compress: true

  rejected_candidates:
    keep_days: 30
    compress: true

  article_records:
    keep_days: 180
    keep_high_value_forever: true

  story_clusters:
    keep_days: 365

  event_threads:
    keep_days: 730
    keep_final_state_forever: true

  trend_themes:
    keep_forever: true

  quarterly_theses:
    keep_forever: true

  annual_narratives:
    keep_forever: true

  judgment_log:
    keep_forever: true

  source_performance:
    keep_forever: true
```

The system should not rely on long-term raw search storage.

Long-term value comes from:

```text
evidence index
story clusters
event state
judgment changes
source performance
missed/false signals
```

## 9. Search Bias Control

Historical memory must not dominate daily search.

Daily search should balance:

```text
explore: discover new events
exploit: follow existing EventThreads
```

Recommended daily search budget:

```yaml
daily_search_budget:
  baseline_seed_queries: 35
  active_thread_followup: 30
  gap_searches: 20
  exploratory_sources: 15
```

EventThread follow-up queries must pass through `query-planner`.

Query planner controls:

```yaml
query_planner_limits:
  max_total_queries: 80
  max_thread_followup_queries: 25
  max_queries_per_event_thread: 3
  max_same_entity_queries: 8
  min_baseline_query_ratio: 0.35
  min_gap_query_ratio: 0.15
  max_event_followup_ratio: 0.35
  disable_followup_after_no_material_update_days: 7
  archive_after_no_material_update_days: 14
```

Generated queries should have expiry:

```yaml
GeneratedQuery:
  query: string
  source: event_thread | source_graph | gap_search | seed
  event_thread_id: string
  created_at: string
  expires_at: string
  last_used_at: string
  hit_rate_7d: float
  rehash_rate_7d: float
```

Every ArticleRecord should store `discovery_mode`.

This allows later analysis:

```text
Are we finding enough new events?
Are old EventThreads consuming too much search budget?
Are gap searches finding important missed stories?
Are event follow-up queries producing too many rehashes?
```

## 10. Relationship To Existing Modules

### 10.1 stratum

Modify from daily-only orchestration into multi-period orchestration.

Needs to define:

```text
daily run
weekly run
monthly run
quarterly review run
yearly review run
```

Each run should specify:

```text
inputs
outputs
artifact paths
failure behavior
```

### 10.2 locale-router

Keep as public module.

Current role:

```text
source_languages -> locales -> engines
```

Updated role:

```text
produce locale-aware query candidates for query-planner
```

It should not decide final search budget.

### 10.3 source-manager

Keep as public module.

It validates and repairs source URLs.

Future integration:

```text
source-manager results feed SourcePerformance
```

### 10.4 verify-engine

Keep as public module.

It verifies:

```text
publish date
numbers
fiscal/calendar year
staleness
source reliability signals
```

It should run before article-normalizer/story-cluster-engine.

### 10.5 source-graph-engine

Keep focused on:

```text
Entity
Term
Channel
Edges between them
```

Do not put story clustering inside source-graph-engine.

Future integration:

```text
source-graph-engine -> known entities/terms for clustering
story-cluster-engine -> high-signal cluster edges back to source graph
```

### 10.6 health-tracker

Current role:

```text
source hit-rate / dry streak
```

Extend into source performance.

Additional metrics:

```text
selected_count
rehash_count
false_positive_count
correction_count
leading_signal_count
average_lead_time_days
reliability_by_topic
```

### 10.7 render-engine

Keep as rendering module.

Extend template support for:

```text
daily brief
weekly brief
monthly brief
quarterly review
yearly review
```

Rendering should remain downstream of structured artifacts.

### 10.8 stratum-{channel} / domain.yaml

Domain package remains source of domain-specific knowledge.

Add optional controls:

```yaml
discovery_budget_defaults:
  baseline_seed_queries: 35
  active_thread_followup: 30
  gap_searches: 20
  exploratory_sources: 15

event_thread_admission_rules:
  min_confidence: C
  min_impact_score: 0.4
  allow_single_source_if:
    - official_source
    - high_reliability_source
    - first_disclosure
    - material_financial_or_supply_signal

trend_theme_candidates:
  - hbm-capacity-lock-in
  - nand-pricing-recovery
  - china-storage-localization

quarterly_thesis_candidates:
  - title: "HBM pricing power remains structurally strong"
    linked_terms: [hbm, hbm4, advanced-packaging]
```

## 11. New Modules To Add

### 11.1 query-planner

Responsibilities:

```text
merge seed queries, gap searches, source watchlists, event follow-up queries
apply query budget
dedupe similar queries
expire stale generated queries
prevent old EventThreads from dominating search
emit final query plan
```

Input:

```text
locale-router output
domain.yaml seed/gap queries
active EventThreads
source-graph auto query candidates
query performance history
```

Output:

```text
query-plan.json
```

### 11.2 article-normalizer

Responsibilities:

```text
canonical URL
content hash
metadata extraction
entity/term extraction
ArticleRecord creation
rejected candidate recording
```

Output:

```text
articles.jsonl
rejected.jsonl.gz
```

### 11.3 story-cluster-engine

Responsibilities:

```text
deduplicate articles
cluster same-day related articles
separate confirmed/disputed/repeated/new claims
score novelty/confidence/impact
emit StoryCluster records
```

V1 approach:

```text
URL canonicalization
title similarity
entity/term overlap
optional embedding cosine similarity
LLM cluster review
```

Do not require UMAP/HDBSCAN in v1.

### 11.4 event-thread-engine

Responsibilities:

```text
match StoryCluster to existing EventThread
create new EventThread when needed
update timeline
update current_assessment
update confidence
update open_questions/watch_signals
manage lifecycle: emerging/active/cooling/resolved/archived
```

### 11.5 periodic-brief-engine

Responsibilities:

```text
weekly synthesis
monthly trend synthesis
quarterly thesis review
yearly narrative review
```

Can later split into:

```text
weekly-brief-engine
monthly-brief-engine
review-engine
```

### 11.6 judgment-log

Responsibilities:

```text
record assessment changes
record confidence before/after
record reason_for_change
link evidence ids
support quarterly/yearly review
```

Format:

```text
judgment-log.ndjson
```

### 11.7 source-performance-engine

Responsibilities:

```text
analyze source quality by topic
track rehash/false positive/leading signal behavior
feed source reliability back into scoring
produce yearly source review
```

### 11.8 artifact-store

Responsibilities:

```text
standardize JSON/JSONL/Markdown/SQLite read/write
manage retention policy
manage indexes
provide artifact lookup by channel/date/period
```

## 12. SQLite Index

Use filesystem for canonical artifacts.

Use SQLite for query and analysis.

Suggested tables:

```sql
articles(
  id,
  date,
  channel,
  source,
  url,
  canonical_url,
  title,
  published_at,
  cluster_id,
  event_thread_id,
  content_hash,
  discovery_mode,
  verification_status
);

clusters(
  id,
  date,
  channel,
  title,
  novelty,
  confidence,
  source_diversity,
  linked_event_thread_id
);

event_threads(
  id,
  channel,
  title,
  status,
  priority,
  first_seen,
  last_seen,
  confidence
);

thread_updates(
  id,
  thread_id,
  date,
  cluster_id,
  update_type,
  confidence_before,
  confidence_after
);

sources(
  id,
  name,
  type,
  reliability,
  total_hits,
  selected_count,
  rehash_count,
  false_positive_count,
  leading_signal_count
);

judgment_log(
  id,
  date,
  object_type,
  object_id,
  previous_assessment,
  new_assessment,
  reason_for_change,
  confidence_before,
  confidence_after
);
```

## 13. Implementation Priority

### P0: Make Existing System Executable

```text
orchestrator entry point
locale-router executable
runtime/source separation
basic artifact store
```

### P1: Daily Story/Event Layer

```text
ArticleRecord
article-normalizer
story-cluster-engine
event-thread-engine
query-planner
daily artifacts
```

### P2: Weekly/Monthly Layer

```text
weekly-thread-summary
monthly TrendTheme
source-performance initial version
judgment-log initial version
```

### P3: Quarterly/Yearly Layer

```text
QuarterlyThesis
AnnualNarrative
source/model review
long-term retention
```

### P4: Advanced Clustering

Evaluate only after article volume justifies it:

```text
multilingual embeddings
UMAP
HDBSCAN
LLM cluster review
```

UMAP/HDBSCAN output should be candidate clustering only, never final truth.

## 14. Final Architecture Summary

The system should become:

```text
Daily:
  turn news into events

Weekly:
  turn events into thread-level judgment

Monthly:
  turn thread trajectories into trends

Quarterly:
  validate or revise industry theses

Yearly:
  synthesize structural change and system lessons
```

The most important long-term data is not raw search data.

The most important long-term data is:

```text
evidence index
story clusters
event states
judgment changes
source performance
missed signals
false signals
```

This is what allows future briefs and reviews to be accurate, continuous, and valuable.

