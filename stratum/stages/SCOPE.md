# stages — daily briefing pipeline

## Purpose

`stratum/stages` contains the executable production chain that turns acquired
evidence into a rendered briefing.

The orchestrator runs these stages in order:

1. watchlist acquisition, via `stratum.sourcing.watchlist`
2. `acquisition`
3. `enrich`
4. `verify`
5. `normalize`
6. `cluster`
7. `edit`
8. `validate`
9. `repair`
10. `validate_recheck`
11. `render`

Watchlist remains a sidecar seed before the acquisition stage script. The
numbered daily chain now includes explicit repair and revalidation after the
first validate pass.

## Stage Contracts

Each stage boundary is a contract: the producing stage owns the structured data
it emits, the artifact name, and the record shape. The consuming stage must
depend on that documented data shape instead of private implementation details.
The carrier can be JSON, JSONL, Markdown, a sidecar file, or later a DB-backed
service record. Shared shapes may live in `stratum/contracts`; stage-local
sidecars are documented here.

| Stage | Determinism | Primary input | Primary output | Responsibility |
|:---|:---|:---|:---|:---|
| watchlist sidecar | network-dependent | `domain.yaml` source registry | seeded `raw.json` | Fetch configured RSS/browser/direct sources first. |
| `acquisition` | external APIs | `config.yaml` plus DB queries or `queries.yaml` plus existing `raw.json` | `raw.json` | Run `discovery` and hand existing raw evidence to the Search supplement policy. |
| `enrich` | deterministic unless `--web-extract` | `raw.json` | `enriched.json` | Fill missing publication dates from API metadata, snippets, URLs, or optional page fetches. |
| `verify` | deterministic | `enriched.json` plus `domain.yaml` | `verified.jsonl` | Apply freshness, URL, duplication, blocklist, and source quality gates. |
| `normalize` | deterministic | `verified.jsonl` plus `domain.yaml` | `articles.jsonl` | Convert verified records into ArticleRecord-like rows with entities, terms, source metadata, and optional event-thread matches. |
| `cluster` | deterministic | `articles.jsonl` | `clusters.json` | Group related articles by event-thread anchor and entity/term overlap. |
| `edit` | LLM-dependent | `articles.jsonl`, `clusters.json`, story context | `{Domain}_{Timescale}_Briefing_{period}.md`, `briefing_plan.json`, `briefing_chunks.json`, `edit_trace.json`, optional `event-threads.json` | Build dynamic evidence categories, edit category blocks with the LLM, render through the timescale template, and produce structured thread data. |
| `validate` | deterministic | `{Domain}_{Timescale}_Briefing_{period}.md`, `articles.jsonl`, optional schemas | exit status and `validate_report.json` | Check cited sources, cited dates, and structured event-thread schema validity. |
| `repair` | deterministic | `{Domain}_{Timescale}_Briefing_{period}.md`, `articles.jsonl`, `validate_report.json` | rewritten `{Domain}_{Timescale}_Briefing_{period}.md`, `repair_report.json` | Rewrite or drop invalid items using validate telemetry and support-article evidence. |
| `validate_recheck` | deterministic | repaired `{Domain}_{Timescale}_Briefing_{period}.md`, `articles.jsonl`, optional schemas | exit status and final `validate_report.json` | Re-run the content gate after repair so render only sees a validated artifact. |
| `render` | deterministic, PDF shell-out optional | `{Domain}_{Timescale}_Briefing_{period}.md`, template | `{Domain}_{Timescale}_Briefing_{period}.html`, optional `{Domain}_{Timescale}_Briefing_{period}.pdf` | Convert Markdown to template-backed HTML, then use local Chrome for PDF when available. |

## Detailed Flow

### 1. acquisition

`acquisition/acquisition.py` is the stage wrapper around
`stratum.sourcing.discovery`.
The package entrypoint `stratum.stages.acquisition` is the stable import
surface for acquisition helpers; external callers should prefer it over
reaching into the stage file directly.
Legacy imports through `search/search.py` remain supported only as a narrow
compatibility alias for the small helper surface still used by tests or older
entrypoints. The package entrypoint `stratum.stages.search` is a compatibility
surface only; new code should import the canonical acquisition package
directly.

