# stages — 8-stage briefing pipeline

## Purpose

`stratum/stages` contains the executable production chain that turns search and collector results into a rendered briefing.

The orchestrator runs these stages in order:

1. collector collection, via `stratum.collectors`
2. `search`
3. `enrich`
4. `verify`
5. `normalize`
6. `cluster`
7. `edit`
8. `validate`
9. `render`

The user-facing pipeline still calls this the "8 stage" flow because collectors are a sidecar seed before search, not a numbered stage script.

## Stage Contracts

| Stage | Determinism | Primary input | Primary output | Responsibility |
|:---|:---|:---|:---|:---|
| collectors sidecar | network-dependent | `domain.yaml` source registry | seeded `raw.json` | Fetch configured RSS/browser/direct sources first. |
| `search` | external APIs | `config.yaml` plus DB queries or `queries.yaml` plus existing `raw.json` | `raw.json` | Run the configured search subsystem, skip covered domain-scoped queries, and merge supplemental raw result objects. |
| `enrich` | deterministic unless `--web-extract` | `raw.json` | `enriched.json` | Fill missing publication dates from API metadata, snippets, URLs, or optional page fetches. |
| `verify` | deterministic | `enriched.json` plus `domain.yaml` | `verified.jsonl` | Apply freshness, URL, duplication, blocklist, and source quality gates. |
| `normalize` | deterministic | `verified.jsonl` plus `domain.yaml` | `articles.jsonl` | Convert verified records into ArticleRecord-like rows with entities, terms, source metadata, and optional event-thread matches. |
| `cluster` | deterministic | `articles.jsonl` | `clusters.json` | Group related articles by event-thread anchor and entity/term overlap. |
| `edit` | LLM-dependent | `articles.jsonl`, `clusters.json`, story context | `briefing.md`, `briefing_plan.json`, `briefing_chunks.json`, `edit_trace.json`, optional `event-threads.json` | Build dynamic evidence categories, edit category blocks with the LLM, render through the timescale template, and produce structured thread data. |
| `validate` | deterministic | `briefing.md`, `articles.jsonl`, optional schemas | exit status and JSON report | Check cited sources, cited dates, and structured event-thread schema validity. |
| `render` | deterministic, PDF shell-out optional | `briefing.md`, template | `briefing.html`, optional `briefing.pdf` | Convert Markdown to template-backed HTML, then use local Chrome for PDF when available. |

## Detailed Flow

### 1. search

`search/search.py` is now a wrapper around `stratum.subsystems.search`.

Inputs:
- `--config config.yaml` for API keys, engine settings, and `.env` resolution.
- `--db <domain.db>` for current DB-backed discovery queries, plus `--queries <queries.yaml>` as the baseline fallback.
- `--date YYYY-MM-DD` for date-aware engine calls and freshness scoring.

Output:
- JSON array of merged collector/search result dictionaries in `raw.json`.
- Search quality and execution sidecar in `raw.stats.json`.

Important boundary:
- No legacy curl scripts or old search implementation should be reintroduced here.
- A present DB file is not treated as sufficient by itself. If it has no active
  daily queries, the stage falls back to `queries.yaml` so Search does not
  silently produce an empty raw pool.
- `queries.yaml` uses the structured `queries` schema. It may be either
  `queries: intent -> locale -> list` for simple domains or
  `queries: intent -> dimension -> locale -> list` for coverage-aware domains.
  Search normalizes these into `{id, text, locale, intent, dimension}`.
  Query items may also carry `include_domains`, which Tavily receives as hard
  source filters. This is the preferred shape for source-first/official-site
  queries; legacy `site:` text still works but is no longer the only option.
- Search diagnostics live in `raw.stats.json`, not in `raw.json`. They cover
  per-query status plus raw-vs-curated locale/dimension/source-type coverage,
  source-type shortfalls, low-yield queries, and top contributing domains.
- Search results preserve original `url` but add `canonical_url` for dedupe.
  Canonicalization strips tracking query parameters/fragments and normalizes
  common `www.`/`m.` host variants.
- `raw.json` is the only raw dataset for a domain/date run. Curated counts and
  quality diagnostics live in sidecars or downstream artifacts, not in extra raw
  JSON copies.

### 2. collectors sidecar

Collectors are not a separate numbered stage script. The orchestrator calls them before Search and seeds `raw.json`; Search then uses that higher-priority evidence to avoid repeat domain-scoped API calls.

Inputs:
- `domain.yaml` `source_registry.sources`
- domain keyword config
- current run date

Supported collectors:
- RSS/Atom feeds
- direct page fetches
- browser-backed sources when Playwright is installed

Output:
- Search-shaped records written into the same single raw result set.

Important boundary:
- Collector failures should degrade a source, not invalidate the whole briefing run.
- Browser collection is optional and must report missing Playwright clearly.

### 3. enrich

`enrich/enrich.py` adds or repairs publication dates.

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
collector or upstream-derived dates as `search_api`.

### 4. verify

`verify/verify.py` decides which enriched records are allowed into the briefing evidence set.

Inputs:
- `enriched.json`
- `domain.yaml`
- run date

Output:
- JSONL `verified.jsonl`
- JSON sidecar `verified.stats.json` with verification totals, rejection
  reasons, date-confidence counts, and quality-flag counts

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
- Verify preserves upstream `date_source` when present. If an enriched/raw
  record has metadata dates but no lineage, Verify marks it as `search_api`;
  if Verify itself extracts a date from title/snippet text, it marks
  `snippet_regex`; records rejected with no usable date emit `none`.
