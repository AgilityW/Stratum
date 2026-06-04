# sourcing/discovery - query-driven external discovery

## Purpose

`stratum/sourcing/discovery` is the shared discovery subsystem used by Stage 1. It hides individual engine APIs behind a common query/result model, applies routing and retry behavior, then curates results for downstream pipeline stages.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for `run_search`, config loaders, diagnostics, and core query/result models |
| `models.py` | `Query`, `SearchResult`, `QueryStats`, `ResultSet` |
| `config.py` | adapts `config.yaml` and `domain.yaml` into subsystem config |
| `engine.py` | Bocha and Tavily API clients |
| `observations.py` | pre-curation normalized provider observation records |
| `query_planner.py` | `QueryPlanner`, `SearchSupplementPolicy`, and `QueryPerformanceScorer` for coverage-aware query decisions, higher-priority raw/discovery supplement merging, skipped-query stats, historical-yield diagnostics, performance-aware ordering, and optional low-yield retirement |
| `executor.py` | concurrent execution, rate limiting, fallback, retry |
| `routing.py` | `RoutingPolicy` for locale fallback and engine-health route ordering |
| `curation_policy.py` | `SearchResultScorer` and `SearchDiversityRanker` for source quality, freshness, relevance, novelty, and diversity policy |
| `curator.py` | domain extraction, source classification, and curation orchestration |

## Public API

```python
from stratum.sourcing.discovery import load_api_keys, load_search_config, run_search

config = load_search_config("storage", workspace)
api_keys = load_api_keys()
result_set = run_search(queries, config, api_keys, "2026-05-30")
stats = result_set.to_stats_json()
```

The package entrypoint `stratum.sourcing.discovery` is the stable import
surface for `run_search`, `load_search_config`, `load_api_keys`,
`build_diagnostics`, the core model types (`Query`, `SearchResult`,
`QueryStats`, `ResultSet`), and the shared normalization helpers
`canonicalize_url`, `normalize_include_domains`, and
`source_pattern_matches`. It also exports the public query-planning and
curation policy types used across acquisition and tests:
`QueryPlanner`, `QueryPerformanceScorer`, `SearchSupplementPolicy`,
`SearchResultScorer`, `SearchDiversityRanker`, and
`split_queries_by_coverage`. External callers should prefer the package surface
over reaching into individual implementation modules unless they intentionally
depend on an engine implementation detail.

`queries` is a list of dicts:

```python
{
  "id": "q-en-0",
  "text": "Samsung HBM4",
  "locale": "en",
  "intent": "detection",
  "include_domains": ["semiconductor.samsung.com"]
}
```

`raw.stats.json` includes per-query `QueryStats`. When a query is scoped with
`include_domains`, the stats entry keeps those domains as well, including
low-yield/no-result records. That makes discovery recall debugging concrete: a
zero-result query can be distinguished from a broad web query versus an
official-source query whose domain filter may be too narrow.
When fallback routing touches more than one engine, `QueryStats` also preserves
`engine_attempts`, an ordered attempt chain with each engine status and error.
This keeps provider failures observable instead of allowing the final fallback
error to hide the earlier failure cause.
Discovery diagnostics include `engine_health`, which aggregates those attempt
chains into per-engine health scores and recommendations. When callers provide
prior `engine_health` in config, `RoutingPolicy` keeps the configured route but
moves weak engines later in the fallback order.
Provider-level quota, billing, and authorization failures are treated as
`provider_exhausted` attempts. The executor records the failure, stops retrying
that engine for the query, marks the provider unavailable for the rest of the
run, and lets fallback engines handle remaining queries when possible.
The diagnostics block also reports `domain_filter_coverage`: for each
configured include domain, it shows how many scoped queries targeted that
domain, how many failed, and how many raw/curated results came back from it.
It also reports `query_performance`, produced by
`QueryPerformanceScorer`, with per-query yield rate, low-yield retirement
candidates, gap-expansion candidates, and deterministic `rewrite_hint` guidance
for review or query maintenance. The scorer owns the algorithmic
recommendation; the stage only writes diagnostics.
When callers pass prior `query_performance` records in config, `QueryPlanner`
orders healthy queries before gap/low-yield candidates before execution.
`query_planning.retire_low_yield: true` may skip `retire_or_rewrite`
candidates; the default is conservative and only defers them later in the run.
When watchlist or other higher-priority sources seed `raw.json`,
`SearchSupplementPolicy` owns the supplemental discovery plan: skip already covered
domain-scoped queries, keep higher-priority raw records before discovery results
on canonical-URL conflicts, and emit skipped-query stats. The stage owns CLI,
query loading, discovery execution, and artifact writes.