Inputs:
- `--config config.yaml` for API keys, engine settings, and `.env` resolution.
- `--db <domain.db>` for current DB-backed discovery queries, plus `--queries <queries.yaml>` as the baseline fallback.
- `--date YYYY-MM-DD` for date-aware engine calls and freshness scoring.

Output:
- JSON array of merged watchlist/discovery result dictionaries in
  `raw.json`.
- Search quality and execution sidecar in `raw.stats.json`.

Important boundary:
- No legacy curl scripts or old search implementation should be reintroduced here.
- A present DB file is not treated as sufficient by itself. If it has no active
  daily queries, the stage falls back to `queries.yaml` so Search does not
  silently produce an empty raw pool.
- DB-backed query loading is delegated to `stratum.db.service`; Search does not
  embed SQLite table contracts directly.
- When `--db` is provided, Search also loads the latest persisted engine-health
  recommendations from that SQLite path and passes them into the Search
  subsystem so weak engines move later in the fallback chain before API calls
  start.
- `queries.yaml` uses the structured `queries` schema. It may be either
  `queries: intent -> locale -> list` for simple domains or
  `queries: intent -> dimension -> locale -> list` for coverage-aware domains.
  Search normalizes these into `{id, text, locale, intent, dimension}`.
  Query items may also carry `include_domains`, which Tavily receives as hard
  source filters. This is the preferred shape for source-first/official-site
  queries; legacy `site:` text still works but is no longer the only option.
- Discovery diagnostics live in `raw.stats.json`, not in `raw.json`. They cover
  per-query status plus raw-vs-curated locale/dimension/source-type coverage,
  source-type shortfalls, low-yield queries, and top contributing domains.
- Coverage-aware query skip/run decisions, higher-priority raw/Search merge
  priority, and skipped-query stats are delegated to
  `stratum.sourcing.discovery.query_planner.SearchSupplementPolicy`, so the
  stage owns query loading, API execution, and artifact handoff while the
  planning algorithm owns the decision.
- Discovery results preserve original `url` but add `canonical_url` for dedupe.
  Canonicalization strips tracking query parameters/fragments and normalizes
  common `www.`/`m.` host variants.
- `raw.json` is the only raw dataset for a domain/date run. Curated counts and
  quality diagnostics live in sidecars or downstream artifacts, not in extra raw
  JSON copies.

### 2. watchlist sidecar

Watchlists are not a separate numbered stage script. The orchestrator calls them before broad discovery and seeds `raw.json`; acquisition then uses that higher-priority evidence to avoid repeat domain-scoped API calls.

Inputs:
- `domain.yaml` `source_registry.sources`
- domain keyword config
- current run date

Supported watchlist:
- RSS/Atom feeds
- direct page fetches
- browser-backed sources when Playwright is installed

Output:
- Search-shaped records written into the same single raw result set.

Important boundary:
- Watchlist failures should degrade a source, not invalidate the whole briefing run.
- Browser collection is optional and must report missing Playwright clearly.

### 3. enrich

`enrich/enrich.py` adds or repairs publication dates.
The package entrypoint `stratum.stages.enrich` is the stable import surface for
date-extraction helpers; external callers should prefer it over reaching into
the stage file directly.

Inputs:
- `raw.json`
- run date
- optional `--web-extract`

Output:
- `enriched.json`

Freshness order:
- existing `datePublished`
- existing `published_at` when `datePublished` is absent
- snippet regex
- URL path date
- configured freshness window fallback
- optional page metadata extraction