- Verify emits `date_confidence` and `quality_flags` so weak inferred freshness
  is visible to Normalize, clustering/debugging, and future editorial policy.
- Verify writes a stats sidecar next to `verified.jsonl` by default, or to
  `--stats` when the orchestrator supplies an explicit path. This keeps
  rejection diagnostics machine-readable instead of only printed to stderr.

### 5. normalize

`normalize/normalize.py` converts verified search-like records into stable article records.

Inputs:
- `verified.jsonl`
- `domain.yaml`
- optional `thread_keywords.json`

Output:
- JSONL `articles.jsonl`

Adds:
- stable article id based on canonical URL plus title
- canonical URL preserved from Verify or recomputed with the Search canonicalizer
- `source`, `source_type`, `source_locale`, and `date_source`
- upstream `engine`, `query_id`, `query_used`, `query_dimension`, and `discovery_mode`
- extracted entities, terms, numeric claims, artifact type
- optional `event_thread_id`

Important boundary:
- Upstream explicit metadata wins over heuristics. For example,
  `source_type_hint` from Search/Collectors is preferred over URL
  reclassification, and explicit `locale` is preferred over domain guessing.
- URL fallback source classification uses domain-boundary matching instead of
  loose substring matching, so impostor domains such as `fakesamsung.com` cannot
  inherit official-source treatment from configured `samsung.com` rules.
- `content_hash` uses canonical URL plus title so mobile/tracking URL variants
  do not become distinct ArticleRecords.
- `thread_keywords.json` may assign `event_thread_id`, but only keywords/topics
  that actually match the article text are added to `terms`. Unmatched thread
  vocabulary must not pollute ArticleRecord terms.

### 6. cluster

`cluster/cluster.py` groups normalized articles into story clusters.

Inputs:
- `articles.jsonl`
- `domain.yaml`
- run date

Output:
- `clusters.json`

Algorithm:
- force-merge articles sharing `event_thread_id`
- cluster remaining articles by weighted entity/term overlap; entity overlap
  carries more weight than generic term overlap, and shared primary entities
  carry more salience than incidental secondary-entity overlap
- review orphan clusters for bridge over-merge: when a component has no entity
  shared by every article, it is split by primary entity so one article cannot
  connect distinct subjects only through pairwise overlap
- split oversized orphan clusters recursively with a stricter threshold, with
  a minimum split threshold of `0.35` so low-threshold discovery does not keep
  oversized generic components intact

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
- `briefing.md`
- `briefing_plan.json` with dynamic categories, selected items, and dropped
  candidates
- `briefing_chunks.json` with category block edit outputs; the filename is
  retained for compatibility with previous chunk artifacts
- `edit_trace.json` with mode, timescale, category/block status, and counts
- optional `event-threads.json` when the LLM emits `threads`, `causal_edges`,
  or `judgments`

Important boundary:
- Edit uses `planner.py`, `category_block.md`, `profile_polish.md`, and the
  timescale templates. Manifest profiles are expected to set
  `budget.edit_mode: v3`; non-v3 edit modes fail fast.
- Raw search data is not rewritten by Edit. `boilerplate.py` applies
  deterministic generic and `domain.yaml` source-specific cleanup rules to the
  evidence surface before LLM calls, and Edit fails fast if generated briefing
  or block artifacts still contain configured boilerplate markers.
- LLM transport lives in `llm_client.py`.
- The orchestrator currently invokes Edit with `--timescale daily`; other
  timescale profiles are present for direct Edit use and future orchestrator
  entrypoints, but weekly/monthly/quarterly/yearly pipeline runners are not
  first-class yet.
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
  and skips structural sections such as `今日要点`, `行业要点`, `产业信号`,
  `特别关注`, and `反向信号`.
- The active daily template has five major chunks: `今日要点`, `行业要点`,
  `产业信号`, `特别关注`, and `反向信号`. `行业要点` contains the dynamic
  evidence-derived category subsections; `产业信号` contains weak/edge signals
  whose item titles still carry the `【边缘信号】` prefix for downstream
  counting and validation compatibility.

### 8. validate

`validate/validate.py` is the content gate after LLM editing.

Inputs:
- `briefing.md`
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
- Validate reuses the same `pipeline.boilerplate` rule contract as Edit so
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

`render/render.py` turns the validated Markdown into user-facing artifacts.

Inputs:
- `briefing.md`
- HTML template
- title/date/footer strings
- optional `domain.yaml` render tags

Output:
- `briefing.html`
- `briefing.pdf` only when local Chrome exists and succeeds

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
- `stratum/subsystems/search`
- `stratum/collectors`
- optional local Chrome for PDF

Downstream dependencies:
- `stratum/orchestrator/pipeline.py`
- `stratum/db/ingest.py` for post-run event-thread ingestion
- `stratum/subsystems/story-tracking` for context and next-run keyword export

## Design Rules

- Keep stages executable as standalone scripts.
- Keep domain knowledge in domain config, not hardcoded stage code.
- Keep search and edit as the only external intelligence boundaries.
- Treat collectors as additive evidence acquisition, not a replacement for search.
- Prefer deterministic validation after every LLM boundary.