Discovery also emits `discovery_observations.jsonl` beside `raw.json`.
Observations are normalized provider results after Bocha/Tavily response
mapping and before curation scoring, ranking, pruning, or selected/rejected
candidate status. They must not include curation fields such as `status`,
`selected`, `score`, or `reason`; those belong in
`discovery_candidates.jsonl`.

Stage `stratum/stages/acquisition/acquisition.py` accepts the structured YAML query schema:

- simple domains: `queries: intent -> locale -> list`
- coverage-aware domains: `queries: intent -> dimension -> locale -> list`

Locale keys are treated as BCP 47-style tags, so simple query files can use
variants such as `en-US`, `zh-cn`, or `zh-Hans-CN` without being mistaken for
coverage dimensions.

The dimensioned form is preferred for Storage because it separates the search
job (`detection`, `verification`) from the briefing coverage surface
(`technology`, `product`, `platform_demand`, `supply_chain`, `market_pricing`,
`financial`, etc.).

## Boundaries

### Owns

- Route locale to engine priority list through `RoutingPolicy`.
- Route BCP 47 locale variants through compatible configured parents when an
  exact route is absent; for example `zh-Hans-CN` can reuse `zh-CN`, and
  `en-US` can reuse `en`.
- Execute Tavily/Bocha requests.
- Pass run-date filters to engines.
- Load DB-backed daily detection/verification queries for unbound queries and
  thread-bound `emerging`, `active`, or `cooling` threads. Cooling thread
  queries remain eligible because they are still part of the follow-up loop.
- Retry rate-limited or failed requests according to config.
- Skip engines that have no API key, then fall back through the remaining
  locale routing chain.
- Skip engines that cannot honor `include_domains` for source-scoped queries,
  then continue through the fallback chain. This prevents a domain-scoped query
  from silently widening into broad discovery.
- Select Tavily `topic` by query shape: site-filtered/domain-scoped queries use
  `general`, and broad queries can override the default by intent or briefing
  dimension through engine config.
- Let individual structured queries carry `include_domains`, so site-first or
  official-source discovery queries can be expressed as data instead of embedding
  `site:` operators in query text. These query-scoped domains are combined with
  any locale-level Tavily source filters and legacy `site:` terms. DB-seeded
  queries preserve the same field, so switching from YAML-backed to DB-backed
  acquisition does not remove source filters.
  Include-domain values are normalized through one shared helper into
  host-only, lowercase domains with presentation prefixes such as `www.` and
  `m.` removed. Malformed structures fail loudly instead of widening a
  source-scoped query by accident.
  Domain-owned query files are expected to use this structured form; `site:`
  remains only as engine-level compatibility for ad hoc or historical input.
- Reuse Tavily `include_domains` settings across compatible locale variants, so
  a query tagged `en-US` can still use `en` source filters and
  `zh-Hans-CN` can still use `zh-CN`/`zh` source filters.
- Normalize engine results to `SearchResult`.
- Classify source type with domain-boundary matching. Domain patterns match the
  exact host or subdomains, so `reuters.com` matches `asia.reuters.com` but not
  `notreuters.com`; configured path-like patterns can still match either a URL
  path prefix or an equivalent subdomain form such as
  `semiconductor.samsung.com`.
- Canonicalize URLs for dedupe by stripping tracking query parameters,
  fragments, common mobile host prefixes, and cosmetic trailing slashes.
- Score and prune results for diagnostics/coverage through
  `SearchResultScorer` and `SearchDiversityRanker`. The scorer owns source
  quality, freshness, relevance, and novelty weights, while stage output keeps
  the full raw discovery result set for the orchestrator to merge into the single
  `raw.json`.
- Preserve a configured minimum source-type mix when candidates exist, so available official/analyst/media evidence is not removed only because one source type has more high-scoring results.
- Limit single-entity dominance after source-type evidence is reserved, so one company/topic cannot consume the curated pool by volume alone.

### Does Not Own

- Does not read query YAML or SQLite directly. Stage `stratum/stages/acquisition/acquisition.py` owns query loading.
- Does not decide coverage-aware query suppression or raw-result merge priority
  inside the stage body. `SearchSupplementPolicy` owns the supplemental discovery
  plan after higher-priority watchlist evidence already covers include domains,
  and `QueryPlanner` owns the underlying coverage decision.
- Does not embed historical query-yield pruning in the public API or stage.
  `QueryPlanner` owns performance-aware ordering and optional retirement from
  supplied `query_performance` records.
