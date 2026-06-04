# watchlist - configured source acquisition layer

## Purpose

`stratum/sourcing/watchlist` directly acquires articles from RSS feeds and fixed
source-owned URLs defined in the domain source registry. It supplements cases
where broad Discovery APIs are unstable, miss pages, or rank evidence poorly.

Watchlist output is normalized to `SearchResult` and merged back into
`raw.json` by the orchestrator. Downstream enrich/verify/normalize code does
not need to know whether a result came from configured sources or broad
discovery.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for `collect(...)`, `collect_with_stats(...)`, and watchlist run/stat dataclasses |
| `models.py` | watchlist result/stat/channel dataclasses |
| `common.py` | shared source-domain extraction and source-type normalization |
| `registry.py` | loads `source_registry` from `domains/{domain}/domain.yaml` and applies `AcquisitionPolicy` access-tier and source-health ordering |
| `discovery.py` | review-only RSS/Atom/sitemap candidate discovery for active and review sources |
| `keywords.py` | builds domain keyword list and admission scores for watchlist candidates |
| `observations.py` | pre-admission structured observation records emitted by parsers/extractors |
| `source_expansion.py` | source expansion scoring from observation/candidate/result/raw funnel metrics |
| `rss_channel.py` | RSS acquisition channel orchestration and per-feed URL failure isolation |
| `url_channel.py` | fixed URL acquisition channel orchestration for `direct_fetch` and `browser` |
| `direct_fetch.py` | HTTP GET + HTMLParser article extraction |
| `rss.py` | RSS/Atom feed parsing |
| `browser.py` | Playwright-rendered extraction for JS-heavy pages |

## Acquisition Channels

Stratum treats fresh external acquisition as three separable channels:

| Channel | Code Owner | Source Config | Purpose |
|:---|:---|:---|:---|
| RSS | `rss_channel.py` + `rss.py` | `access: rss` | feed-based fresh items with cheap dated metadata |
| Fixed URL | `url_channel.py` + `direct_fetch.py`/`browser.py` | `access: direct_fetch` or `access: browser` | source-owned newsroom/blog pages, including JS-heavy pages |
| Broad Discovery | `stratum/sourcing/discovery/` | query YAML/DB + Bocha/Tavily config | gap exploration beyond configured sources |

Watchlist orchestration only owns RSS and fixed URL channels. Bocha/Tavily are
kept in the discovery subsystem so provider routing, query planning, engine
health, and broad discovery result curation can evolve independently.

## Contract

```python
from stratum.sourcing.watchlist import collect, collect_with_stats

results = collect("storage", workspace="/repo", run_date="2026-05-30")
run = collect_with_stats("storage", workspace="/repo", run_date="2026-05-30")
```

All strategy modules return `list[SearchResult]` with:

- `url`
- `title`
- `snippet`
- `locale`
- `published_at`
- `source_domain`
- `source_type_hint`
- `engine` such as `direct_fetch:micron-newsroom`
- `query_id` strategy/source identifier

Before admission scoring, watchlist parsers and extractors also emit
`watchlist_observations.jsonl`. Observations are the first structured layer
after RSS XML, fixed URL HTML, or browser-rendered DOM is parsed. They include
minimal article/link fields such as source, access, URL, title, snippet,
publication date, locale, source domain/type, engine, query id, parser, observed
time, and source URL. Observations must not include admission fields such as
`status`, `score`, `reason`, or `matched_keywords`; those belong in
`watchlist_candidates.jsonl`.

RSS admission is score-based rather than a hard keyword gate. Exact domain
keyword matches are accepted, while storage-sector weak signals can enter
`raw.json` as lower-confidence candidates for downstream verify/normalize
gates. This prevents broad feeds from dropping edge signals only because the
title/snippet missed the current keyword list.

Source discovery is review-only. It can scan active source definitions and
`candidate_sources` for RSS/Atom feeds, common feed paths, and sitemap paths.
Discovered candidates are written with `status: review`; they are not
auto-enabled in `source_registry`.

Source expansion scoring is an algorithm helper, not a default pipeline
artifact. `source_expansion.py` can read `watchlist_observations.jsonl`,
`watchlist_candidates.jsonl`, `watchlist_results.json`, and final `raw.json` to
compute per-source funnel metrics and recommendations such as promote,
deprioritize, investigate parser, or improve date extraction. It does not edit
domain configuration, enable sources automatically, or write run artifacts
unless explicitly invoked by a caller.

Source definitions may set `resolve_article_dates: true` for `direct_fetch`
sources that need article-detail pages to expose publication dates. This is
opt-in because some corporate sites are slow or unreliable; without it,
`direct_fetch` only trusts URL/local-context dates and leaves uncertain dates
blank for downstream enrichment/verification.

Direct URL sources can also define source-specific adapter hints:
`article_selector` or `list_selector` for stable article-link anchors,
`pagination` for configured list-page expansion, and `sitemap_fallback: true`
with optional `sitemap_urls` when list pages are incomplete. These adapters stay
inside the URL channel; if list-page extraction returns fewer than the source
budget, sitemap fallback may top up the remaining candidates. The acquisition
stage only receives normalized raw records.

