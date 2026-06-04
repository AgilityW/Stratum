# Stratum module review

This document tracks the ongoing module-by-module review. The review standard is:

- Design: clear ownership, boundaries, and extension points.
- Flexibility: adding a domain/source/engine/stage should avoid framework rewrites.
- Readability: local code should reveal intent without archaeology.
- Testability: important behavior should have deterministic unit tests.
- Effectiveness: the module must improve briefing quality in real runs, not just pass tests.

## Review order

| Area | Status | Notes |
|:---|:---|:---|
| Search | Reviewed and fixed | Tavily restored, DB/YAML query fallback added, source-type classification and diagnostics improved. |
| Collectors | Reviewed and fixed | Date poisoning fixed; browser dependency gap documented; RSS/direct tests expanded. |
| Enrich/Verify/Normalize | Reviewed and fixed | Locale preservation fixed; date and quality gates reviewed. |
| Cluster/Edit/Validate/Render | Reviewed and fixed | Future-date validation and render tags fixed; LLM boundary reviewed. |
| DB/Story Tracking | Reviewed and fixed | Judgment thread targets preserved in story context. |
| Monitoring | Reviewed and fixed | Coverage fallback now uses cluster source/locale summaries. |
| Orchestrator | Reviewed and fixed | `--from-stage` now actually gates stage execution. |
| Contracts/Docs | Reviewed and fixed | JSON schemas now cover current Search/Collectors shapes and require downstream lineage fields. |
| Domains/Config | Reviewed and fixed | Query templates are now single-sourced in `queries.yaml`; config integrity tests added. |
| Tooling/Infra | Reviewed and fixed | Makefile focused test targets and package metadata now match current project shape. |
| Data Integrity Tests | Reviewed and fixed | Runtime artifact checks now follow current `{domain}/data/{date}` layout and current sidecars. |
| Prompt/LLM Boundary | Reviewed and fixed | LLM payloads no longer leak through command argv; edit titles and source rules now align with domain config. |

## Search review

### What was good

- The high-level split is healthy:
  - `stages/search/search.py` owns query loading and CLI.
  - `subsystems/search/config.py` adapts project/domain config.
  - `engine.py` owns API-specific payloads.
  - `executor.py` owns concurrency/retry/fallback.
  - `curator.py` owns scoring/pruning.
- Search is domain-agnostic at the framework level.
- Result output preserves compatibility fields for downstream stages.
- Unit tests already covered models, scoring, pruning, config loading, and basic engine construction.

### Problems found

- Tavily date filtering used `start_date == end_date`, which Tavily rejects with HTTP 400. This silently collapsed all Tavily queries into `all engines exhausted`.
- `site:` queries were sent as raw query text instead of using Tavily `include_domains`; this weakened site-first search.
- DB query loading only included `detection` queries, leaving active `verification` queries unused.
- Executor diagnostics hid useful engine errors, making real failures hard to debug.
- Search config read source classification from an obsolete location instead of `pipeline.source_classification`, so all curated results were scored as `media`.
- Query stats lacked locale/intent, limiting observability.
- Search stats did not explain curation quality. A run could show total raw/curated counts while hiding whether official/analyst floors were missed, which locales were low-yield, or which domains dominated before pruning.
- Search config mixed company aliases into `classifications`, but downstream code interprets that map as source types. This could classify `news.samsung.com` as synthetic `company` instead of `official`, weakening official-source weights and source-type quotas.
- When a SQLite DB file existed but had no active daily queries, Search skipped `queries.yaml` and could run with zero queries.
- Engine clients were constructed even when their API key was missing. This made Search spend time on predictable auth failures instead of immediately falling back to a usable engine or reporting clear per-query diagnostics.
- DB seeding already understood structured queries, but Search's YAML loader still assumed the legacy `seed_queries` shape. That made query strategy evolution fragile.
- Storage needed coverage dimensions such as technology, product, platform demand, supply chain, pricing, and financials. A flat locale query list could not say which briefing surface a query was meant to cover.
- Search curation code could match entity/term aliases, but `load_search_config()` only passed English and Simplified Chinese names. This weakened relevance scoring and entity-diversity caps for Japanese, Korean, Traditional Chinese, and other locale results.
- Search and collector merge deduped by exact URL only. Tracking parameters, fragments, trailing slashes, and common mobile host variants could let the same article occupy multiple slots.
- Verify still deduped by exact URL even after Search started emitting `canonical_url`, so raw inputs or collector/search merge variants could leak through later.
- Source-type classification used loose substring matching. That let impostor
  or unrelated hosts such as `notreuters.com` or `fakesamsung.com` inherit the
  configured treatment for `reuters.com` or `samsung.com`, distorting source
  weights and evidence-mix quotas.
- Tavily broad queries used a single static `topic` setting. `news` is useful for time-sensitive discovery, but verification, financial, pricing, supply-chain, and professional source queries often need `general` to surface primary or non-news pages.
- Search per-query `results_count` used engine raw return size, while `raw.json` and `total_raw` used canonical URL dedupe. Duplicate URL variants from one query could therefore inflate DB query hit counters.
- Stage Search accepted `--config`, but `load_search_config()` always read
  `workspace/config.yaml`. Alternate config files therefore changed the
  workspace directory but not the actual Search engine/routing/curation policy.
- Stage Search's simple `queries: intent -> locale -> list` loader only
  recognized narrow two-part locale keys. BCP 47 variants such as `en-US`,
  `zh-cn`, or `zh-Hans-CN` could be mistaken for dimensions and silently drop
  query items.
- Executor routing only matched locales exactly. A valid query locale variant
  could therefore miss the configured parent route, such as `zh-Hans-CN`
  falling past `zh-CN` and losing the intended Bocha-first engine chain.
- Tavily locale-scoped `include_domains` also matched locales exactly. After
  locale variant routing, a query such as `en-US` could reach Tavily but lose
  the `en` source filters that make source-first search stronger.
- Source-first Search still depended on embedding `site:` operators inside
  query text. That worked but mixed query semantics with engine syntax, made
  official-source recall harder to configure cleanly, and left no structured
  path for per-query Tavily domain filters.

### Fixes made

- Tavily now sends a non-empty date window: `start_date = run_date`, `end_date = run_date + 1 day`.
- Tavily converts `site:domain.com` syntax to `include_domains` and removes the `site:` token from the query.
- DB query loading includes both `detection` and `verification` intents.
- Executor preserves concrete failure messages, distinguishes `no_results`, and reports locale/intent in `QueryStats`.
- `raw.stats.json` now includes a `diagnostics` block with raw-vs-curated locale/source-type/dimension coverage, configured source-type floor gaps, low-yield query records, and top source domains before/after curation.
- Per-query Search stats now retain `include_domains` for scoped queries,
  including low-yield/no-result diagnostics, so weak recall can be traced to
  domain-scoped searches versus broad search failures.
- Search diagnostics now include `domain_filter_coverage`, summarizing how many
  scoped queries targeted each include domain and how many raw/curated results
  each domain produced.
- Source classification now reads `domain.yaml` `pipeline.source_classification`.
- Company aliases are kept out of source-type classification and remain used for entity scoring/diversity only.
- The orchestrator now passes both DB and `queries.yaml` to Search. Search prefers active DB queries but falls back to the YAML baseline when the DB is empty or has an unusable query table.
- Engine factory now skips engines without API keys. The executor can still fall back to the next routed engine, and a no-usable-engine run produces per-query failed stats instead of an opaque empty result set.
- Executor now skips engines that cannot honor `include_domains` for
  source-scoped queries, then falls through to a compatible engine such as
  Tavily. This prevents Chinese source-scoped queries from being broadened by
  Bocha before Tavily gets a chance to apply domain filters.
- Search YAML loading now uses the structured `queries` schema, supporting both `queries: intent -> locale -> list` and `queries: intent -> dimension -> locale -> list`, aligned with DB seeding.
- Storage queries are now split by explicit intent and briefing dimension, including `platform_demand` for NVIDIA/AI platform architecture signals that drive memory/storage demand.
- Search config now preserves all company and term aliases from `domain.yaml`, and term scoring consumes aliases instead of English names only.
- SearchResult now computes `canonical_url`; executor, curation, and collector/search merge use it for dedupe while preserving the original `url`.
- Search/Normalize source classification now uses domain-boundary matching.
  Domain patterns match exact hosts and subdomains, while path-like patterns can
  still match either URL paths or equivalent subdomain forms.
- Search executor now dedupes each query's engine results by canonical URL before reporting `results_count`, keeping `raw.stats.json` and SQLite query counters aligned with unique evidence.
- Verify now preserves `canonical_url` and uses canonical URL keys for duplicate rejection.
- Curation now supports `min_per_source_type` so available official/analyst/media evidence cannot be crowded out solely by higher-volume media results.
- Curation now supports `max_per_entity` so one high-frequency company/entity cannot dominate the curated pool after the source-type evidence floor has been reserved.
- Tavily topic selection is now query-aware. Site-filtered/domain-scoped queries use `general`; broad queries can override the engine default by intent or dimension through `topic_by_intent` and `topic_by_dimension`.
- The executor now passes query intent and dimension into engine calls, so API payload choices can reflect the query's job instead of only its locale/text.
- Search now passes the exact Stage 1 `--config` path into the subsystem; config
  loading reads `.env` next to that selected file and no longer implicitly
  falls back to `workspace/config.yaml`.
- Stage Search now recognizes BCP 47-style locale keys in the simple query YAML
  form, so locale variants remain query locales rather than being parsed as
  dimensions.
- Executor routing now tries compatible locale parents before the generic
  fallback, keeping script/region variants on the strongest configured engine
  chain.
- Tavily include-domain lookup now also walks compatible locale parents, so
  source filters survive BCP 47 script/region variants.
