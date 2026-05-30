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

### Fixes made

- Tavily now sends a non-empty date window: `start_date = run_date`, `end_date = run_date + 1 day`.
- Tavily converts `site:domain.com` syntax to `include_domains` and removes the `site:` token from the query.
- DB query loading includes both `detection` and `verification` intents.
- Executor preserves concrete failure messages, distinguishes `no_results`, and reports locale/intent in `QueryStats`.
- `raw.stats.json` now includes a `diagnostics` block with raw-vs-curated locale/source-type/dimension coverage, configured source-type floor gaps, low-yield query records, and top source domains before/after curation.
- Source classification now reads `domain.yaml` `pipeline.source_classification`.
- Company aliases are kept out of source-type classification and remain used for entity scoring/diversity only.
- The orchestrator now passes both DB and `queries.yaml` to Search. Search prefers active DB queries but falls back to the YAML baseline when the DB is empty or has an unusable query table.
- Engine factory now skips engines without API keys. The executor can still fall back to the next routed engine, and a no-usable-engine run produces per-query failed stats instead of an opaque empty result set.
- Search YAML loading now supports current `seed_queries`/`gap_searches`, `queries: intent -> locale -> list`, and `queries: intent -> dimension -> locale -> list`, aligned with DB seeding.
- Storage queries are now split by explicit intent and briefing dimension, including `platform_demand` for NVIDIA/AI platform architecture signals that drive memory/storage demand.
- Search config now preserves all company and term aliases from `domain.yaml`, and term scoring consumes aliases instead of English names only.
- SearchResult now computes `canonical_url`; executor, curation, and collector/search merge use it for dedupe while preserving the original `url`.
- Verify now preserves `canonical_url` and uses canonical URL keys for duplicate rejection.
- Curation now supports `min_per_source_type` so available official/analyst/media evidence cannot be crowded out solely by higher-volume media results.
- Curation now supports `max_per_entity` so one high-frequency company/entity cannot dominate the curated pool after the source-type evidence floor has been reserved.
- Tests were added for executor diagnostics, Tavily date/site helpers, verification query loading, DB-empty fallback, missing-key fallback, curation diagnostics, dimensioned YAML query strategy loading, multilingual alias scoring, canonical URL dedupe, and classification loading.

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
- Tavily `topic=news` can be noisy for broad queries, while `topic=general` works better for site-filtered professional sources. This is now handled for `site:` queries, but broad-query strategy still needs tuning.
- Curation now enforces a configured source-type floor and a single-entity diversity cap when configured.
- Search query sourcing is now safer operationally: DB-backed discovery can evolve, but an empty DB no longer suppresses the domain's baseline query strategy.
- Missing API keys are now explicit operational signals. They no longer cause avoidable network retries, and they do not block fallback to another keyed engine for the same locale.
- Site-first and source-mix tuning now has a concrete feedback surface: source-type shortfalls and low-yield query records can be read directly from `raw.stats.json`.
- Query strategy can now evolve without changing Search code: baseline queries can stay simple while storage uses explicit detection/verification intent groups plus coverage dimensions.
- Multilingual results are now scored and diversity-capped with the same entity/term vocabulary as English and Simplified Chinese results, which makes locale expansion more meaningful.
- Duplicate URL pressure is lower: Search and collectors now treat common URL variants as the same article before they consume curated evidence slots.
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

### Fixes made

- `direct_fetch` no longer uses the full list page as a publication-date fallback for heading links.
- Added optional article-detail date resolution via `resolve_article_dates: true`, with concurrent workers and short per-request timeout. It is available for sources that need it but is not forced on every source.
- Added future-date sanity: dates more than one day after `run_date` are discarded.
- Normalized extracted title text with HTML unescape and whitespace collapsing.
- `read_more` fallback now uses only local surrounding markup as fallback context, and discards implausible future dates.
- Added `collect_with_stats()` and `CollectorRun` so every source emits status, count, duration, dated count, locale/category, and error text.
- The orchestrator now writes `collector_stats.json` and appends collector source health to Monitoring NDJSON.
- Collectors now derive `source_domain` from each article URL and normalize collection categories (`newsroom`, `rss`, etc.) into canonical source types.
- Added tests that lock the key regression: list-page event dates must not override article-page publication dates.

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
- Collector stats now exist as a run sidecar and Monitoring feed. Next improvement is to add aggregate alert thresholds over dry streak, errors, and dated ratio.
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
- `enrich` can still extract event dates from title/snippet text if an undated collector/search record mentions a future event. `verify` catches most of these through `FUTURE`, but the date_source should be treated as lower confidence than API or URL dates.
- `verify.py` has a small readability wart in its module docstring/import area, but no behavioral impact.