Dates extracted by snippet regex, URL path, or page metadata must be plausible
publication dates for the run date. Candidates beyond the configured future
grace are ignored so future event dates do not poison article freshness.
When text contains multiple date-like values, Enrich keeps scanning within the
same pattern until it finds a plausible publication date instead of letting the
first future event date hide a later publication timestamp.
`date_source` records the lineage (`search_api`, `snippet_regex`, `url_path`,
`freshness_window`, `web_extract`, or `none`) and is preserved through verify
and normalize for debugging and quality policy.
Verify maps that lineage to `date_confidence`: API, page metadata, and URL-path
dates are high confidence; freshness-window inference is medium; title/snippet
regex dates are low. Domains can set
`pipeline.date_window.min_date_confidence` to reject weak date evidence. The
default policy keeps low-confidence dates with a `LOW_CONFIDENCE_DATE` quality
flag so downstream stages can inspect the risk without losing recall.
Enrich preserves an existing non-`none` `date_source` instead of relabeling
watchlist or upstream-derived dates as `search_api`.

### 4. verify

`verify/verify.py` decides which enriched records are allowed into the briefing evidence set.
Freshness, date-confidence, and background-evidence admission policy live in
`verify/freshness_policy.py` as `FreshnessPolicy`; the stage uses that policy
instead of owning date-window tuning logic directly.
`FreshnessPolicy` supports optional source-type-specific stale windows through
`pipeline.date_window.source_type_stale_days`, so official, financial, analyst,
or other evidence classes can have calibrated freshness windows without
forking Verify orchestration.
Blocklist, low-priority source gates, magnitude sanity, duplicate detection,
platform admission, and corroboration scoring live in `verify/evidence_acceptance.py` as
`EvidenceAcceptancePolicy`; the stage records the decision outcome but does not
own the acceptance algorithm directly.
The package entrypoint `stratum.stages.verify` is the stable import surface for
Verify helpers; external callers should prefer it over reaching into sibling
policy modules unless they intentionally depend on a specific implementation.

Inputs:
- `enriched.json`
- `domain.yaml`
- run date

Output:
- JSONL `verified.jsonl`
- JSON sidecar `verified.stats.json` with verification totals, rejection
  reasons, date-confidence counts, quality-flag counts, and corroboration
  level counts

Checks:
- publication date freshness
- malformed or blocked URLs
- title/snippet quality
- duplicate canonical URLs or near-duplicate titles
- domain-level source policy

Important boundary:
- Blocklist and low-priority domain policy use host-boundary matching. A rule
  for `youtube.com` applies to `m.youtube.com`, but not to
  `notyoutube.com`; low-priority roots such as `google.com` also cover their
  subdomains.
- Evidence acceptance is delegated to `EvidenceAcceptancePolicy`; the stage
  still controls when the policy runs relative to freshness so rejected raw
  evidence keeps the same external contract.
- Verify preserves upstream `date_source` when present. If an enriched/raw
  record has metadata dates but no lineage, Verify marks it as `search_api`;
  if Verify itself extracts a date from title/snippet text, it marks
  `snippet_regex`; records rejected with no usable date emit `none`.
- Verify emits `date_confidence` and `quality_flags` so weak inferred freshness
  is visible to Normalize, clustering/debugging, and future editorial policy.
- Verify emits `corroboration_score`, `corroboration_level`, and optional
  `corroborating_sources` so downstream stages can distinguish single-source
  evidence from independently supported evidence without embedding that
  scoring in the stage body.
- Background stale/no-date admission is a freshness-policy decision. The stage
  records resulting `BACKGROUND_STALE`, `BACKGROUND_NO_DATE`, or
  `LOW_CONFIDENCE_DATE` quality flags but does not own the decision rules.
- Verify writes a stats sidecar next to `verified.jsonl` by default, or to
  `--stats` when the orchestrator supplies an explicit path. This keeps
  rejection diagnostics machine-readable instead of only printed to stderr.

### 5. normalize

`normalize/normalize.py` converts verified search-like records into stable article records.
Entity, term, title-pattern, and numeric-claim extraction live in
`normalize/extractors.py` as `EntityResolver`, `TermResolver`, and
`ClaimExtractor`. The stage assembles ArticleRecord-shaped rows and calls those
components instead of owning extraction algorithms directly. The resolvers
produce both display labels (`entities`, `terms`) and canonical ids
(`entity_ids`, `term_ids`) from structured domain records or legacy flat lists.
The package entrypoint `stratum.stages.normalize` is the stable import surface
for Normalize helpers; external callers should prefer it over reaching into
individual sibling modules unless they intentionally need a specific algorithm
implementation detail.
Thread keyword matching lives in `normalize/thread_matcher.py` as
`ThreadKeywordMatcher`, which owns IDF weighting, co-occurrence scoring,
sub-token matching, thresholds, and match diagnostics.