- Structured Search queries can now carry `include_domains`. Stage Search
  preserves the field, the executor passes it to engines, and Tavily combines
  those query-scoped domains with locale-level filters and legacy `site:`
  filters.
- Storage query templates now use structured `include_domains` instead of
  embedding `site:` operators in query text; a domain-config regression test
  prevents query files from drifting back to the old syntax.
- SQLite query seeding and DB-backed query loading now persist `include_domains`
  as JSON, so source-first Search survives the YAML -> DB path instead of
  widening into generic web search after seeding.
- Tests were added for executor diagnostics and query metadata propagation, Tavily date/site/topic helpers, verification query loading, DB-empty fallback, missing-key fallback, curation diagnostics, dimensioned YAML query strategy loading, multilingual alias scoring, canonical URL dedupe, source-classification boundary matching, and classification loading.
- Added a regression test proving explicit Search config paths override the
  default `config.yaml` in the same workspace.
- Added Search regression tests for BCP 47 query-locale parsing and parent
  locale engine routing.
- Added Tavily include-domain fallback coverage for parent locale variants.
- Added regression coverage for YAML `include_domains` parsing, executor
  propagation, and Tavily payload generation.
- Added domain-config coverage requiring source-scoped query files to use
  structured domain filters rather than `site:` query operators.
- Added DB regression coverage for seeding, reading, and scale-helper
  propagation of `include_domains`.
- Added Search stats regression coverage proving domain-scoped low-yield
  queries expose their `include_domains` in diagnostics.
- Added executor regression coverage proving domain-scoped queries skip engines
  that cannot apply `include_domains`.
- Added diagnostics regression coverage for per-domain yield from
  `include_domains` queries.

### Real-run effect

Using `storage` on `2026-05-30`:

Before:

- Loaded 53 DB queries.
- `20/53` queries OK.
- `33` failed.
- `87` raw results.
- `45` curated results.
- Curated engine mix: Bocha only.

After:

- Loaded 60 DB queries.
- `59/60` queries OK.
- `0` failed, `1` no-results.
- `324` raw results.
- `150` curated results.
- Curated engine mix: `130` Tavily, `20` Bocha.
- Locale coverage: `30` each for en, zh-CN, ja, ko, zh-TW.
- Source type coverage includes analyst sources instead of treating everything as media.

### Remaining Search questions

- Official-source recall is still mostly handled by collectors; Search did not surface many official newsroom results in the reviewed run.
- Tavily broad-query topic tuning is now configurable by intent/dimension. The next effectiveness check is to compare real-run yield by dimension and adjust the Storage defaults with evidence from `raw.stats.json`.
- Curation now enforces a configured source-type floor and a single-entity diversity cap when configured.
- Search query sourcing is now safer operationally: DB-backed discovery can evolve, but an empty DB no longer suppresses the domain's baseline query strategy.
- Missing API keys are now explicit operational signals. They no longer cause avoidable network retries, and they do not block fallback to another keyed engine for the same locale.
- Site-first and source-mix tuning now has a concrete feedback surface: source-type shortfalls and low-yield query records can be read directly from `raw.stats.json`.
- Query strategy can now evolve without changing Search code: baseline queries can stay simple while storage uses explicit detection/verification intent groups plus coverage dimensions.
- Multilingual results are now scored and diversity-capped with the same entity/term vocabulary as English and Simplified Chinese results, which makes locale expansion more meaningful.
- Duplicate URL pressure is lower: Search and collectors now treat common URL variants as the same article before they consume curated evidence slots.
- Query hit counters now track canonical-unique evidence per query rather than raw engine duplicates, so query quality history is less sensitive to mobile/tracking URL variants.
- The canonical URL contract now carries through Verify, so downstream stages get the same identity key even when raw input did not originate from the current Search stage.

## Collectors review

### What was good

- `collectors` has the right architectural purpose: fixed trusted sources are fetched outside generic Search, then normalized to `SearchResult` so downstream stages do not care whether a record came from search or a collector.
- Source ownership is correctly domain-scoped in `domains/{domain}/domain.yaml` under `source_registry`.
- Strategy modules are separated by access pattern:
  - `direct_fetch.py`: static newsroom/blog pages.
  - `rss.py`: RSS/Atom feeds.
  - `browser.py`: JS-rendered pages via optional Playwright.
- Per-source failures are isolated; one broken source does not stop the whole collection run.
- Browser dependency failure is explicit and actionable instead of silent.

### Problems found

- `direct_fetch` used the whole list page to infer every article's `published_at`. On the Storage run for `2026-05-30`, Micron list-page text about an upcoming `June 24, 2026` earnings event was assigned as the publication date for unrelated articles. That is a serious effectiveness bug because downstream freshness checks rely on dates.
- `direct_fetch` date extraction had no future-date sanity check.
- Article title extraction did not consistently unescape HTML entities or normalize whitespace.
- Optional article-detail date fetching is useful but can be slow or hang on some corporate sites. It should be opt-in per source, not unconditional.
- Browser-backed sources are active for Samsung and Western Digital, but the default local test/runtime does not include Playwright. In a default install those official sources are skipped, which weakens official-source recall.
- Collector run logging reported only counts, not structured source health metrics. Monitoring had source health pieces, but collectors did not emit a first-class per-source stats file.
- Collector `source_domain` could describe the feed/list page instead of the article URL, and `category: newsroom` was passed through as `source_type_hint` even though downstream contracts expect canonical types such as `official`.
- Collector host normalization used `lstrip("www.")`, which strips any leading
  `w` or `.` characters rather than the exact `www.` prefix. Hosts such as
  `ww2.example.com` could therefore be corrupted in collector source-domain
  stats and downstream labels.
- `source_registry.defaults` existed in `domain.yaml`, but active source loading did not merge per-access defaults into source definitions. New sources without explicit timeout/article limits therefore ignored the domain-level defaults reviewers expected to apply.
- Collector dispatch emitted `status: unsupported` for unknown access methods, but collector stats integrity checks and docs did not accept that status. A typo in a source registry could therefore produce a valid diagnostic sidecar that tests/consumers treated as invalid.
- Missing optional Playwright runtime for `access: browser` sources was reported
  as a generic source `error`. That made infrastructure capability gaps look
  like upstream source failures in collector stats and Monitoring.
- Browser-backed official sources had no configured static fallback. In a
  default environment without Playwright, Storage skipped Samsung/Western
  Digital/Kioxia-style official pages entirely even when their initial HTML
  might expose usable article links.
- Collector health wrote `selected = hits`, even though orchestrator merge can drop duplicate canonical URLs before writing `raw.json`. Monitoring could therefore overstate a fixed source's actual contribution.
- `direct_fetch` and `rss` strategy helpers swallowed HTTP/fetch failures and
  returned an empty result list. The dispatcher then recorded those broken
  sources as `empty`, making upstream failures look like successful quiet scans.
- RSS XML parse failures were also swallowed inside feed parsing, so a broken
  feed could look like a valid feed with zero matching articles.
- Multi-URL RSS sources were not isolated per URL in strict dispatch. One bad
  feed URL could stop the whole source before later feed URLs were attempted.
- Collector selected-count attribution preferred `query_id`, but real collector
  query ids are strategy-prefixed (`df-*`, `rss-*`, `b-*`) while source stats use
  source-registry ids. This could undercount selected contribution for real
  collector sources even when merge kept their articles.

### Fixes made

- `direct_fetch` no longer uses the full list page as a publication-date fallback for heading links.
- Added optional article-detail date resolution via `resolve_article_dates: true`, with concurrent workers and short per-request timeout. It is available for sources that need it but is not forced on every source.
- Added future-date sanity: dates more than one day after `run_date` are discarded.
- Normalized extracted title text with HTML unescape and whitespace collapsing.
- `read_more` fallback now uses only local surrounding markup as fallback context, and discards implausible future dates.
- Added `collect_with_stats()` and `CollectorRun` so every source emits status, count, duration, dated count, locale/category, and error text.
- The orchestrator now writes `collector_stats.json` and appends collector source health to Monitoring NDJSON.
- Collectors now derive `source_domain` from each article URL and normalize collection categories (`newsroom`, `rss`, etc.) into canonical source types.
- Collector host normalization now removes only known presentation prefixes
  (`www.`, `m.`) and preserves real subdomains such as `ww2.example.com`.
- Source registry loading now applies per-access defaults before dispatch, normalizing `max_articles_per_url` and `timeout_seconds` to the strategy-facing `max_articles` and `timeout` keys while preserving explicit source overrides.
- Unsupported collector access methods now produce a stable stats shape: `status: unsupported`, `access: unknown`, and an error message containing the configured access value.
- Missing optional Playwright runtime for browser-backed sources now produces
  `status: unsupported` with `access: browser`, preserving the installation hint
  while avoiding false source-error alerts.
- Browser sources can opt into `fallback_access: direct_fetch`. Storage enables
  this for browser defaults, so missing Playwright first attempts a static HTML
  extraction before giving up on official-source recall.
- Collector sidecars and source health now distinguish `hits` from `selected`: `hits` is collected candidates, while `selected` is the post-merge canonical-unique contribution to `raw.json`.
- `collect_with_stats()` now calls direct-fetch/RSS strategies in strict mode:
  real fetch failures become source-level `status: error`, while `empty`
  remains reserved for successful scans with no matching candidates.
- RSS strict mode now propagates malformed XML parse failures to the dispatcher
  so broken feeds are tracked as source errors.
- Multi-URL RSS dispatch now isolates failures per URL. Later feed URLs still
  run; partial failures are retained in the source stat `error`, while all-URL
  failures become `status: error`.
- Collector selected counts now derive source ids from `engine`
  (`strategy:source_id`) before falling back to normalized query ids, keeping
  Monitoring attribution aligned with source registry ids.
- Added tests that lock the key regression: list-page event dates must not override article-page publication dates.
- Added collector host-normalization regression coverage for `www.`, mobile,
  and non-presentation subdomains.