### Fixes made

- Added `resolve_source_locale()` in `normalize`: it now prefers `article.locale`, then `article.raw_metadata.locale`, and only falls back to URL heuristics if no explicit locale exists.
- Added a regression test that ensures explicit `zh-CN` wins over `eet-china.com` URL heuristics.
- Normalize now preserves or recomputes canonical URL, and uses canonical URL plus title for `id` and `content_hash`.
- Normalize now prefers upstream `source_type_hint`/`source_type` over URL heuristics, with aliases such as `newsroom -> official` and `rss -> media`.
- Normalize now carries `engine`, `query_id`, `query_used`, `query_dimension`, and `discovery_mode` into ArticleRecord output for downstream diagnostics.
- `enrich` now rejects implausible future publication dates from snippet, URL, and web metadata extraction instead of letting future event dates become article dates.
- `date_source` is now preserved through `verify` and `normalize`, and required on the ArticleRecord schema as lineage.

### Remaining questions

- Date lineage now exists as `date_source`; the next improvement is to use that lineage for confidence scoring, for example treating `snippet_regex` as weaker than `search_api` or `url_path`.
- Normalize currently drops rejected records silently. That is fine for downstream articles, but a rejection summary artifact would make quality debugging faster.

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
- `cluster` could over-merge when generic terms dominated the article term sets. Thread anchoring helped continuity, but the orphan clustering decision treated entity and term overlap as equally specific.
- `cluster` output only listed article IDs plus aggregate source types/locales. That was enough for joins, but weak for debugging why a cluster formed or whether duplicate URL variants slipped in.
- `edit` relied entirely on prompt discipline for source lines. The fallback parsing was useful, but a common LLM omission was missing source/date lines that could be repaired deterministically from article data.
- `validate` checked that a cited source existed somewhere in the verified article pool, but did not require that the cited source's article actually matched the news item content.

### Fixes made

- `validate_item()` now accepts `max_future_days` and rejects cited dates beyond the configured future window.
- `validate.main()` reads both `pipeline.date_window.max_future_days` and `pipeline.date_window.stale_days` from `domain.yaml`.
- `validate` source-line parsing now strips locale tags defensively, while the Edit prompt and cleanup still require final source lines without `[en]` / `[zh-CN]`.
- `render.convert()` now accepts `tag_config` and renders configured tag badges in item headings.
- `render.main()` now loads `editorial.render_tags` from the domain config and passes it into HTML rendering.
- `cluster` now uses weighted entity/term overlap for orphan clustering, giving entity matches more weight than generic term matches.
- Cluster objects now include `source_domains` and `canonical_urls` as audit fields while keeping `article_ids` as the primary join key.
- `edit` now applies deterministic source-line repair before writing `briefing.md`: missing source/date lines are added only when a news item clearly matches one input article.
- `validate` now checks source-item alignment: a cited source must map to an article from that source with coarse title/body overlap, not merely appear elsewhere in the day's source pool.
- Added tests for domain-configured stale windows, future-date validation, source locale tag cleanup, render tag output, source-line repair, and generic-term over-merge prevention.

### Remaining questions