Inputs:
- `verified.jsonl`
- `domain.yaml`
- optional `thread_keywords.json`

Output:
- JSONL `articles.jsonl`

Adds:
- stable article id based on canonical URL plus title
- canonical URL preserved from Verify or recomputed with the discovery canonicalizer
- `source`, `source_type`, `source_locale`, and `date_source`
- upstream `engine`, `query_id`, `query_used`, `query_dimension`, and `discovery_mode`
- extracted entities, entity ids, terms, term ids, legacy numeric claim strings,
  typed numeric claim records, and artifact type
- optional `event_thread_id`

Important boundary:
- Upstream explicit metadata wins over heuristics. For example,
  `source_type_hint` from Search/Watchlists is preferred over URL
  reclassification, and explicit `locale` is preferred over domain guessing.
- URL fallback source classification uses domain-boundary matching instead of
  loose substring matching, so impostor domains such as `fakesamsung.com` cannot
  inherit official-source treatment from configured `samsung.com` rules.
- `content_hash` uses canonical URL plus title so mobile/tracking URL variants
  do not become distinct ArticleRecords.
- `thread_keywords.json` may assign `event_thread_id`, but only keywords/topics
  that actually match the article text are added to `terms`. Unmatched thread
  vocabulary must not pollute ArticleRecord terms.
- Static entities, static terms, canonical entity/term ids, title-pattern terms,
  legacy numeric claim strings, typed numeric claims, and thread keyword
  matching are delegated to Normalize algorithm components.
  `typed_numeric_claims` currently covers
  price changes, ASP, yield, capacity, CAPEX, shipments, and revenue.
  Normalize should continue to evolve richer taxonomy and claim typing in those
  components rather than adding new scoring logic to the stage body.

### 6. cluster

`cluster/cluster.py` groups normalized articles into story clusters.
Similarity scoring, thread-anchor grouping, bridge-cluster splitting,
oversized-cluster splitting, and confidence scoring live in
`cluster/story_clusterer.py` as `StoryClusterer` and
`ClusterConfidenceScorer`. The stage owns file IO, artifact shape, domain/date
parameters, and StoryCluster object assembly; the algorithm module owns
scoring, ranking, merge/split policy, and confidence calibration.
The package entrypoint `stratum.stages.cluster` is the stable import surface
for clustering helpers.

Inputs:
- `articles.jsonl`
- `domain.yaml`
- run date

Output:
- `clusters.json`

Algorithm component:
- `StoryClusterer` force-merges articles sharing `event_thread_id`
- `StoryClusterer` clusters remaining articles by weighted entity/term overlap; entity overlap
  carries more weight than generic term overlap, and shared primary entities
  carry more salience than incidental secondary-entity overlap
- `StoryClusterer` reviews orphan clusters for bridge over-merge: when a component has no entity
  shared by every article, it is split by primary entity so one article cannot
  connect distinct subjects only through pairwise overlap
- `StoryClusterer` splits oversized orphan clusters recursively with a stricter threshold, with
  a minimum split threshold of `0.35` so low-threshold discovery does not keep
  oversized generic components intact
- `ClusterConfidenceScorer` assigns cluster confidence labels and numeric
  scores from article count, source-type diversity, locale diversity, and
  entity coverage

Cluster objects include `source_domains` and `canonical_urls` in addition to
article IDs. These are audit fields: downstream stages should still use
`article_ids` as the primary join key, but the extra fields make source-mix and
duplicate investigations visible without rehydrating every article.
When upstream records provide `source_domain` instead of `source`, or only a
raw `url` instead of `canonical_url`, Cluster fills those audit fields from the
available metadata so diagnostics stay useful across search-shaped and
ArticleRecord-shaped inputs.
`created` is the pipeline run date, not wall-clock execution date, so backfills
and historical reruns produce stable cluster artifacts.
`event_thread_id` anchoring is a continuity contract with Story Tracking. A
thread-anchored cluster is not split by the generic `max_size` overflow pass;
large continuing stories should stay one cluster unless Story Tracking itself
splits or resolves the thread.