- Added a collector registry test proving per-access defaults apply only to active sources and do not override source-specific settings.
- Added collector stats integrity coverage for `unsupported` status and stable unknown-access reporting.
- Added collector dispatcher coverage proving missing browser runtime is
  surfaced as `unsupported`, not a generic source error.
- Added collector dispatcher coverage proving configured browser sources use
  direct-fetch fallback when Playwright is unavailable.
- Added collector dispatcher/strategy coverage proving direct-fetch and RSS
  fetch failures are recorded as `error`, not `empty`.
- Added RSS strict-mode coverage proving malformed feeds raise parse errors
  instead of producing false empty scans.
- Added collector dispatcher coverage proving a multi-URL RSS source keeps good
  feed results while surfacing the failed URL in source stats.
- Added orchestrator regression coverage proving selected counts are attributed
  to the source-registry id when collector results use strategy-prefixed query
  ids.
- Added orchestrator tests proving collector `selected` counts follow canonical URL merge, including duplicate collector results.

### Real-run effect

Using `storage` collectors on `2026-05-30`:

- Total collected: `43` records.
- Sources contributing: Micron newsroom/blog, SK hynix newsroom, Western Digital blog, ServeTheHome RSS, StorageNewsletter RSS, SemiEngineering RSS.
- Browser sources skipped because Playwright is not installed in the default environment.
- Before the fix, many Micron articles were incorrectly marked as future `2026-06-24`.
- After the fix, future poisoned dates are gone: `FUTURE []`.
- Date coverage is lower (`16` dated, `27` undated), but this is preferable to wrong dates. Undated collector records can be enriched via explicit web extraction or rejected by verify.

### Remaining Collectors questions

- Decide whether production daily runs should install Playwright by default. Without it, Samsung Semiconductor and Western Digital newsroom coverage is intentionally skipped.
- Decide source-by-source where `resolve_article_dates: true` is worth the latency. It is accurate when corporate pages expose article dates, but some corporate sites are slow enough that it should stay configurable.
- Collector stats now exist as a run sidecar and Monitoring feed. Monitoring now has aggregate alert thresholds over dry streak, contribution drought, current HTTP error streaks, and dated metadata ratio.
- Add a freshness policy knob. Today collectors gather candidates and let downstream verify decide. For high-volume feeds, a configurable `max_age_days` could reduce noise earlier.

## Enrich / Verify / Normalize review

### What was good

- The three-stage split is useful:
  - `enrich` fills missing dates but preserves record count.
  - `verify` applies deterministic quality gates and writes per-record decisions.
  - `normalize` converts verified records into stable ArticleRecords.
- Date validation, blocklist, low-priority filtering, duplicate checks, magnitude sanity, source classification, artifact classification, entity/term extraction, and locale routing are all covered by unit tests.
- The config-driven design keeps domain policy in `domain.yaml` instead of burying storage-specific rules in stage code.

### Problems found

- `normalize` ignored explicit upstream `locale` values from Search/Collectors and guessed from URL only. This can misclassify sources such as `eet-china.com`, because URL heuristics are never as reliable as an explicit query/source locale.
- `verify` preserves useful upstream metadata under `raw_metadata`, but `normalize` did not read locale from that metadata.
- `normalize` wrote `canonical_url` as the raw `url`, and its `id`/`content_hash` used raw URL variants. That broke the stable identity chain established by Search and Verify.
- `normalize` reclassified source type from URL even when Search/Collectors already provided `source_type_hint`, and it dropped useful execution metadata such as `engine`, `query_id`, `query_dimension`, and `discovery_mode`.
- Normalize's URL fallback source classification shared the old loose substring
  behavior, so fake or unrelated domains could inherit official/analyst/source
  types from configured domain fragments.
- Normalize's `thread_keywords.json` matching returned every keyword/topic from the matched thread as article `terms`, even if most of those words never appeared in the article. That could pollute downstream clustering with unrelated thread vocabulary.
- `enrich` can still extract event dates from title/snippet text if an undated collector/search record mentions a future event. `verify` catches most of these through `FUTURE`, but the date_source should be treated as lower confidence than API or URL dates.
- `enrich` only inspected the first regex match for each date pattern. If a
  snippet mentioned a future event date before a valid publication date in the
  same format, the valid date was skipped.
- `enrich` relabeled every existing `datePublished` as `search_api`, even when
  upstream had already supplied `date_source` such as `url_path` or
  `web_extract`. It also ignored `published_at` when `datePublished` was absent.
- `verify` preserved upstream `date_source` when present, but if it inferred a date from title/snippet text or accepted unlabelled metadata dates, the verified record could still carry blank lineage.
- `date_source` existed as lineage, but Verify treated all accepted dates equally. Snippet regex dates and freshness-window inference are weaker evidence than API, web metadata, or URL-path dates.
- `verify` blocklist matching used loose substring checks, so an unrelated host
  like `notyoutube.com` could be rejected. Low-priority matching had the
  opposite problem: exact matching missed subdomains such as `news.google.com`.
- `verify.py` has a small readability wart in its module docstring/import area, but no behavioral impact.

### Fixes made

- Added `resolve_source_locale()` in `normalize`: it now prefers `article.locale`, then `article.raw_metadata.locale`, and only falls back to URL heuristics if no explicit locale exists.
- Added a regression test that ensures explicit `zh-CN` wins over `eet-china.com` URL heuristics.
- Normalize now preserves or recomputes canonical URL, and uses canonical URL plus title for `id` and `content_hash`.
- Normalize now prefers upstream `source_type_hint`/`source_type` over URL heuristics, with aliases such as `newsroom -> official` and `rss -> media`.
- Normalize's fallback URL classification now shares Search's domain-boundary
  matcher, keeping source typing consistent after the Search curation boundary.
- Normalize now carries `engine`, `query_id`, `query_used`, `query_dimension`, and `discovery_mode` into ArticleRecord output for downstream diagnostics.
- Thread keyword matching now returns only keywords/topics actually present in the article text; unmatched thread vocabulary can assign no terms and cannot pollute ArticleRecord `terms`.
- `enrich` now rejects implausible future publication dates from snippet, URL, and web metadata extraction instead of letting future event dates become article dates.
- `enrich` now keeps scanning later matches within the same date pattern, so a
  future event date no longer hides a later plausible publication date.
- Enrich now preserves existing non-`none` date lineage and uses `published_at`
  as the upstream date when `datePublished` is absent, keeping Search/Collector
  contracts compatible with the stage.
- `date_source` is now preserved through `verify` and `normalize`, and required on the ArticleRecord schema as lineage.
- Verify now fills missing date lineage deterministically: unlabelled metadata dates become `search_api`, Verify-side title/snippet extraction becomes `snippet_regex`, and no-date rejections emit `none`.
- Verify now maps `date_source` to `date_confidence`, carries low-confidence
  dates as `quality_flags`, and supports `pipeline.date_window.min_date_confidence`
  for domains that want to reject weak date evidence.
- Normalize preserves `date_confidence` and `quality_flags` on ArticleRecord so
  date-quality signals survive beyond Verify.
- Verify now writes `verified.stats.json` with totals, rejection reasons,
  date-confidence counts, and quality-flag counts, so rejected records no longer
  require scanning JSONL or stderr to debug a thin evidence set.
- Verify blocklist and low-priority source policy now use the shared
  host-boundary matcher: configured roots match exact hosts and subdomains, but
  not impostor domains.
- Cleaned the Verify module docstring/import area so the file header reflects executable code clearly.

### Remaining questions

- Date lineage now feeds deterministic confidence scoring. The next improvement
  is to decide whether Storage should set `min_date_confidence: medium` after
  comparing recall loss against wrong-date reduction on real runs.
- Normalize still only emits verified ArticleRecords, by design. The new Verify
  stats sidecar is the rejection-debug surface for the records that Normalize
  drops.

## Cluster / Edit / Validate / Render review

### What was good

- `cluster` is deterministic and standalone. Its split between thread anchoring, Jaccard grouping, and oversized-cluster splitting is readable and testable.
- `edit` keeps the LLM boundary narrow: prompt assembly is in `assembler.py`, transport is in `llm_client.py`, and optional structured output failure does not prevent writing `briefing.md`.
- `validate` is the right post-LLM safety gate: it checks cited sources, cited dates, and optional structured JSON schemas.
- `render` is template-driven and can still write HTML when local Chrome is missing, which is the correct failure mode for report generation.

### Problems found

- `validate` rejected stale dates but did not reject future cited dates. A source line dated after the run date could pass even though `verify` has a future-date policy.
- `validate` read `pipeline.date_window.max_future_days`, but stale-date validation still hardcoded two days. That made the validate gate diverge from the domain's configured freshness policy.
- `validate` parsed source locale tags literally. Edit strips `[en]` / `[zh-CN]`, but a missed cleanup could still turn `Digitimes [en]` into a false source mismatch.
- `render_tags` had config, CSS, and unit tests for tag detection, but the production render path never applied those tags to item headings. This made part of the render design dead code.
- Render tag detection nominally supported item bodies, but `convert()` rendered the heading before reading the body. In practice, tags were title-only and missed price/supply/technology cues that appeared in the item text.
- `render` displayed source locale tags if they survived earlier cleanup. Edit
  and Validate already handle `[en]` / `[zh-CN]` defensively, but the final
  presentation layer could still expose them in HTML/PDF.
- Source-locale cleanup only accepted lowercase language plus uppercase region
  tags. LLM output using variants such as `[EN]`, `[zh-cn]`, or
  `[zh-Hans-CN]` could slip through Edit cleanup, Validate parsing, or final
  Render display.
- Artifact basename logic existed in both Render and the orchestrator. Current
  `storage` worked, but a future domain ID with punctuation could make the
  orchestrator record a different expected HTML/PDF path than Render writes.