`source_domain` must be the article URL's domain, not the feed/list-page domain.
Watchlist host normalization strips only exact presentation prefixes (`www.`,
`m.`), preserving meaningful subdomains such as `ww2.example.com` for source
health and downstream labels.
`source_type_hint` must use the canonical source types accepted by the article
contract: `official`, `analyst`, `media`, `blog`, `social`, or `unknown`.
Collection categories such as `newsroom`, `press`, and `rss` are normalized by
`common.normalize_source_type()`.

`collect()` is the backward-compatible result-only API. `collect_with_stats()`
returns a `WatchlistRun` compatibility contract with `results` and
`source_stats`. Each source stat
includes source id, access type, status, hit count, duration, locale/category,
dated count, selected count, and error text when present. The orchestrator
writes this to `watchlist_stats.json` and forwards it to Monitoring health
records.
The package entrypoint `stratum.sourcing.watchlist` is the stable import surface
for `collect`, `collect_with_stats`, `WatchlistRun`, and watchlist source-stat
dataclasses; external callers should prefer it over reaching into the package
implementation layout unless they intentionally depend on a specific channel or
parser module.
`hits` means the source's collected candidates; `selected` means the number of
that source's candidates that survived canonical URL merge into `raw.json`.
Orchestrator selected-count attribution uses the watchlist `engine`
`strategy:source_id` value, not the strategy-prefixed `query_id`, so health
records line up with source registry ids such as `storagenewsletter-rss`.
Valid source-stat statuses are `ok`, `empty`, `error`, and `unsupported`.
`empty` is reserved for a successful scan that found no matching candidates.
HTTP/fetch/parser failures in strict orchestrator collection are reported as
`error`, so Monitoring can distinguish a quiet source from a broken one.
Unsupported access methods are reported with `access: unknown` plus an error
message naming the configured access value, keeping the sidecar schema stable
while still surfacing configuration mistakes.

`registry.get_active_sources()` applies `source_registry.defaults` by access
type before dispatch, then orders active sources with the runtime
`AcquisitionPolicy`. Defaults such as `max_articles_per_url` and
`timeout_seconds` are normalized to the strategy-facing keys `max_articles` and
`timeout`, while explicit source-level settings still win. This keeps per-source
definitions compact without making defaults decorative.
Source health can tune fetch budgets after priority ordering. Healthy,
high-yield sources may receive a larger `max_articles` budget; repeatedly dry
sources are reduced but remain available; date-poor URL/browser sources are
marked for detail-page date resolution.

## Boundaries

### Owns

- Read source definitions from domain config.
- Dispatch by acquisition channel: RSS or fixed URL.
- Extract candidate article links and lightweight metadata.
- Return normalized `SearchResult` objects.
- Normalize watchlist categories into canonical source types.
- Emit structured per-source health stats for the orchestrator.
- Provide source expansion scoring from persisted sidecars when explicitly
  invoked.
- Accept prior source health from the orchestrator and pass it to
  `AcquisitionPolicy`; watchlist execute the ordered list but do not own the
  ordering algorithm.
- Respect the active source list returned by registry after `AcquisitionPolicy`
  applies optional source budgets; watchlist do not own cost or budgeting
  decisions.

### Does Not Own

- Do not verify truth, freshness, duplicates, or blocklists. Verify stage owns that.
- Do not classify entities/terms. Normalize stage owns that.
- Do not write pipeline outputs. Orchestrator owns merging into `raw.json`.
- Do not contain domain-specific source lists. Domain config owns source registry.

## Failure Policy

Individual source failures are isolated and logged. A broken source should not
break all collection. The dispatcher calls strategy modules in strict mode, so
network/fetch failures and malformed RSS/Atom XML become source-level `error`
stats instead of being misreported as valid empty scans. Strategy-level
`collect()` helpers remain best-effort for manual use.
For RSS sources with multiple feed URLs, URL failures are isolated: remaining
URLs still run. If at least one URL yields candidates, the source remains `ok`
and the failed URL detail is retained in `error`; if all URLs fail, the source
is reported as `error`.

`browser.py` requires the optional browser extra:

```bash
pip install -e '.[browser]'
playwright install chromium
```

If browser sources are active and Playwright is missing, `browser.py` raises `BrowserWatchlistUnavailable` with that installation hint; the watchlist dispatcher logs the source-level failure.
This runtime-capability miss is reported as `status: unsupported` with
`access: browser`, not as a generic source `error`, so Monitoring can distinguish
missing optional infrastructure from a failing upstream source. The orchestrator
records unsupported watchlist health entries as `scanned: false`, so missing
optional runtime dependencies do not create dry-source or HTTP-error alerts.
Browser sources may explicitly set `fallback_access: direct_fetch`. In that
case a missing Playwright runtime triggers one static HTML attempt before the
source is marked unsupported. The stat keeps `access: browser` and records the
fallback in `error`, so dashboards still show the source's configured strategy
while default installs can recover any server-rendered official links.

## Dependencies

- `requests`
- optional `playwright`
- `domains/{domain}/domain.yaml`
- `stratum.sourcing.discovery.SearchResult`
