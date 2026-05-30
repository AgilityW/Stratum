# collectors - search 之外的内容采集层

## Purpose

`stratum/collectors` 负责从 domain source registry 中定义的来源直接采集文章，补足 search API 不稳定、漏抓或排序偏差的问题。

Collector 产物统一是 `SearchResult`，由 orchestrator merge 回 `raw.json`，因此下游 enrich/verify/normalize 不需要知道结果来自 search 还是 collector。

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | single entry point: `collect(domain, workspace, run_date)` |
| `common.py` | shared source-domain extraction and source-type normalization |
| `registry.py` | loads `source_registry` from `domains/{domain}/domain.yaml` |
| `keywords.py` | builds domain keyword list and filters feed items |
| `direct_fetch.py` | HTTP GET + HTMLParser article extraction |
| `rss.py` | RSS/Atom feed parsing |
| `browser.py` | Playwright-rendered extraction for JS-heavy pages |

## Contract

```python
from stratum.collectors import collect, collect_with_stats

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

Source definitions may set `resolve_article_dates: true` for `direct_fetch`
sources that need article-detail pages to expose publication dates. This is
opt-in because some corporate sites are slow or unreliable; without it,
`direct_fetch` only trusts URL/local-context dates and leaves uncertain dates
blank for downstream enrichment/verification.

`source_domain` must be the article URL's domain, not the feed/list-page domain.
Collector host normalization strips only exact presentation prefixes (`www.`,
`m.`), preserving meaningful subdomains such as `ww2.example.com` for source
health and downstream labels.
`source_type_hint` must use the canonical source types accepted by the article
contract: `official`, `analyst`, `media`, `blog`, `social`, or `unknown`.
Collection categories such as `newsroom`, `press`, and `rss` are normalized by
`common.normalize_source_type()`.

`collect()` is the backward-compatible result-only API. `collect_with_stats()`
returns a `CollectorRun` with `results` and `source_stats`. Each source stat
includes source id, access type, status, hit count, duration, locale/category,
dated count, selected count, and error text when present. The orchestrator
writes this to `collector_stats.json` and forwards it to Monitoring health
records.
`hits` means the source's collected candidates; `selected` means the number of
that source's candidates that survived canonical URL merge into `raw.json`.
Orchestrator selected-count attribution uses the collector `engine`
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
type before dispatch. Defaults such as `max_articles_per_url` and
`timeout_seconds` are normalized to the strategy-facing keys `max_articles` and
`timeout`, while explicit source-level settings still win. This keeps per-source
definitions compact without making defaults decorative.

## Boundaries

### 做什么

- Read source definitions from domain config.
- Dispatch by `access`: `direct_fetch`, `rss`, `browser`.
- Extract candidate article links and lightweight metadata.
- Return normalized `SearchResult` objects.
- Normalize collector categories into canonical source types.
- Emit structured per-source health stats for the orchestrator.

### 不做什么

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

If browser sources are active and Playwright is missing, `browser.py` raises `BrowserCollectorUnavailable` with that installation hint; the collector dispatcher logs the source-level failure.
This runtime-capability miss is reported as `status: unsupported` with
`access: browser`, not as a generic source `error`, so Monitoring can distinguish
missing optional infrastructure from a failing upstream source. The orchestrator
records unsupported collector health entries as `scanned: false`, so missing
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
- `stratum.subsystems.search.models.SearchResult`