- `cluster` could over-merge when generic terms dominated the article term sets. Thread anchoring helped continuity, but the orphan clustering decision treated entity and term overlap as equally specific.
- `cluster` treated all entity overlap equally. A shared secondary entity could
  count too much compared with a shared primary subject, and the oversized
  split threshold was too weak once entity salience was introduced.
- `cluster` output only listed article IDs plus aggregate source types/locales. That was enough for joins, but weak for debugging why a cluster formed or whether duplicate URL variants slipped in.
- `cluster` audit fields assumed fully normalized `source` and `canonical_url`
  fields. Search-shaped or partially normalized records with `source_domain` or
  only raw `url` could therefore produce incomplete source/canonical audit
  metadata.
- `cluster` wrote `created` from wall-clock execution time. Backfills or historical reruns could therefore produce old run-date outputs whose cluster creation date looked like today.
- `cluster` promised `event_thread_id` forced merging, but the later `max_size`
  split could break a large thread-anchored cluster back into smaller lexical
  groups. That weakened the Story Tracking continuity contract.
- `edit` relied entirely on prompt discipline for source lines. The fallback parsing was useful, but a common LLM omission was missing source/date lines that could be repaired deterministically from article data.
- Edit's source-line repair treated every `###` heading as a news item, so
  structural sections such as `今日要点`, `关注`, and `反向信号` could receive
  invented source lines when their text overlapped an article.
- `validate` checked that a cited source existed somewhere in the verified article pool, but did not require that the cited source's article actually matched the news item content.
- `validate` also accepted brand-like source labels through loose domain-token matching. A cited source such as `Reuters` could match an unrelated domain containing that token instead of requiring an alias or exact source.
- `validate` source aliases were still matched by substring after alias lookup.
  `Reuters -> reuters.com` could therefore still match an impostor host such as
  `notreuters.com`.
- `validate` treated a cited source with no comparable article text as aligned. That let a known source label pass even when the underlying article could not support or contradict the generated item.
- `validate` checked the report's cited source-line date against the run window,
  but did not compare it with the actual date of the supporting article. A stale
  article could be cited as today's news if the LLM rewrote only the source-line
  date.
- Edit and Validate used the same incorrect `lstrip("www.")` host cleanup for
  fallback source labels. That could corrupt uncommon but valid subdomains in
  rendered source labels or validation source matching.
- Edit writes `threads` into `event-threads.json`, but Validate only checked
  `causal_edges` and `judgments`. At the same time, the structured-output
  schemas still expected the older `et-YYYY-NNN` placeholder ID shape while Edit
  can now normalize new IDs to `et-{domain}-{date}-{hash}`. That weakened the
  quality gate for next-run watch-query generation.

### Fixes made

- `validate_item()` now accepts `max_future_days` and rejects cited dates beyond the configured future window.
- `validate.main()` reads both `pipeline.date_window.max_future_days` and `pipeline.date_window.stale_days` from `domain.yaml`.
- `validate` source-line parsing now strips locale tags defensively, while the Edit prompt and cleanup still require final source lines without `[en]` / `[zh-CN]`.
- `render.convert()` now accepts `tag_config` and renders configured tag badges in item headings.
- `render.convert()` now buffers each item until its body/source line is complete, then detects tags from title plus body text before rendering the heading.
- `render.main()` now loads `editorial.render_tags` from the domain config and passes it into HTML rendering.
- `render` now strips machine locale tags from displayed source lines so final
  artifacts do not show `[en]` or `[zh-CN]` even if upstream cleanup misses one.
- Edit, Validate, and Render now share a broader locale-tag shape that accepts
  case variants and script/region subtags, so source-line cleanup is robust to
  common LLM casing drift.
- The orchestrator now uses Render's `artifact_basename()` helper when resolving
  expected HTML/PDF paths, keeping artifact naming single-sourced.
- `cluster` now uses weighted entity/term overlap for orphan clustering, giving entity matches more weight than generic term matches.
- Cluster similarity now treats the first entity as the best available subject
  hint: shared primary entities score above secondary-only overlap, and
  secondary-only overlap is lightly damped.
- Oversized orphan cluster splitting now uses at least a `0.35` threshold, so
  low-threshold discovery runs still get a genuinely stricter second pass.
- `cluster` now applies a bridge-cluster review: orphan components without a
  shared entity across all articles are split by primary entity, while
  multi-primary clusters with a common subject entity still stay together.
- Cluster objects now include `source_domains` and `canonical_urls` as audit fields while keeping `article_ids` as the primary join key.
- Cluster audit fields now fall back from `source` to `source_domain` and from
  `canonical_url` to canonicalized `url`, keeping diagnostics useful when the
  input still resembles raw/search records.
- Cluster `created` now comes from the pipeline run date, so backfills and historical reruns produce stable artifacts.
- Thread-anchored clusters now remain intact during the oversized-cluster split;
  `max_size` applies to generic orphan clusters, not to an active story thread.
- `edit` now applies deterministic source-line repair before writing `briefing.md`: missing source/date lines are added only when a news item clearly matches one input article.
- Source-line repair now skips structural sections (`今日要点`, `关注`,
  `反向信号`) and only repairs actual news items.
- `validate` now checks source-item alignment: a cited source must map to an article from that source with coarse title/body overlap, not merely appear elsewhere in the day's source pool.
- `validate` now rejects source-item alignment when the generated item has content but the cited article has no comparable title/snippet/summary tokens.
- `validate` now checks source-date alignment when supporting articles expose
  dates: the cited source-line date must match at least one aligned article date,
  otherwise the item gets a `SOURCE_DATE` violation.
- `validate` alias and domain-like source matching now use host-boundary rules:
  aliases match exact hosts/subdomains, not arbitrary substrings, while parent
  domains such as `sina.com.cn` can still match subdomains such as
  `finance.sina.com.cn`.
- Edit and Validate fallback source labels now strip only exact `www.`/`m.`
  presentation prefixes and preserve real subdomains.
- `validate` now reserves loose domain-token fallback for domain-like labels only; brand-like labels require configured aliases or exact source names.
- Added `event_thread.schema.json` for daily structured thread output, and
  updated causal-edge and judgment schemas to accept the current event-thread
  ID family instead of only the old placeholder pattern.
- Validate now checks `threads`, `causal_edges`, and `judgments` when
  `event-threads.json` and a schema directory are supplied.
- Added tests for domain-configured stale windows, future-date validation, source locale tag cleanup including case/script variants, source label fallback, source-context evidence, source-date evidence, render tag output from titles and item bodies, rendered source-line locale cleanup, render/orchestrator artifact-name consistency, source-line repair, generic-term over-merge prevention, bridge-cluster splitting, shared-subject cluster preservation, thread-anchored max-size behavior, and run-date-driven cluster creation dates.
- Added cluster regression coverage proving primary-entity overlap scores above
  secondary-only overlap.
- Added structured-output regression tests for thread validation and current
  thread ID shapes.

### Remaining questions

- Cluster now has a lightweight primary-entity guard against bridge merges, but
  a richer primary-topic model could still improve cases where entity order is
  not a strong salience signal.
- Edit now has a deterministic first-pass repair for missing source lines. A full LLM retry loop for schema/validation failures is still future work.
- Render tag detection now uses item title plus body text. A remaining display improvement is to tune each domain's keyword sets against real reports so badges stay sparse and useful.
- Validate source-item alignment is intentionally coarse. If future prompts become more abstractive, this should evolve into cluster-aware support checks instead of direct token overlap. Source-date alignment is also intentionally evidence-based: undated aligned articles are not rejected solely for lacking date metadata.

## DB / Story Tracking / Monitoring / Orchestrator review

### What was good

- `db` cleanly separates schema creation, domain seeding, ingest/write helpers, and read APIs.
- `story-tracking` keeps contracts and context-selection logic pure, while SQLite writes stay in `stratum/db`.
- `monitoring` has deterministic health and coverage functions with focused tests.
- `orchestrator/pipeline.py` keeps stage execution in standalone subprocesses, so stages remain independently testable.

### Problems found

- `--from-stage` existed in the CLI and docs but was not actually used to gate execution. Resume runs could unexpectedly re-run earlier stages, including Search and collectors.
- Resume runs skipped earlier stages but still executed tail DB ingest unconditionally. A `--from-stage validate` or `--from-stage render` run could therefore re-ingest old articles/events and mutate SQLite counters during what should be a read-only validation/render pass.
- Story context generation read `target_entity_ids` from judgments but ignored `target_thread_ids`. Event-pair judgments from the LLM therefore lost their target thread context before reaching the next prompt.
- SQLite query seeding accepted dimension-grouped `queries.yaml`, but the `queries` table did not persist `dimension`, and DB-backed Search read every DB query as synthetic `dimension=db`. That erased the coverage surface Search had just learned from YAML.
- Coverage monitoring depended on detailed `source_records` carrying `cluster_id`. When only Stage 5 `clusters.json` was available, it ignored the cluster-level `source_types` and `locales` already present in the cluster object and could report false gaps.
- Coverage follow-up generation expected gap `entities`, but `detect_gaps()` did not preserve cluster entities/terms in the gap object. Missing official-source gaps therefore lost the context needed to generate specific official queries.
- Coverage severity still interpreted cluster confidence as historical `A/B/C/D` labels even though current StoryCluster output uses `high/medium/low`. Low-confidence gaps could therefore be downgraded and fail to generate follow-up queries.
- Coverage severity counted only detailed `source_records`, ignoring cluster-level `source_domains`. A cluster summary without detailed records could look source-sparse even when it already carried several source domains.
- Coverage detail records defaulted missing `source_locale` to `en`. An
  incomplete source record could therefore hide an English-locale gap even
  though there was no language evidence.
- Coverage compared source types/locales literally, so labels such as
  `Official`, `MEDIA`, or `zh-cn` could create false missing-source or
  missing-locale gaps.