### 7. edit

`edit/source_repair.py` owns deterministic source-line repair for generated
Markdown. Source/article alignment for those repairs lives in
`edit/source_alignment.py` as `SourceAlignmentMatcher`, so token overlap,
source-label matching, and repair thresholds stay in a named algorithm
component instead of the Markdown traversal helper.
`edit/block_policy.py` owns category-block payload construction, generated item
normalization, bad-JSON handling, missing-item fallback, and deterministic
fallback paragraphs through `BlockOutputPolicy`.
`edit/profile_policy.py` owns report-level polish payload construction and
summary/focus/contrarian fallback normalization through `ProfilePolishPolicy`;
`edit/edit.py` only calls the polish prompt and hands the parsed response back
to that policy.
`edit/renderer.py` owns deterministic category Markdown assembly, source-line
rendering, Chinese date labels, and timescale template rendering through
`EditRenderer`. `edit/edit.py` still owns the stage orchestration, LLM
transport/concurrency, and block-level structured output handoff.
`edit/output_policy.py` owns generated Markdown item classification and output
budget checks through `EditOutputPolicy`, including edge-signal heading
normalization and main/edge item count gates. When the deterministic plan has
fewer valid items than the manifest's normal daily minimum, the policy lowers
minimum gates to the plan counts instead of forcing impossible item volume from
sparse evidence.
`edit/structured_output.py` owns event-thread structured output normalization
and plan-derived fallback construction through
`DeterministicStructuredOutputBuilder`, including deterministic thread id
repair, causal-edge cleanup, judgment key normalization, and fallback
threads/causal edges/judgments built from selected main report items.
`edit/planning_policy.py` owns deterministic evidence, cluster, and category
scoring through `EditorialEvidenceScorer` and runtime budget resolution through
`ItemBudgetPolicy`. It owns cluster and unclustered evidence candidate
selection through `CategoryCandidatePolicy`, including cluster ordering,
cluster-vs-edge classification, evidence filtering, and unclustered candidate
selection. It also owns final item selection and omission diagnostics through
`PlanReconciliationPolicy`, including duplicate-topic suppression,
per-category caps, and outside-budget drops. `CategoryGroupingPolicy` owns
final selected-item grouping into dynamic report categories and category
ranking by evidence strength. `edit/planner.py` owns dynamic category/item
artifact assembly through `ReportPlanner` and calls those policies instead of
embedding scoring, budget, candidate-selection, grouping, and final reconcile
rules in the orchestration flow. The public `build_block_plan` function remains
as a compatibility wrapper for the Edit stage.

`edit/edit.py` is the LLM editorial boundary. The active v3 path is a
timescale-aware block editor: deterministic planning builds dynamic categories
from the normalized evidence, category-sized LLM calls edit those blocks, and
the final Markdown is assembled through the configured timescale template.

Inputs:
- `articles.jsonl`
- `clusters.json`
- generated story context
- prompt manifest and block/polish prompts from `stratum/stages/edit/prompts/`
- timescale Markdown template from `stratum/stages/edit/templates/`
- `config.yaml` LLM settings
- `domain.yaml` policy and title values injected into the prompt

Output:
- canonical briefing Markdown artifact
  `{Domain}_{Timescale}_Briefing_{period}.md`
- `briefing_plan.json` with dynamic categories, selected items, and dropped
  candidates
- `briefing_chunks.json` with category block edit outputs; the filename is
  retained for compatibility with previous chunk artifacts
- `edit_trace.json` with mode, timescale, category/block status, and counts
- optional `event-threads.json` when the LLM emits `threads`, `causal_edges`,
  or `judgments`

Important boundary:
- Edit uses `edit/planner.py`, `stratum/stages/edit/prompts/category_block.md`,
  `stratum/stages/edit/prompts/profile_polish.md`, and the
  timescale templates. Manifest profiles are expected to set
  `budget.edit_mode: v3`; non-v3 edit modes fail fast.
