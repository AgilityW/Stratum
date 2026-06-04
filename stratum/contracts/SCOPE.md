# contracts - shared data contracts

## Purpose

`stratum/contracts` stores shared data models and JSON Schemas used across
modules. Its job is to give stages, subsystems, and tests common names and
field expectations for shared structures.

Project-wide contract boundary rules live in `docs/ENGINEERING_RULES.md`. This
module is not the whole contract system. It owns shared contracts only; local
contracts can stay with their producing module when the data shape is local to
that boundary.

## Current Contents

| File | Role |
|:---|:---|
| `search_result.json` | Search and watchlist raw discovery result contract |
| `search_stats.json` | Search execution stats and diagnostics sidecar contract |
| `watchlist_stats.json` | Watchlist sidecar and source-health handoff contract |
| `verified_article.json` | Verify stage output contract |
| `article_record.json` | Normalize stage article contract, including lineage fields used by downstream stages |
| `story_cluster.json` | Cluster stage output contract |
| `validate_report.json` | Validate stage item-level findings and sidecar contract |
| `repair_report.json` | Repair stage action telemetry and sidecar contract |
| `signal_awareness.json` | Independent signal-awareness detection payload contract |
| `signal_plan.json` | Independent signal-awareness preparation plan contract |
| `capability_invocation.json` | Capability-layer MCP-ready invocation envelope contract |
| `capability_result.json` | Capability-layer MCP-ready result envelope contract |
| `agent_task.json` | Agent-facing task invocation envelope contract |
| `task_result.json` | Agent-facing task result envelope contract |
| `event_thread.py` | cross-temporal event-thread dataclasses and scale helpers |
| `report_window.py` | shared report profile + concrete date-window contract |
| `pipeline_artifacts.py` | stable stage artifact filename and artifact-type contract |
| `__init__.py` | re-export for `event_thread.py` |

## Boundaries

### Owns

- Define data shapes shared by multiple modules.
- Provide lightweight helpers such as scale-order lookup.
- Provide stable file locations for pytest schema and integrity tests.
- Preserve lineage fields that must cross stages, such as `engine`,
  `source_type_hint`, `canonical_url`, and `date_source`.
- Provide testable public structures for module-to-module and stage-to-stage
  handoffs.

### Does Not Own

- Does not contain domain knowledge.
- Does not access network, DB, or runtime filesystem data.
- Does not implement pipeline stage algorithms.

## Import Rule

Python dataclass contracts should be imported through the package root:

```python
from stratum.contracts import CrossTemporalState, BriefingRef
```

JSON Schemas are read by tests and stages through file paths.

`report_window.py` is the shared contract that keeps report scale/profile
separate from the actual covered date range. Standard periods such as
`2026-W22` still resolve normally, while custom user-selected windows use
stable ids such as `custom-2026-05-01_to_2026-07-31`.

## Discovery Contract Notes

`search_result.json` covers both Search API results and watchlist sidecar
results. `engine` is a free string because the actual source can be `bocha`,
`tavily`, or watchlist strategy IDs such as `rss:<source>` and
`direct_fetch:<source>`.

`search_stats.json` covers `raw.stats.json`, the Search execution and
quality diagnostics sidecar. It requires `queries` to preserve each
`QueryStats` record's `query_id`, engine, status, result count,
locale/intent/dimension, latency/error, and optional `include_domains`.
`diagnostics` covers locale/source-type/dimension output, source-type floor
gaps, domain-filter coverage, top source domains, and low-yield queries. This
contract protects DB query-stat ingest, Search recall debugging, and later
coverage tuning from field drift.

`watchlist_stats.json` covers the watchlist source-level health sidecar. It is
the shared contract between Watchlists and Monitoring, with each source's
access, status, hits, duration, dated count, and optional error. Unknown
watchlist access methods use `access: unknown` and `status: unsupported`, while
the error text preserves the original config value.

`date_source` records where the date came from. Current allowed values are
`search_api`, `web_extract`, `snippet_regex`, `url_path`, `freshness_window`,
and `none`. Verify and Normalize should preserve this field.
`date_confidence` is Verify's quality explanation for that lineage:
`search_api`, `web_extract`, and `url_path` are high; `freshness_window` is
medium; `snippet_regex` is low; `none` is none. Low-confidence records that
still pass the default policy carry `quality_flags` so downstream stages can
inspect the risk.

VerifiedArticle may carry `corroboration_score`, `corroboration_level`, and
`corroborating_sources`. These fields are evidence-strength annotations from
Verify's acceptance policy; they are not a default rejection gate.

`article_record.json` keeps display labels in `entities` and `terms` while
adding canonical `entity_ids` and `term_ids` for algorithm consumers. It also
keeps legacy `numeric_claims` as string snippets for compatibility and adds
`typed_numeric_claims`. Typed claims include `claim_type`, text, numeric value,
unit, direction, and metric, with current claim types covering price changes,
ASP, yield, capacity, CAPEX, shipments, and revenue.

`canonical_url` is the stable article identity key across Search, Watchlists,
Verify, and Normalize. The original `url` should remain available for lineage
and page opening, but dedupe, ArticleRecord `id`, and `content_hash` should
prefer the canonical URL.

ArticleRecord `source_locale` uses the same BCP47-style boundary as Search
query locales: language tags plus optional script/region subtags such as `en`,
`en-US`, `zh-CN`, `zh-cn`, or `zh-Hans-CN`.

`query_dimension` is the intent/dimension label passed from Search config into
Normalize, such as `baseline`, `verification`, or `supply_chain`. It must be
preserved on ArticleRecord so later analysis can identify which items came from
baseline search, verification search, or a dedicated coverage dimension.

`story_cluster.json` uses `article_ids` as the primary join key and also allows
`source_domains` and `canonical_urls` as audit fields. Those fields do not
replace `articles.jsonl`; they only support quick checks of source mix,
duplicate URLs, and cluster explainability.
StoryCluster id follows `sc-{domain_id}-{seq:04d}`. The `domain_id` part is
the domain directory id, so the schema allows lowercase letters, digits,
underscores, and hyphens.

## Pending Consolidation

`stratum/subsystems/story_tracking/story_contracts.py` remains a local
`stratum.subsystems.story_tracking` contract for now. If multiple subsystems depend on
EventRecord/CausalEdge/Judgment later, move those structures into
`stratum/contracts`.

`capability_invocation.json` and `capability_result.json` are additive
capability-layer transport-neutral envelopes for future MCP adapters. They do
not replace the underlying stage, subsystem, or DB contracts returned inside
the payload.

`agent_task.json` and `task_result.json` are additive task-layer
envelopes for future agent orchestrators. They are intentionally narrow and
must remain downstream of `stratum.capabilities`, not upstream of production
pipeline control.