- Source health `dry_streak` was computed in append order. Backfills or replayed historical health records could make a recovered source still look dry, or hide a recent dry spell.
- Source health records are append-only, so rerunning the same day could write multiple records for the same source/date. Stats then treated duplicate same-day misses as multiple dry days and inflated `total_scans`.
- Monitoring treated `hits > 0` as source health, but Collectors now distinguish
  candidates from selected post-merge contribution. A source producing only
  duplicate candidates could look healthy even while contributing nothing to
  `raw.json`.
- Source health records carried a `scanned` flag, but aggregation still counted
  `scanned: false` records as scans and dry days. A source deliberately skipped
  by config/runtime could therefore look like a failing source.
- Collector `unsupported` status distinguished missing runtime capability from
  source failure, but the orchestrator/Monitoring health path still treated it
  like a scanned zero-hit error. Browser-only sources without Playwright could
  therefore generate dry-source and HTTP-error alerts.
- Source dated-rate aggregation mixed observed and unobserved metadata: the
  numerator counted only records with `metadata.dated`, but the denominator used
  all historical hits. Legacy records without dated metadata could therefore
  create false low-dated-rate alerts.
- Monitoring HTTP-error alerts used the lifetime error counter directly. A
  source with old transient failures could keep alerting even after later
  successful scans reset the current operational risk.
- DB ingest did not persist search query stats in the normal pipeline path, even though helper APIs existed. Collector source health now feeds Monitoring NDJSON.
- DB read APIs exposed entity snapshots, but not an event-level timeline by entity or term. That made accumulated data hard to reuse for questions like "Samsung's important events over the last six months" or "HBM progress across major companies".
- `get_thread_timeline()` returned raw SQLite rows, leaving JSON-array columns
  such as `article_ids`, `entity_ids`, `term_ids`, and `source_domains` as
  strings. Other event timeline helpers returned parsed lists, so callers had to
  handle inconsistent shapes for the same event contract.
- Orchestrator parsed a runtime `db_dir`, but DB helper functions still resolved their own path from global `config.yaml` or the default fallback. In no-config or custom-output runs, the pipeline could check one SQLite path while story context/query stats/final ingest wrote another.
- Entity updates used the machine's current date for `entities.last_seen` instead of the pipeline run date. Backfills or historical replays could therefore make old entities look newly active.
- Entity rolling counts were additive for every normalize-or-earlier rerun. Reprocessing the same day could inflate `article_count_7d` even though the per-period entity snapshot already identified the same `{entity, scale, period}` surface.
- Entity rolling counters were only same-period delta corrected. Historical backfills and 7-day/30-day window expiration could still leave `entities.article_count_*` out of sync with `entity_snapshots`.
- Search query hit counters had the same problem: re-running Search for the same date added the whole result count again, so query quality history could drift away from actual daily results.
- Search query rolling counters still behaved like patched additive counters. Same-day deltas were corrected, but 7-day/30-day values were not recomputed from the daily ledger, so historical backfills and window expiration could leave stale query quality metrics.
- Thread daily event counters were incremented before `events` upsert, so re-ingesting the same `event-threads.json` could make an existing story look more active than it really was.
- Edit prompts describe thread priority as human labels such as `high`,
  `medium`, and `low`, but SQLite stores `threads.priority` and
  `events.priority` as integer sort ranks. Daily DB ingest wrote raw values, so
  label output could land in integer columns and make priority ordering
  unreliable.
- Event replacement updated `events.entity_ids`, but `thread_entities` only inserted missing links and never removed stale subject associations. Correcting an event could therefore leave obsolete entities in thread keyword export and entity timelines.
- Corrected daily Agent output could remove a causal edge or judgment from `event-threads.json`, but DB ingest only upserted current rows and never deleted stale pending rows from the same briefing. Old hypotheses could therefore keep appearing in story context.
- The orchestrator exported `thread_keywords.json` before DB ingest even though the exporter reads SQLite. The feedback file for the next run could therefore miss events produced by the current Edit/DB ingest cycle.
- `thread_keywords.json` was exported per event row instead of per thread. A continuing story with multiple events could become multiple competing Normalize candidates, splitting its keyword evidence and making thread assignment less stable.
- Event-thread watch query persistence required explicit `watch_signals` even
  though the event-thread engine can fall back to a thread title/canonical
  question. Agent output that omitted optional watch signals could therefore
  persist the event itself but fail to create next-run Search follow-up queries.
- `should_run_stage()` silently returned `True` for unknown stage names. The CLI
  constrained `--from-stage`, but helper callers or future entrypoints could
  typo a stage and unexpectedly run the full chain, including earlier mutating
  stages.

### Fixes made

- Added `PIPELINE_STAGE_ORDER` and `should_run_stage()` to make `--from-stage` real.
- Search-side collectors now run only when Search runs, so resume from a later stage does not mutate existing `raw.json`.
- Added DB ingest mode gating: event ingestion only runs when Edit may have produced fresh structured output, entity count/snapshot ingestion only runs when Normalize produced fresh articles, and validate/render-only resumes record DB ingest as skipped.
- Story context generation now falls back to `target_thread_ids` when a judgment has no `target_entity_ids`.
- DB schema now includes `queries.dimension`, connection setup applies an additive migration for existing DBs, seeding preserves dimension-grouped query strategy, and DB-backed Search reads the stored dimension.
- `coverage.detect_gaps()` now initializes coverage from cluster-level `source_types` and `locales`, then augments it with detailed source records when available.
- Coverage gaps now retain cluster `entities` and `terms`, so high-severity missing-official gaps can generate entity-specific follow-up queries.
- Coverage severity now normalizes both current `high/medium/low` and legacy `A/B/C/D` confidence labels.
- Coverage severity now uses cluster-level `source_domains` when detailed source records are absent, preventing false high severity caused by missing source-record detail.
- Coverage now normalizes source type and locale labels before comparison, and
  treats missing locale metadata as unknown rather than English coverage.
- Source health stats now group records by source and compute dry streaks in chronological order, making monitoring robust to backfilled or replayed NDJSON records.
- Source health stats now collapse repeated records for the same source/date to the latest append before aggregation, keeping reruns from inflating scan counts or dry streaks.
- Source health now tracks both acquisition drought (`dry_streak`) and
  contribution drought (`selected_dry_streak`), plus `selected_rate`; added
  `get_non_contributing_sources()` for sources that keep scanning but do not
  survive collector/search canonical URL merge.
- Source health aggregation now keeps `scanned: false` records for first/last
  seen observability but excludes them from scan counts, dry streaks, selected
  dry streaks, and HTTP error counts.
- Collector health writes `unsupported` records as `scanned: false` with
  `metadata.status`, and Monitoring also recognizes historical unsupported
  records from tags/metadata so infrastructure capability gaps do not become
  source-quality alerts.
- Source health now computes dated metadata coverage from collector health
  metadata and exposes `get_source_alerts()` for configurable dry-source,
  non-contribution, HTTP-error, and low-dated-rate alerts.
- Source dated-rate aggregation now divides by `dated_hits_observed`, the hits
  from records that actually reported dated metadata, so legacy records without
  dated telemetry do not become synthetic undated failures.
- HTTP-error alerts now use `http_error_streak`, the current consecutive
  scanned-day error streak, while retaining lifetime `http_errors` for
  historical reliability review.
- Collector source health is now written to `{health_data_dir}/{domain}/source-daily.ndjson` and a per-run `collector_stats.json` sidecar.
- The orchestrator now writes `run_manifest.json` with stage-level status, outputs, timestamps, summary counts, and hard-failure state before exit.
- Search `raw.stats.json` is now ingested into SQLite query counters after Search, including the new `query_id/results_count` stats shape.
- Entity snapshots now use the same per-run entity article counts derived from `articles.jsonl`, instead of writing placeholder zero counts.
- DB now exposes event-level retrieval helpers for entity histories, term histories, and term-by-company progress groups.
- `get_thread_timeline()` now returns the same parsed event shape as
  `get_entity_events()` and `get_term_events()`, so all event timeline readers
  expose list-valued JSON fields consistently.
- DB path resolution now supports `STRATUM_DB_DIR`, and the orchestrator sets it from the resolved runtime `db_dir` so all in-process DB helpers use the same database root.
- Entity updates now accept and receive the pipeline `run_date`, so `last_seen` follows the briefing date rather than wall-clock execution time.
- Entity updates now compare incoming period article counts with existing `entity_snapshots` for the same entity/scale/period and apply only the delta, making same-day reruns idempotent.
- Entity updates now write the current period's article count into `entity_snapshots` and recompute 7-day/30-day rolling counters from that ledger, making entity activity counters snapshot-derived.
- Query stats now write a `query_run_stats` daily ledger and update `queries.hit_count_7d` by same-date result deltas, making Search stats re-ingest idempotent.
- Query stat ingest now recomputes `hit_count_7d`, `hit_count_30d`, and `avg_articles` from `query_run_stats` after each write, making Search quality counters ledger-derived rather than additive.
- Daily event ingest now checks the deterministic `ev-{run_date}-{thread_id}` id before updating `threads.event_count_daily`, so same-day event replacement does not inflate thread activity.
- Daily event ingest now normalizes thread/event priority labels to numeric DB
  ranks (`high` = 1, `medium` = 2, `low`/unknown = 3), keeping story ordering
  stable even when Agent output follows the prompt's label format.
- After each event upsert, DB ingest rebuilds thread subject-entity links from all stored events for that thread, preserving historical entities while dropping stale entities from corrected event payloads.
- Daily causal edges and judgments now clear stale pending rows for the same source briefing before inserting current output, while preserving verification fields on already-verified rows with matching IDs.
- `thread_keywords.json` export now runs after successful event DB ingest, so the next normalize run receives keywords from newly persisted events rather than the previous SQLite state.
- Thread keyword export now aggregates events by `thread_id`, unions title/entity keywords, and keeps the most actionable lifecycle status for Normalize feedback.
- Event-thread watch query persistence now sends all thread records with an ID
  to the event-thread engine; explicit `watch_signals` are still preferred, but
  threads without them fall back to canonical question/title for Search
  follow-up.