- Raw search data is not rewritten by Edit. `stratum/stages/boilerplate.py`
  applies
  deterministic generic and `domain.yaml` source-specific cleanup rules to the
  evidence surface before LLM calls, and Edit fails fast if generated briefing
  or block artifacts still contain configured boilerplate markers.
- LLM transport lives in `edit/llm_client.py`.
- The orchestrator currently invokes Edit with `--timescale daily`. Higher
  timescales are first-class temporal profiles, but their current production path
  is DB-native synthesis plus render, not LLM Edit. Future higher-scale Edit
  stages should be introduced through `stratum/temporal/profiles.py` first.
- Daily structured output asks for `threads` with concrete `watch_signals`,
  `close_conditions`, status, priority, and entity/term ids so DB ingest can
  seed next-run Search follow-up queries.
- `threads`, `causal_edges`, and `judgments` all have JSON Schema files under
  `prompts/_schemas/`. The schema thread-id shape follows the current
  `et-{domain}-{date}-{hash}` / `et-{domain}-{seq}` style instead of the older
  `et-YYYY-NNN` placeholder.
- If the LLM leaves a new thread id blank, Edit assigns a deterministic
  `et-{domain}-{date}-{hash}` id before writing `event-threads.json`. This keeps
  DB ingest and watch-query persistence pointed at the same thread surface.
- The stage should still write the Markdown briefing if optional structured JSON is malformed.
- Before writing, Edit applies a deterministic source-line repair: if a news
  item has no source/date line and clearly matches one input article, it adds
  that article's source and date. It does not invent sources for weak matches
  and skips configured structural sections such as the daily `today`,
  `industry`, `signals`, `focus`, and `contrarian` chunks.
- Edge-signal heading normalization and generated-item budget checks are
  delegated to `EditOutputPolicy`; Edit only invokes the policy before writing
  and reporting the budget status.
- The active daily template has five major chunk keys: `today`, `industry`,
  `signals`, `focus`, and `contrarian`. The industry chunk contains dynamic
  evidence-derived category subsections; the signals chunk contains weak/edge
  signals whose item titles still carry the configured localized edge-signal
  prefix for downstream counting and validation compatibility.

### 8. validate

Validation includes source existence, source-to-item alignment, cited date
freshness, structured schema checks, boilerplate leakage checks, and first-pass
overclaim rules. Current overclaim rules catch sample/qualification evidence
being promoted to mass-production confirmation and reported signals being
promoted to confirmed facts. They also catch forecast or guidance language
being promoted to certain outcomes. Domain-specific evidence-class rules also
flag customer/design-win claims that are supported only by qualification,
validation, sampling, or weak reported signals, and financial outcome claims
that are supported only by analyst/media forecasts, channel checks, or other
non-company evidence. Causal-language rules flag generated claims that turn
correlation, linkage, or modal analyst language into explicit causality without
mechanism evidence.

`validate/validate.py` is the content gate after LLM editing. Claim support and
overclaim policy live in `validate/claim_validator.py` as `ClaimValidator`; the
stage calls that validator instead of owning the algorithm rules directly.
`ClaimValidator` owns the claim-pattern, weak-evidence, support-pattern,
weak-source-type, and high-salience entity-consistency rules through
`EvidenceClassRule`; the stage only hands over the generated item and aligned
supporting articles.
Source-to-article support matching and cited/article date parsing live in
`validate/source_support.py` as `SourceSupportMatcher` and `SourceDatePolicy`.
Those components own source alias/domain matching, multilingual item/article
token overlap, distinctive token detection, background-evidence classification,
and cited-date range parsing; `validate/validate.py` only records the resulting
violations.
The package entrypoint `stratum.stages.validate` is the stable import surface
for parsing, overclaim checks, source/date support logic, and structured-output
validation helpers.

Inputs:
- canonical briefing Markdown artifact
  `{Domain}_{Timescale}_Briefing_{period}.md`
- `articles.jsonl`
- `domain.yaml`
- optional `event-threads.json` and schema directory