- Does not run watchlist. Project-level evidence acquisition runs watchlist
  before discovery and passes that existing raw pool into the acquisition stage.
  Discovery is the broad-engine supplement layer, not the first source priority
  when watchlist are available.
- Does not verify freshness beyond curation scoring. Verify stage is the gate.
- Does not enrich missing dates from web pages. Enrich stage owns that.

## Configuration Sources

- `config.yaml`
  - `engines`
  - `source_languages`
  - `locales`
  - `curation`
- `domains/{domain}/domain.yaml`
  - company aliases, preserved across locales for entity scoring and entity-dominance caps
  - term aliases, preserved across locales for relevance scoring
  - source classifications, used only as source type -> URL/domain patterns

API keys are loaded from environment, with `.env` next to the selected
`--config` file supported by `config.py` before config interpolation. Stage 1
passes the exact CLI `--config` path into the subsystem, so alternate config
files are honored instead of implicitly falling back to `workspace/config.yaml`.
Engine clients are only constructed when the matching API key exists. This
avoids slow auth-failure retries and keeps diagnostics focused on which engine
was unavailable. If no configured engine is usable, discovery still writes
per-query failed stats instead of returning an opaque empty result set.

Tavily topic strategy is configured under `engines.tavily.extra`. The default
`topic` remains the broad-query fallback, while `topic_by_intent` and
`topic_by_dimension` let discovery use `general` for verification, financial,
pricing, or supply-chain queries where professional/source-specific pages often
rank better than news-only results. Query metadata is passed from the executor
to the engine so this strategy is testable without changing query text.

## Curation Policy

`curation.min_per_source_type` is a soft floor. The curator first reserves the
best available candidates for each configured source type while respecting
locale, source-domain, and total caps. If a source type has fewer candidates
than its floor, the remaining slots are filled by the normal score order.
The reserve/fill decision lives in
`stratum.sourcing.discovery.curation_policy.SearchDiversityRanker`; `curator.py`
keeps the public curation function and SearchResult classification handoff.

`curation.max_per_entity` is a soft diversity cap applied during the normal fill
step. It matches configured company aliases against result titles/snippets and
prevents one entity from dominating curated results. The source-type reservation
step can exceed this cap when needed to preserve official/analyst/media evidence.
Company and term aliases are preserved from `domain.yaml` rather than reduced to
English/Chinese display names, so Japanese, Korean, Traditional Chinese, and
other locale results can still contribute to relevance and diversity decisions.
Freshness, source weight, and entity/term relevance scoring live in
`SearchResultScorer` so curation weighting can evolve without growing inside
the discovery orchestration path.

Company aliases are intentionally not copied into `classifications`: the
classification map is only for source type hints such as `official`, `analyst`,
or `media`. This keeps `news.samsung.com` classified as `official` instead of a
synthetic `company` type, so source weights and source-type quotas remain
meaningful.

## Output Compatibility

`SearchResult.to_dict()` writes both subsystem-native and legacy-compatible fields:

- native: `published_at`, `canonical_url`, `source_domain`, `source_type_hint`, `query_id`
- downstream compatibility: `datePublished`, `description`, `query_used`

This keeps enrich/verify/normalize compatible while legacy stage-search code has been removed.
The original `url` is preserved for traceability, while `canonical_url` is used
as the dedupe key inside discovery and during watchlist/discovery merge.

Stage `stratum/stages/acquisition/acquisition.py` also writes `raw.stats.json` next to
`raw.json`. The stats payload includes raw/curated counts, engine/locale/source
type summaries, and per-query records with `query_id`, `locale`, `intent`,
`status`, `results_count`, latency, retries, and error text. `results_count`
is the number of canonical-URL-unique results produced by that query, not the
engine's raw duplicate-inclusive item count. The orchestrator ingests those
per-query records into SQLite query counters after acquisition.
The stats payload also includes `diagnostics`: raw vs curated locale/source-type
coverage, raw vs curated dimension coverage, source-type floor shortfalls,
low-yield query records, and top source domains before/after curation. This
sidecar is the first place to inspect when a site-first query, locale, briefing
dimension, or evidence type underperforms.

When the orchestrator passes both `--db` and `--queries`, the stage prefers
active DB queries but falls back to the domain YAML baseline if the DB exists
without active daily queries or has an unusable query table. This prevents an
empty SQLite file from silently turning Stage 1 into a zero-query run.
DB-backed queries preserve `queries.dimension` when the column exists; older
DBs or minimal test tables without the column fall back to `db`/`general`
without breaking execution.