- Resume-stage gating now rejects unknown stage names with a clear `ValueError`
  instead of defaulting to a full run.
- Added tests for resume gating, DB query dimension persistence, schema execution on empty SQLite, cluster-summary coverage fallback, current/legacy confidence severity, source-domain-aware severity, and DB event timeline retrieval.
- Added a DB regression test proving thread timelines parse JSON-array columns
  the same way entity and term timelines do.
- Added a monitoring regression test for out-of-order health records.
- Added a monitoring regression test for duplicate same-day source records produced by reruns.
- Added a monitoring regression test proving unscanned records do not create
  false dry-source alerts.
- Added monitoring tests for dated-rate aggregation and source alert threshold
  generation, including legacy records without dated metadata.
- Added a monitoring regression test proving dated-rate denominators ignore
  hits from records that lack dated metadata observations.
- Added an orchestrator regression test proving DB ingest helpers resolve the same `db_dir` the pipeline checked.
- Added a DB regression test proving `update_entities_after_run()` writes the explicit pipeline date.
- Added DB regression tests for same-period idempotency and changed-count delta correction.
- Added a DB regression test proving entity rolling counters are recomputed from `entity_snapshots` across 7-day and 30-day windows.
- Added DB regression tests for same-date Search query stat idempotency and changed-count delta correction.
- Added a DB regression test proving Search query rollups are recomputed from the daily ledger across 7-day and 30-day windows.
- Added DB regression tests for event-thread re-ingest idempotency and new daily event counting.
- Added a DB regression test proving labelled daily priorities are stored as
  numeric ranks on both threads and events, including same-thread updates.
- Added a DB regression test proving corrected event entity sets rebuild `thread_entities` without losing historical associations.
- Added DB regression tests for stale pending causal/judgment cleanup and preservation of existing verification fields during replacement.
- Added an orchestrator regression test for the post-ingest thread-keyword export gate.
- Added an orchestrator regression test proving repeated events for one thread export as a single keyword profile.
- Added an orchestrator regression test proving persisted watch queries fall
  back to thread title when `watch_signals` are absent.
- Added an orchestrator regression test proving unknown resume stages fail loudly.

### Remaining questions

- Manifest data can now support retries and dashboards, but no retry runner consumes it yet.
- DB ingest is now safer for late-stage resumes and same-day reprocessing of entity/query/event counters. Search query and entity activity counters are both ledger-derived; a remaining improvement is adding normalized event/entity index tables if JSON-array scans become expensive.
- The event timeline helpers currently filter JSON-array columns in Python for SQLite portability. If the DB grows large, add normalized `event_entities` and `event_terms` indexes behind the same read API.

## Contracts / Docs review

### What was good

- `stratum/contracts` provides stable JSON schema locations for raw search results, verified articles, normalized articles, and story clusters.
- Cross-temporal event-thread dataclasses are re-exported through `stratum.contracts`, so tests and callers do not need to import deep implementation paths.
- Required `SCOPE.md` files are now covered by `tests/test_docs.py`.
- The current schema files parse as valid JSON.
- `tests/test_contracts.py` now validates representative Search, collector, Verify, Normalize, and Cluster output shapes against the shared JSON schemas.

### Problems found

- `search_result.json` still treated `engine` as a small legacy enum and omitted newer Search/collector fields such as `locale`, `source_domain`, `source_type_hint`, `query_id`, `query_dimension`, `score`, and `published_at`.
- `date_source` lineage was implemented in Enrich/Verify/Normalize, but the raw and verified schemas did not describe all current values, so schema consumers would reject valid pipeline objects.
- ArticleRecord required `date_source` but left it as an unconstrained string, while raw and verified contracts used an explicit lineage enum. That made normalized artifacts less strictly validated than upstream artifacts.
- `collector_stats.json` had become the official Collectors-to-Monitoring sidecar, but it had no shared JSON Schema under `stratum/contracts`.
- Search `raw.stats.json` had become the main quality-debug surface for query
  yield, curation coverage, source-type gaps, domain-filter coverage, and DB
  query-stat ingest, but it did not have a shared contract. That meant Search
  observability could regress while schema tests still passed.
- ArticleRecord `source_locale` schema and data integrity tests only accepted
  narrow language/region tags. After Search began preserving BCP47-style
  variants such as `en-US`, `zh-cn`, and `zh-Hans-CN`, valid normalized
  records could fail contract or fixture validation.
- `story_cluster.json` and data-integrity tests only allowed lowercase
  letters/underscores in the domain part of `sc-{domain_id}-{seq}`. The cluster
  stage preserves the real domain directory id, so a future domain such as
  `ai-storage2` would produce valid pipeline output that failed the contract.
- Contract consolidation is incomplete: `story-tracking/story_contracts.py` remains local to that subsystem while `contracts/event_thread.py` covers cross-temporal thread state. This is acceptable for now, but the boundary should stay explicit.
- Documentation has to distinguish the user-facing "8 stage" flow from the internal collector sidecar and DB ingest steps. `stratum/stages/SCOPE.md` now does this, but it is an easy area to regress.

### Fixes applied

- Updated `search_result.json` to accept both Search API output and collectors sidecar output, including flexible engine IDs like `rss:<source>` and `direct_fetch:<source>`.
- Added `date_source` to `verified_article.json` and expanded the allowed date-lineage values across raw and verified contracts.
- Constrained ArticleRecord `date_source` to the same lineage enum as raw and verified artifacts.
- Added `collector_stats.json` as a shared contract for collector sidecars, including `unsupported` status and `unknown` access.
- Added `search_stats.json` as the shared contract for `raw.stats.json`.
  The schema requires the current Search diagnostics surface, including
  raw/curated locale, source-type and dimension coverage, source-type gaps,
  domain-filter coverage, top source domains, low-yield queries, and per-query
  execution stats.
- Relaxed ArticleRecord `source_locale` validation and data integrity tests to
  the same BCP47-style language/script/region shape used by Search query
  locales.
- Added `query_dimension` to the raw Search contract, and required `canonical_url`, `date_source`, `discovery_mode`, and `query_dimension` on ArticleRecord so downstream diagnostics cannot silently lose discovery context.
- Required StoryCluster audit fields (`article_count`, `source_types`, `locales`, `source_domains`, `canonical_urls`, `created`) that current clustering emits and monitoring/debugging relies on.
- Relaxed the StoryCluster id contract and integrity tests to accept domain ids
  with lowercase letters, digits, underscores, and hyphens, matching the
  cluster stage's `sc-{domain_id}-{seq:04d}` output.
- Added a module-doc test that requires `stratum/contracts/SCOPE.md` to list each current JSON schema exactly once.
- Expanded `stratum/contracts/SCOPE.md` with discovery-contract notes so the Search/Collectors boundary is explicit.
- Added schema smoke tests that parse every contract, run Draft 7 schema checks, and validate representative current output shapes.
- Added contract smoke coverage for collector stats sidecars and required docs listing for the new schema.
- Added contract smoke coverage for Search `raw.stats.json`, and changed the
  runtime data-integrity test to validate optional `raw.stats.json` against the
  shared schema instead of only checking for a loose query key.
- Added ArticleRecord schema coverage for BCP47-style locale variants.
- Added cluster/contract regression coverage for a hyphenated digit-bearing
  domain id.

### Remaining questions

- Integrity tests now validate a small golden end-to-end fixture against the
  shared schemas when no local run exists; a remaining improvement is wiring the
  same contract validation directly into pipeline artifact emission for earlier
  failure during real runs.
- Decide whether `EventRecord`, `CausalEdge`, and `Judgment` should move from `story-tracking` into `contracts` once more subsystems depend on them.

## Domains / Config review

### What was good

- Domain-specific knowledge is mostly isolated under `domains/{id}/`, keeping `stratum/` framework code domain-agnostic.
- `domain.yaml` owns entities, source registry, validation policy, source classification, and editorial/render policy.
- `queries.yaml` owns structured Search query templates by intent, dimension, and locale, which matches the current Search and DB seeding path.
- The storage source registry has clear active/inactive lifecycle fields and explicit access methods.

### Problems found

- `domains/storage/domain.yaml` still carried an old copy of `seed_queries` and `gap_searches`, while the runtime path reads `domains/storage/queries.yaml`. That creates a split-brain query strategy: reviewers may edit one file while production reads the other.
- README still described `domain.yaml` as the only place domain knowledge lives, even though prompts, templates, taxonomy, and `queries.yaml` are intentionally separate domain assets.
- `domains/robot/queries.yaml` still showed the old flat `seed_queries` placeholder shape, and `CONTRIBUTING.md` described the removed skill/data-domain project layout. That made new-domain onboarding point at APIs the runtime no longer treats as the preferred contract.
- `pipeline.source_aliases` only allowed one domain per display alias. Brands
  such as Digitimes publish across `digitimes.com` and `digitimes.com.tw`, so a
  valid cited `Digitimes` source could fail Validate when the supporting
  article came from the Taiwan domain.
- Top-level onboarding docs were not covered by the stale-module reference
  test, so `CONTRIBUTING.md` could still mention removed runtime modules such as
  `value-chain-monitor` after the module `SCOPE.md` files had been cleaned.
- `include_domains` is one of the main Search-strength levers, but Search YAML,
  DB seed/ingest, and the Tavily engine each normalized it locally with a loose
  string strip. URL-like values, mobile prefixes, duplicates, or malformed
  structures could therefore drift between YAML-backed and DB-backed Search.

### Fixes applied