- Cluster now uses weighted entity/term overlap. A remaining improvement is entity salience: primary entities should eventually count more than incidental mentions.
- Cluster audit fields improve explainability, but the algorithm still lacks an explicit primary-topic model. A bridge article can still connect nearby subtopics through Union-Find if their entity/term overlap clears threshold.
- Edit now has a deterministic first-pass repair for missing source lines. A full LLM retry loop for schema/validation failures is still future work.
- Render tag detection currently uses item title text. If tags need body-aware classification, `convert()` should collect an item block before rendering its heading.
- Validate source-item alignment is intentionally coarse. If future prompts become more abstractive, this should evolve into cluster-aware support checks instead of direct token overlap.

## DB / Story Tracking / Monitoring / Orchestrator review

### What was good

- `db` cleanly separates schema creation, domain seeding, ingest/write helpers, and read APIs.
- `story-tracking` keeps contracts and context-selection logic pure, while SQLite writes stay in `stratum/db`.
- `monitoring` has deterministic health and coverage functions with focused tests.
- `orchestrator/pipeline.py` keeps stage execution in standalone subprocesses, so stages remain independently testable.

### Problems found

- `--from-stage` existed in the CLI and docs but was not actually used to gate execution. Resume runs could unexpectedly re-run earlier stages, including Search and collectors.
- Story context generation read `target_entity_ids` from judgments but ignored `target_thread_ids`. Event-pair judgments from the LLM therefore lost their target thread context before reaching the next prompt.
- SQLite query seeding accepted dimension-grouped `queries.yaml`, but the `queries` table did not persist `dimension`, and DB-backed Search read every DB query as synthetic `dimension=db`. That erased the coverage surface Search had just learned from YAML.
- Coverage monitoring depended on detailed `source_records` carrying `cluster_id`. When only Stage 5 `clusters.json` was available, it ignored the cluster-level `source_types` and `locales` already present in the cluster object and could report false gaps.
- Coverage follow-up generation expected gap `entities`, but `detect_gaps()` did not preserve cluster entities/terms in the gap object. Missing official-source gaps therefore lost the context needed to generate specific official queries.
- Coverage severity still interpreted cluster confidence as historical `A/B/C/D` labels even though current StoryCluster output uses `high/medium/low`. Low-confidence gaps could therefore be downgraded and fail to generate follow-up queries.
- Coverage severity counted only detailed `source_records`, ignoring cluster-level `source_domains`. A cluster summary without detailed records could look source-sparse even when it already carried several source domains.
- DB ingest did not persist search query stats in the normal pipeline path, even though helper APIs existed. Collector source health now feeds Monitoring NDJSON.
- DB read APIs exposed entity snapshots, but not an event-level timeline by entity or term. That made accumulated data hard to reuse for questions like "Samsung's important events over the last six months" or "HBM progress across major companies".

### Fixes made

- Added `PIPELINE_STAGE_ORDER` and `should_run_stage()` to make `--from-stage` real.
- Search-side collectors now run only when Search runs, so resume from a later stage does not mutate existing `raw.json`.
- Story context generation now falls back to `target_thread_ids` when a judgment has no `target_entity_ids`.
- DB schema now includes `queries.dimension`, connection setup applies an additive migration for existing DBs, seeding preserves dimension-grouped query strategy, and DB-backed Search reads the stored dimension.
- `coverage.detect_gaps()` now initializes coverage from cluster-level `source_types` and `locales`, then augments it with detailed source records when available.
- Coverage gaps now retain cluster `entities` and `terms`, so high-severity missing-official gaps can generate entity-specific follow-up queries.
- Coverage severity now normalizes both current `high/medium/low` and legacy `A/B/C/D` confidence labels.
- Coverage severity now uses cluster-level `source_domains` when detailed source records are absent, preventing false high severity caused by missing source-record detail.
- Collector source health is now written to `{health_data_dir}/{domain}/source-daily.ndjson` and a per-run `collector_stats.json` sidecar.
- The orchestrator now writes `run_manifest.json` with stage-level status, outputs, timestamps, summary counts, and hard-failure state before exit.
- Search `raw.stats.json` is now ingested into SQLite query counters after Search, including the new `query_id/results_count` stats shape.
- Entity snapshots now use the same per-run entity article counts derived from `articles.jsonl`, instead of writing placeholder zero counts.
- DB now exposes event-level retrieval helpers for entity histories, term histories, and term-by-company progress groups.
- Added tests for resume gating, DB query dimension persistence, schema execution on empty SQLite, cluster-summary coverage fallback, current/legacy confidence severity, source-domain-aware severity, and DB event timeline retrieval.