Output:
- JSON status report to stdout
- exit code `0` for clean validation, `1` for violations

Checks:
- cited sources map back to verified/normalized article sources
- cited source articles have coarse content overlap with the news item they support
- cited source-line dates match the publication date of a supporting article
  when that article carries date evidence
- cited dates are parseable and within `pipeline.date_window`
- structured threads, causal edges, and judgments match JSON Schema when present
- generated Markdown contains no configured evidence boilerplate markers

Important boundary:
- Validate parses news items from `###` headings and stops an item when a new
  `##` section begins. Structural sections such as focus and contrarian notes
  must not be attached to the final news item for claim validation.
- Validate reuses the same shared `stratum.stages.boilerplate` helper and
  `pipeline.boilerplate` rule contract as Edit so
  template/navigation leaks are caught as deterministic `BOILERPLATE`
  violations instead of being left to LLM style judgment.
- Validate strips source-line locale tags such as `[en]` or `[zh-CN]` while
  parsing, so one missed Edit cleanup does not cause a false source violation.
  The prompt and Edit cleanup still require rendered source lines to omit those
  tags.
- Brand-like source labels such as `Reuters` must match through configured
  aliases or exact source names. Alias and domain-like source matching use
  host-boundary rules, so `Reuters -> reuters.com` can match
  `www.reuters.com` but not `notreuters.com`. Parent-domain labels such as
  `sina.com.cn` can still match article subdomains such as
  `finance.sina.com.cn`.
- Source-item alignment requires the cited article to expose comparable title,
  snippet, or extracted-summary tokens when the generated item has content.
  A source existing in the article pool is not sufficient evidence by itself.
- Source-date alignment is evidence-based: if aligned articles from a cited
  source carry publication dates and none match the report's cited date,
  Validate emits `SOURCE_DATE`. Undated aligned articles do not create a date
  mismatch by themselves.

### 9. render

`render/render.py` owns Markdown-to-HTML/PDF conversion. The package entrypoint
`stratum.stages.render` is the stable import surface for render helpers and
artifact naming.

`render/render.py` turns the validated Markdown into user-facing artifacts.

Inputs:
- canonical briefing Markdown artifact
  `{Domain}_{Timescale}_Briefing_{period}.md`
- HTML template
- title/date/footer strings
- optional `domain.yaml` render tags

Output:
- canonical HTML artifact `{Domain}_{Timescale}_Briefing_{period}.html`
- canonical PDF artifact `{Domain}_{Timescale}_Briefing_{period}.pdf` only when
  local Chrome exists and succeeds

Important boundary:
- Missing Chrome is a non-fatal PDF skip; HTML remains the durable artifact.
- Render tag badges are detected from a complete item block: title plus body
  text. The heading is rendered only after the item body/source line is seen, so
  domain tags such as price, supply, or technology can be driven by the actual
  item text instead of title keywords only.
- Render strips machine locale tags such as `[en]` and `[zh-CN]` from displayed
  source lines as a final presentation guard. Locale cleanup accepts case
  variants and script/region tags such as `[EN]`, `[zh-cn]`, and
  `[zh-Hans-CN]`. Edit should still avoid writing them, and Validate should
  still parse defensively.

## Dependencies

Runtime dependencies:
- `config.yaml`
- `domains/<domain>/domain.yaml`
- `domains/<domain>/queries.yaml` or SQLite discovery DB
- `domains/<domain>/templates/daily.html`
- `stratum/sourcing/discovery`
- `stratum/sourcing/watchlist`
- optional local Chrome for PDF

Downstream dependencies:
- `stratum/orchestrator/pipeline.py`
- `stratum/temporal` for timescale stage profiles and higher-scale temporal execution
- `stratum/db/ingest.py` for post-run event-thread ingestion
- `stratum/subsystems/story_tracking` for context and next-run keyword export

## Design Rules

- Keep stages executable as standalone scripts.
- Keep domain knowledge in domain config, not hardcoded stage code.
- Keep search and edit as the only external intelligence boundaries.
- Treat watchlist as additive evidence acquisition, not a replacement for search.
- Prefer deterministic validation after every LLM boundary.