- Removed stale `seed_queries` and `gap_searches` from `domains/storage/domain.yaml`; `queries.yaml` is now the sole storage Search template source.
- Updated the storage domain header and README to describe the domain directory as the source of truth, with queries explicitly owned by `queries.yaml`.
- Added `tests/test_domains.py` to assert domain configs do not duplicate query templates, every domain has nonempty `queries.yaml`, and active storage sources have collectable registry fields.
- Migrated the robot placeholder to the structured `queries` schema, removed the remaining `gap_searches` wording from storage scope docs, and updated `CONTRIBUTING.md` to describe `domains/{id}/domain.yaml + queries.yaml`.
- Removed Stage Search and DB seeding support for legacy `seed_queries`/`gap_searches` YAML so new-domain query configuration has one active schema; added regression tests proving legacy sections are rejected.
- Validate now accepts `source_aliases` values as either a single domain string
  or a list of domain patterns. Storage maps `digitimes` to both
  `digitimes.com` and `digitimes.com.tw`, and config tests lock the alias value
  shape.
- Clarified `CONTRIBUTING.md` so `value_chain` is documented as optional domain
  taxonomy/coverage metadata, not a live framework runtime module.
- Expanded documentation coverage tests to scan top-level `README.md` and
  `CONTRIBUTING.md` for removed module/config references, with precise checks
  for retired runtime names rather than valid taxonomy wording.
- Added a shared Search include-domain normalizer and routed Search YAML,
  DB seed/ingest, and Tavily execution through it. Include-domain filters now
  become lowercase host-only domains with `www.`/`m.` prefixes removed, and
  malformed config shapes fail loudly.
- Tightened domain-config tests so domain-owned `queries.yaml` keeps
  `include_domains` as bare hostnames, and added Search regression tests for
  URL/prefix normalization and malformed include-domain values.

### Remaining questions

- The robot domain is still a placeholder. Before using it for real runs, it needs a proper source registry, stronger source classification, and domain-specific collector sources.
- Storage still has browser-only official sources. Production effectiveness depends on deciding whether Playwright is part of the standard runtime.

## Tooling / Infra review

### What was good

- `Makefile` centralizes common test commands and prefers `.venv/bin/python` when available, which keeps local runs consistent with the project-managed dependency set.
- `pyproject.toml` has explicit test dependencies and pytest discovery paths for `tests`, `stratum/stages`, and `stratum/subsystems`.
- `tests/infra/test_install.py` already covers config example validity, install script syntax, required project files, and removal of the old Hermes-skill project shape.

### Problems found

- `make test-schema` still pointed at the deleted `tests/modules/test_all_contracts.py`, so the focused schema target failed even though full `make test` passed.
- Package metadata still said version `4.1.0` and described the project as a generic "Multi-Scale Intelligence System", while README and code now describe the v5 domain-agnostic briefing pipeline.
- DB docs/comments still referred to old implementation names such as `source-profiler` and implied the removed standalone cascade runtime was current.
- Makefile still contained external `hermes cron run ...` shortcuts for daily/weekly/monthly/quarterly/yearly. They may have been useful locally, but they were not self-describing inside this repo.

### Fixes applied

- Updated `make test-schema` to run `tests/test_contracts.py` plus the story event schema tests.
- Added infra tests that parse Makefile pytest commands and assert explicit test paths still exist.
- Historical note: this review previously suggested a large major version; the project now uses small 0.x versions until Storage reaches the real-data 1.0 bar.
- Clarified `stratum/db/SCOPE.md` and `stratum/db/ingest.py` comments so DB persistence capabilities are separated from removed runtime modules.
- Replaced private Hermes cron shortcuts with repo-local `make daily`/`make pipeline` targets that call `stratum/orchestrator/pipeline.py` directly; higher-scale targets now fail with an explicit message because the current orchestrator is daily-only.
- Added an infra regression test so Makefile pipeline shortcuts cannot drift back to private external cron IDs.

### Remaining questions

- The DB layer still has multi-scale/cascade persistence hooks. They are valid state primitives, but no current first-class runner consumes them.

## Data Integrity Tests review

### What was good

- The project already separated fixture-level data tests under `tests/data` from runtime artifact checks under `tests/infra/test_data.py`.
- Fixture tests catch JSON/JSONL parse errors, duplicate IDs, locale format problems, and malformed cluster summaries without requiring network or LLM runs.
- Runtime checks can inspect the latest local daily run, and fall back to a deterministic golden run fixture when no local artifact exists.

### Problems found

- `tests/infra/test_data.py` still searched for old output directories such as `storage/data/articles/<date>/articles.jsonl` and `storage/data/story-clusters/<date>/story-clusters.json`. Current orchestrator output is `{output_dir}/{domain}/data/{YYYY-MM-DD}/articles.jsonl` and `clusters.json`, so the tests were mostly permanent skips.
- Runtime integrity tests still referenced removed source-intelligence artifacts such as `source-records.jsonl` and `trial-pool.json`.
- `tests/data` fixtures still modeled old ArticleRecord and StoryCluster shapes: `date`, `novelty`, confidence grades `A/B/C/D`, and IDs like `sc-YYYY-MM-DD-001`, while current contracts use `published_at`, `fetched_at`, `confidence` values `high/medium/low`, and IDs like `sc-storage-0001`.

### Fixes applied

- Reworked runtime artifact discovery to scan current run directories matching `{domain}/data/{YYYY-MM-DD}` and ignore non-run folders such as `story-tracking`.
- Updated runtime checks to validate current artifacts: `articles.jsonl`, `clusters.json`, optional `raw.stats.json`, optional `collector_stats.json`, optional `run_manifest.json`, and optional `event-threads.json`.
- Added deterministic path-discovery coverage so the runtime tests do not rely only on skipped local artifact checks.
- Migrated fixture-level ArticleRecord and StoryCluster data tests to current contract fields and current cluster ID/confidence formats.
- Added a minimal golden run fixture for runtime artifact tests so cross-artifact checks execute in CI/fresh clones without relying on local output history.
- Runtime artifact tests now validate `articles.jsonl` and `clusters.json` against the shared ArticleRecord and StoryCluster JSON Schemas.
- Replaced stale source-record fixture tests with collector stats sidecar integrity tests.
- Expanded the golden run fixture to include `raw.json`, `enriched.json`,
  `verified.jsonl`, and rendered HTML, and added runtime integrity checks for
  RawSearchResult, VerifiedArticle, CollectorStats, and raw-to-enriched
  identity preservation.

### Remaining questions

- The golden run fixture now covers the main stage artifacts from raw through
  render, but it is still intentionally small. A future richer fixture could
  add `briefing.md`, validation reports, and nonempty structured event-thread
  payloads.

## Prompt / LLM Boundary review

### What was good

- `edit` keeps prompt assembly, LLM transport, markdown repair, and structured-output normalization in separate functions/files.
- The stage has deterministic post-processing for common LLM drift: source locale tags are stripped, missing source lines can be repaired when article support is clear, and `mechanism` can be normalized to judgment `hypothesis`.
- Structured outputs are separated behind `---DATA---` and validated later by the Validate stage when present.

### Problems found

- `llm_client.call_llm()` passed the full JSON payload through `curl -d <payload>`. That can expose the full prompt in process arguments and makes transport behavior harder to test.
- `edit.py` resolved briefing title from `config.yaml` only, so normal domain runs could fall back to `storage早报` instead of `domains/storage/domain.yaml`'s `存储早报`.
- The daily prompt contradicted the lower-level writing rule: one part asked for source domains, while another encouraged professional media aliases and not full domains. It also did not make the no-language-tag rule explicit enough for source lines.
- The structured output instructions asked for `causal_edges` and `judgments`,
  but not `threads`/`watch_signals`. Even after the persistence path existed,
  the LLM was not explicitly prompted to produce the story-thread surface that
  powers next-run Search follow-up.
- Edit only wrote `event-threads.json` when structured output included
  `causal_edges` or `judgments`. A threads-only payload with `watch_signals`
  could therefore be dropped before DB ingest and Search watch-query
  persistence saw it.
- The daily prompt allowed new `threads[].thread_id` to be blank, but DB ingest
  and watch-query persistence both require a concrete id. A new LLM-created
  thread with useful `watch_signals` could therefore be omitted from SQLite and
  never become next-run Search follow-up.

### Fixes applied

- Changed LLM transport to send the payload on stdin via `curl --data-binary @-`, keeping prompts out of argv.
- Added `resolve_domain_title()` and tests so title selection is config override → `domain.yaml` title → fallback.
- Clarified the daily prompt: source lines must use source strings from the provided source index/article data, must include dates, and must not add `[en]`/`[zh-CN]` tags.
- Daily structured-output instructions now request `threads` with
  `watch_signals`, `close_conditions`, priority/status, and entity/term ids, and
  the final `---DATA---` JSON template includes `threads` alongside
  `causal_edges` and `judgments`.
- Added tests for LLM stdin transport and title resolution.
- Documented `domains/{domain}/prompts/` as reserved future override assets, removed the unused `prompts_dir` path from orchestrator path resolution, and added docs tests for that boundary.
- Edit now writes `event-threads.json` when structured output contains
  `threads`, `causal_edges`, or `judgments`, preserving threads-only
  `watch_signals` for DB ingest and next-run Search follow-up.
- Edit now normalizes structured arrays, copies `id` to `thread_id` when needed,
  and assigns deterministic `et-{domain}-{date}-{hash}` ids for blank new
  thread ids before writing `event-threads.json`. This keeps DB ingest and
  watch-query persistence aligned even when the LLM follows the "new thread can
  leave id blank" prompt.
- Added tests for prompt thread/watch-signal instructions and threads-only
  structured output persistence decisions.
- Added tests for blank-thread id synthesis, `id`/`thread_id` normalization, and
  single-object structured array coercion.

### Remaining questions

- Domain prompt overrides are now documented as reserved assets. Implementing first-class override support remains optional future work, but the current active prompt path is explicit.
- Full LLM retry on validation failure remains future work; today the stage repairs only a few deterministic output issues.