### Remaining questions

- Manifest data can now support retries and dashboards, but no retry runner consumes it yet.
- The event timeline helpers currently filter JSON-array columns in Python for SQLite portability. If the DB grows large, add normalized `event_entities` and `event_terms` indexes behind the same read API.

## Contracts / Docs review

### What was good

- `stratum/contracts` provides stable JSON schema locations for raw search results, verified articles, normalized articles, and story clusters.
- Cross-temporal event-thread dataclasses are re-exported through `stratum.contracts`, so tests and callers do not need to import deep implementation paths.
- Required `SCOPE.md` files are now covered by `tests/test_module_docs.py`.
- The current schema files parse as valid JSON.
- `tests/test_contract_schemas.py` now validates representative Search, collector, Verify, Normalize, and Cluster output shapes against the shared JSON schemas.

### Problems found

- `raw_search_result.json` still treated `engine` as a small legacy enum and omitted newer Search/collector fields such as `locale`, `source_domain`, `source_type_hint`, `query_id`, `query_dimension`, `score`, and `published_at`.
- `date_source` lineage was implemented in Enrich/Verify/Normalize, but the raw and verified schemas did not describe all current values, so schema consumers would reject valid pipeline objects.
- Contract consolidation is incomplete: `story-tracking/story_contracts.py` remains local to that subsystem while `contracts/event_thread.py` covers cross-temporal thread state. This is acceptable for now, but the boundary should stay explicit.
- Documentation has to distinguish the user-facing "8 stage" flow from the internal collector sidecar and DB ingest steps. `stratum/stages/SCOPE.md` now does this, but it is an easy area to regress.

### Fixes applied

- Updated `raw_search_result.json` to accept both Search API output and collectors sidecar output, including flexible engine IDs like `rss:<source>` and `direct_fetch:<source>`.
- Added `date_source` to `verified_article.json` and expanded the allowed date-lineage values across raw and verified contracts.
- Added `query_dimension` to the raw Search contract, and required `canonical_url`, `date_source`, `discovery_mode`, and `query_dimension` on ArticleRecord so downstream diagnostics cannot silently lose discovery context.
- Required StoryCluster audit fields (`article_count`, `source_types`, `locales`, `source_domains`, `canonical_urls`, `created`) that current clustering emits and monitoring/debugging relies on.
- Added a module-doc test that requires `stratum/contracts/SCOPE.md` to list each current JSON schema exactly once.
- Expanded `stratum/contracts/SCOPE.md` with discovery-contract notes so the Search/Collectors boundary is explicit.
- Added schema smoke tests that parse every contract, run Draft 7 schema checks, and validate representative current output shapes.

### Remaining questions

- A small golden end-to-end fixture could still validate produced stage artifacts on disk against these schemas, but the main stage output shapes are now covered by focused contract tests.
- Decide whether `EventRecord`, `CausalEdge`, and `Judgment` should move from `story-tracking` into `contracts` once more subsystems depend on them.

## Domains / Config review

### What was good

- Domain-specific knowledge is mostly isolated under `domains/{id}/`, keeping `stratum/` framework code domain-agnostic.
- `domain.yaml` owns entities, source registry, validation policy, source classification, and editorial/render policy.
- `queries.yaml` owns Search query templates and gap searches, which matches how Search and DB seeding actually load queries.
- The storage source registry has clear active/inactive lifecycle fields and explicit access methods.

### Problems found

- `domains/storage/domain.yaml` still carried an old copy of `seed_queries` and `gap_searches`, while the runtime path reads `domains/storage/queries.yaml`. That creates a split-brain query strategy: reviewers may edit one file while production reads the other.
- README still described `domain.yaml` as the only place domain knowledge lives, even though prompts, templates, taxonomy, and `queries.yaml` are intentionally separate domain assets.

### Fixes applied

- Removed stale `seed_queries` and `gap_searches` from `domains/storage/domain.yaml`; `queries.yaml` is now the sole storage Search template source.
- Updated the storage domain header and README to describe the domain directory as the source of truth, with queries explicitly owned by `queries.yaml`.
- Added `tests/test_domain_configs.py` to assert domain configs do not duplicate query templates, every domain has nonempty `queries.yaml`, and active storage sources have collectable registry fields.

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

### Fixes applied

- Updated `make test-schema` to run `tests/test_contract_schemas.py` plus the story event schema tests.
- Added infra tests that parse Makefile pytest commands and assert explicit test paths still exist.
- Updated `pyproject.toml` to `5.0.0` with a current pipeline-oriented description, and added a README/package major-version consistency test.
- Clarified `stratum/db/SCOPE.md` and `stratum/db/ingest.py` comments so DB persistence capabilities are separated from removed runtime modules.

### Remaining questions

- Makefile still contains external `hermes cron run ...` shortcuts for daily/weekly/monthly/quarterly/yearly. They may be useful locally, but they are not self-describing inside this repo and should eventually be documented or replaced with direct `stratum/orchestrator/pipeline.py` commands.
- The DB layer still has multi-scale/cascade persistence hooks. They are valid state primitives, but no current first-class runner consumes them.

## Data Integrity Tests review

### What was good

- The project already separated fixture-level data tests under `tests/data` from runtime artifact checks under `tests/infra/test_data_integrity.py`.
- Fixture tests catch JSON/JSONL parse errors, duplicate IDs, locale format problems, and malformed cluster summaries without requiring network or LLM runs.
- Runtime checks can inspect the latest local daily run, and fall back to a deterministic golden run fixture when no local artifact exists.

### Problems found

- `tests/infra/test_data_integrity.py` still searched for old output directories such as `storage/data/articles/<date>/articles.jsonl` and `storage/data/story-clusters/<date>/story-clusters.json`. Current orchestrator output is `{output_dir}/{domain}/data/{YYYY-MM-DD}/articles.jsonl` and `clusters.json`, so the tests were mostly permanent skips.
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

### Remaining questions

- The golden run fixture covers the artifact contract and references, but it is intentionally small. A future fuller fixture could include real `raw.json`, `enriched.json`, `verified.jsonl`, rendered HTML, and validation reports.

## Prompt / LLM Boundary review

### What was good

- `edit` keeps prompt assembly, LLM transport, markdown repair, and structured-output normalization in separate functions/files.
- The stage has deterministic post-processing for common LLM drift: source locale tags are stripped, missing source lines can be repaired when article support is clear, and `mechanism` can be normalized to judgment `hypothesis`.
- Structured outputs are separated behind `---DATA---` and validated later by the Validate stage when present.

### Problems found

- `llm_client.call_llm()` passed the full JSON payload through `curl -d <payload>`. That can expose the full prompt in process arguments and makes transport behavior harder to test.
- `edit.py` resolved briefing title from `config.yaml` only, so normal domain runs could fall back to `storage早报` instead of `domains/storage/domain.yaml`'s `存储早报`.
- The daily prompt contradicted the lower-level writing rule: one part asked for source domains, while another encouraged professional media aliases and not full domains. It also did not make the no-language-tag rule explicit enough for source lines.

### Fixes applied

- Changed LLM transport to send the payload on stdin via `curl --data-binary @-`, keeping prompts out of argv.
- Added `resolve_domain_title()` and tests so title selection is config override → `domain.yaml` title → fallback.
- Clarified the daily prompt: source lines must use source strings from the provided source index/article data, must include dates, and must not add `[en]`/`[zh-CN]` tags.
- Added tests for LLM stdin transport and title resolution.
- Documented `domains/{domain}/prompts/` as reserved future override assets, removed the unused `prompts_dir` path from orchestrator path resolution, and added docs tests for that boundary.

### Remaining questions

- Domain prompt overrides are now documented as reserved assets. Implementing first-class override support remains optional future work, but the current active prompt path is explicit.
- Full LLM retry on validation failure remains future work; today the stage repairs only a few deterministic output issues.