## Story Tracking review

### What was good

- `story-tracking` keeps event, causal edge, judgment, and prompt-context logic deterministic and independent from DB writes.
- `BriefingContext` gives Edit a compact surface for carried-forward stories, due judgments, coverage gaps, active causal chains, and unassigned events.
- Tests already covered the main selectors and dataclass serialization helpers.

### Problems found

- Carried-forward context excluded `cooling` events even though they are still part of an active story lifecycle. That could make a story disappear from the next briefing before it is resolved.
- Carried-forward context accepted any scale reference newer than the lookback cutoff, including references after the target date. Historical backfills could therefore see future briefing appearances.
- Carried-forward context sorted same-priority events by older appearance first, which could spend prompt space on less recent stories ahead of fresher active context.
- Active causal chains included unverified edges even when both endpoints were already resolved/archived, pushing stale hypotheses into the Edit prompt.
- Prompt formatting reported only the count of unassigned events, not their IDs, so the Agent had no handle for acting on them.
- Due-judgment context did not filter by judgment `made_at`. Historical
  backfills could therefore see hypotheses that were created after the target
  briefing date if their expected verification date fell inside the due window.
- Coverage-gap detection used every event's `last_updated`, including events
  after the target briefing date. Historical backfills could therefore let a
  future mention suppress a legitimate missing-coverage prompt.
- Coverage gaps derived only from entities already seen in past events. A
  domain-required entity that had never appeared could never become a prompt
  gap, even if the domain taxonomy/watchlist expected coverage.
- Unassigned events and unverified causal chains were not bounded by the target
  briefing date. Historical backfills could inject future events or future-made
  causal hypotheses into the Edit prompt.
- `from_jsonl_line()` only reconstructed the top-level dataclass. Nested
  `TimelineEntry`, `ScaleRef`, and enum fields stayed as raw dictionaries or
  strings, so a future JSONL repository or migration could not rely on the
  contract helper for real round trips.

### Fixes applied

- Carried-forward context now includes `cooling` events and still excludes resolved/archived events.
- Carried-forward context now bounds scale references to the target-date window, preventing future context leakage during backfills.
- Same-priority carried-forward events now sort by most recent relevant briefing appearance first.
- Active causal chains now skip fully inactive chains where both endpoints are resolved/archived.
- `format_context_for_prompt()` now lists unassigned event IDs up to the context item limit.
- Due-judgment selection now ignores judgments with `made_at` after the target
  briefing date, keeping historical prompt context time-consistent.
- Coverage-gap detection now ignores events after the target date, matching the
  no-future-leak behavior of carried-forward context.
- Coverage-gap detection now accepts an optional configured entity universe;
  never-seen candidates are emitted as `never_seen` gaps, and prompt formatting
  describes them as missing prior coverage.
- The orchestrator now passes `domain.yaml` `companies[].id` into Story
  Tracking as the coverage entity universe, so cold-start story context can
  surface never-covered domain companies.
- Unassigned-event selection and active causal-chain selection now respect the
  target briefing date, preventing future story records from leaking into
  backfilled context.
- `from_jsonl_line()` now recursively rebuilds nested dataclasses and enums,
  including `EventRecord.timeline`, `EventRecord.scale_refs`,
  `TimelineEntry.update_type`, and `ScaleRef.prominence`.
- Added regression tests for cooling carry-forward, future-ref exclusion,
  same-priority recency ordering, future-made judgment exclusion, future-event
  exclusion in coverage gaps, never-seen configured coverage entities, future
  unassigned/causal-chain exclusion, fully resolved chain filtering, and
  unassigned event ID formatting.
- Added JSONL round-trip regression coverage for nested event timeline and
  scale-reference objects.

### Remaining questions

- The active runtime maps SQLite rows into compatible simple objects in `orchestrator/pipeline.py`; a future typed adapter could move that mapping into this subsystem without changing `generate_context()`.
- Coverage gaps currently use `companies[].id` as the runner-provided universe.
  A future richer watchlist could include taxonomy-critical products,
  technologies, or value-chain layers as separate coverage candidates.

## Event Thread review

### What was good

- The subsystem has a clean deterministic core for lifecycle state, cluster-to-thread matching, watch query generation, archiving, and cross-temporal rollups.
- Cross-temporal linkage is well isolated from daily thread mechanics and already has broad tests for register/rollup/trace/resolve behavior.
- The module does not own persistence, which keeps it easy to test and reuse.

### Problems found

- `add_update()` could leave an old `emerging` thread in `emerging` after a second confirmation update, because status computation only looked at the latest update date.
- Lifecycle status used the last timeline list entry without checking the target
  `run_date` or sorting by entry date. Historical backfills could therefore see
  future updates, and unordered timeline payloads could compute the wrong
  cooling/resolved state.
- Cluster matching could match against `resolved` or `archived` threads, accidentally reviving inactive stories through lexical overlap.
- Watch queries skipped `cooling` threads even though those are precisely the threads that need follow-up before resolution.
- Watch query generation depended on dict insertion order, so low-priority threads could consume the daily query cap before high-priority threads.
- Within the same priority, watch query generation sorted older `last_updated`
  threads before newer ones. When the daily query cap was tight, stale stories
  could crowd out fresh active stories that were more likely to produce useful
  follow-up Search results.
- Watch query generation always emitted English queries and did not deduplicate identical watch signals. That left multilingual follow-up to other layers and could waste the daily Search cap on repeated queries.
- Thread auto-creation checked a relative expression that allowed growth beyond `MAX_THREADS`.
- Archive stats could count preexisting archived threads as newly archived.
- Search DB query loading only allowed thread-bound queries for `emerging` and `active` threads. That contradicted event-thread watch-query generation, which correctly includes `cooling` threads for follow-up before resolution.
- The public DB helper `get_queries_for_scale("daily")` still returned only
  `detection` queries from emerging/active threads. That left a second daily
  query-selection path that could drop event-thread `verification` follow-ups
  and cooling stories even after the Search CLI path was fixed.
- New thread IDs were allocated as `len(threads) + 1`. Sparse histories or
  deleted/archived records could therefore generate an ID that already exists,
  overwriting an existing story thread.
- Cross-temporal appearance registration appended every appearance blindly.
  Re-running the same briefing could duplicate appearances in traces and
  inflate scale summaries.
- `add_update()` appended the new confidence to `confidence_history`, but left
  `thread.confidence` at the previous value. Current-state consumers could
  therefore see stale confidence even though the timeline was updated.
- Matching and watch-query generation depended too heavily on explicit
  `watch_signals`. Auto-created threads or imperfect LLM structured output
  could produce a live thread with no watch signals, making it hard to match
  future clusters and preventing next-run Search follow-up.

### Fixes applied

- Lifecycle computation now keeps only true first-disclosure same-day threads as
  `emerging`; later updates make the thread `active`. It also ignores future
  timeline entries for historical backfills and sorts observed timeline dates
  before choosing the latest update.
- Cluster matching now ignores resolved/archived threads and tokenizes watch-signal phrases before overlap scoring.
- Watch queries include `cooling` threads and are ordered by priority plus
  recency before the daily cap is applied.
- Watch queries can now be generated for a caller-provided locale list, and repeated `query + locale` pairs are deduped before consuming the daily cap.
- Search DB query loading now also includes active queries bound to `cooling` threads, keeping the Search closed loop aligned with event-thread lifecycle policy.
- `get_queries_for_scale("daily")` now matches that policy: daily reads include
  `detection` plus thread-bound `verification` queries for emerging, active,
  and cooling threads, while resolved threads remain excluded.
- The orchestrator now expands configured source locales and persists
  event-thread `watch_signals` into SQLite as active thread-bound
  `verification` queries with `dimension = thread_watch`, so the next Search
  run follows emerging/active/cooling stories through the normal DB query path.
- `evolve_threads()` now uses `len(threads) < MAX_THREADS` for auto-creation and reports only newly archived threads.
- New thread IDs now use the highest existing `et-{domain}-NNNN` suffix plus
  one, preserving story identity even when thread IDs are sparse.
- Cross-temporal appearances are now idempotent by `scale + briefing_id`, so
  re-running the same briefing replaces the existing appearance instead of
  duplicating trace/summary records.
- `add_update()` now updates the current `thread.confidence` together with
  `last_updated`, lifecycle status, timeline, and confidence history.
- Cluster matching now falls back to thread title, canonical question,
  open/close conditions, and timeline summaries when explicit watch signals are
  missing. Watch-query generation similarly falls back to the canonical question
  or title so live stories do not disappear from Search feedback solely because
  `watch_signals` was empty.
- Added regression tests for resolved-thread matching, phrase-token matching,
  cooling watch queries, locale-aware watch query generation, watch query
  dedupe, Search loading of cooling thread queries, watch-query SQLite
  persistence, orchestrator source-locale expansion, priority ordering, archive
  stats, max-thread enforcement, and sparse-ID collision avoidance.
- Added regression coverage proving same-priority watch query caps prefer the
  most recently updated thread.
- Added DB helper regression coverage proving daily scale query reads include
  cooling thread-watch verification queries and still exclude resolved threads.
- Added regression tests for title/timeline-summary fallback matching and
  title-backed watch queries when explicit watch signals are missing.
- Added a regression assertion that thread confidence reflects the latest
  update, not only the historical confidence list.
- Added regression coverage for lifecycle status with future timeline entries
  and unordered timeline payloads.
- Added cross-temporal regression coverage for idempotent appearance
  registration and rollup target appearance replacement.

### Remaining questions

- Matching is still lexical and intentionally deterministic. A future semantic matcher can sit beside this implementation, but it should keep the same inactive-thread and priority constraints.
- Watch-query persistence is now wired into the daily runner. A remaining
  tuning task is measuring how many thread-watch queries should be allowed per
  domain before they crowd out baseline discovery.
