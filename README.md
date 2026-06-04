# Stratum — Storage Industry Intelligence Pipeline

> **v0.1.0** — Storage-domain 0.1 line moving toward 0.2. Daily pipeline with explicit validate-repair-revalidate flow, DB-backed story tracking, higher-scale synthesis, custom report windows, and template-driven HTML/PDF rendering.

## Architecture

```
Stratum/
├── stratum/                     # Framework — zero domain knowledge
│   ├── sourcing/
│   │   ├── watchlist/       #     RSS + fixed URL source acquisition
│   │   └── discovery/          #     Bocha/Tavily broad discovery
│   ├── orchestrator/
│   │   └── pipeline.py          #   Main pipeline executor (daily stages + watchlist)
│   ├── capabilities/            #   Additive MCP-ready and agent-ready capability layer
│   ├── mcp_adapter/             #   Additive MCP-style tool adapter over capabilities
│   ├── stages/                  #   Daily pipeline stages
│   │   ├── acquisition/         #     Query-driven discovery over seeded raw evidence
│   │   ├── enrich/              #     Date extraction from snippets
│   │   ├── verify/              #     Blocklist, date window, magnitude sanity
│   │   ├── normalize/           #     Entity/term extraction, source classification
│   │   ├── cluster/             #     Jaccard + Union-Find story clustering
│   │   ├── edit/                #     LLM-powered dynamic block editing + template assembly
│   │   ├── validate/            #     Content gate (claims vs verified articles)
│   │   ├── repair/              #     Post-validate rewrite/drop pass
│   │   └── render/              #     MD → HTML → PDF (template-driven)
│   ├── subsystems/
│   │   ├── story_tracking/      #   Cross-day event tracking (SQLite)
│   │   ├── event_thread/        #   Event threading engine
│   │   └── monitoring/          #   Health + coverage tracking
│   ├── db/                      #   SQLite schema, ingest, connection
│   └── contracts/               #   JSON schemas (data contracts)
│
├── domains/                     # Domain-owned config and assets
│   ├── storage/                 #   Storage industry
│   │   ├── domain.yaml          #     Companies, terms, source_registry, pipeline rules
│   │   ├── queries.yaml         #     Search queries by locale (5 locales)
│   │   ├── taxonomy.yaml        #     Industry taxonomy
│   │   └── templates/daily.html #     HTML template
│   └── robot/                   #   Robotics (placeholder)
│
├── tests/                       # Unit + integration + data integrity tests
├── config.yaml                  # Runtime config (output_dir, db_dir, API keys)
└── config.example.yaml          # Config template
```

## Pipeline (daily stages + watchlist)

```
Stage 1.0:  Watchlist → raw.json seed  (RSS + direct_fetch + browser)
Stage 1.5:  Acquisition  → raw.json merge (Bocha/Tavily discovery supplement)
Stage 2:    Enrich     → enriched.json    (date extraction)
Stage 3:    Verify     → verified.jsonl   (blocklist, freshness, magnitude)
Stage 4:    Normalize  → articles.jsonl   (entities, terms, classification)
Stage 5:    Cluster    → clusters.json    (Jaccard story grouping)
Stage 6:    Edit       → {Domain}_{Timescale}_Briefing_{Period}.md      (dynamic block editing + template assembly)
Stage 7:    Validate          → validate_report.json      (claims vs verified articles)
Stage 8:    Repair            → repair_report.json        (rewrite/drop invalid items when needed)
Stage 9:    Validate Recheck  → validate_report.json      (final gate after repair)
Stage 10:   Render            → HTML + PDF                (template-driven)
```

**Acquisition channels**:

| Tier | Method | Sources |
|------|--------|---------|
| `direct_fetch` | HTTP + HTML parse | Micron newsroom/blog, SK hynix, WD blog |
| `rss` | XML feed parse | ServeTheHome, StorageNewsletter, EE Times, SemiEngineering |
| `browser` | Playwright headless | Samsung newsroom/tech-blog, WD newsroom |
| `discovery` | Bocha/Tavily query execution | Coverage gaps, DB watch queries, broad discovery |

**Iron law**: `stratum/` has **zero** hardcoded domain data. Domain-owned knowledge lives under `domains/{id}/`: `domain.yaml` for entities, sources, validation/editorial rules; `queries.yaml` for search templates; HTML template files for rendering. The active Edit engine lives in `stratum/stages/edit/`: it builds dynamic categories from normalized evidence, edits those blocks with LLM calls, and renders Markdown through timescale templates in `stratum/stages/edit/templates/`.

**Edit artifacts**: Stage 6 writes the canonical Markdown briefing artifact
`{Domain}_{Timescale}_Briefing_{Period}.md` plus debugging sidecars:

| Artifact | Meaning |
|---|---|
| `briefing_plan.json` | Dynamic category plan, selected items, omitted/dropped candidates |
| `briefing_chunks.json` | Category block edit outputs. The filename is kept for compatibility; the content is block-oriented in Edit v3. |
| `edit_trace.json` | Block status, timescale, category counts, and plan counts |
| `validate_report.json` | Item-level validate findings, violation counts, and sidecar telemetry |
| `repair_report.json` | Item-level rewrite/drop actions, support-article lineage, and repair counters |
| `event-threads.json` | Optional structured thread/edge/judgment data for DB ingest |

The orchestrator runs the daily stage chain for `daily`; `weekly`, `monthly`,
`quarterly`, and `yearly` use the DB-native timescale temporal runner with same-scale
exploring, DB synthesis, Markdown, render, and run-manifest output.

`stratum/capabilities/` is an additive layer for future MCP-style exposure and
agent orchestration. It does not replace the current pipeline; it provides a
stable callable surface and task wrappers around selected analysis and semantic
read capabilities, including collection diagnostics such as discovery quality
inspection and watchlist source-expansion evaluation.

The active daily report template uses five fixed major chunk keys: `today`,
`industry`, `signals`, `focus`, and `contrarian`. Dynamic evidence categories
are rendered as subsections under the industry chunk; weak/edge items are
grouped under the signals chunk and keep the configured localized edge-signal
title prefix for machine counting.

Edit keeps raw search data immutable, then applies deterministic boilerplate
rules to the evidence surface before LLM calls. Generic cleanup rules live in
the Edit stage, while source-specific template markers such as site navigation,
QR follow blocks, tags, quote centers, or fast-news modules are configured in
`domain.yaml` under `pipeline.boilerplate`. Validate reuses the same rule set
and fails the report if generated Markdown still contains those markers.

The validate gate now writes `validate_report.json` even on success. When
violations remain, the orchestrator runs a deterministic Repair stage that
rewrites or drops invalid items, writes `repair_report.json`, then re-runs
Validate before Render is allowed to publish.

## Development vs Deployment

Development runs use the working tree:

```bash
make daily DOMAIN=storage DATE=2026-05-30
make weekly DOMAIN=storage DATE=2026-W22
make monthly DOMAIN=storage DATE=2026-05
```

Deployment runs are tag-locked and isolated from the development checkout:

```bash
make release VERSION=v0.1.1
make deploy VERSION=v0.1.1 ENV=production DOMAIN=storage \
    DEPLOY_ROOT="$HOME/stratum/deployments" \
    DEPLOY_CONFIG=/secure/stratum/config.yaml \
    OUTPUT_DIR="$HOME/stratum/reports"
make run-deployed-daily ENV=production DOMAIN=storage DATE=2026-05-30 \
    DEPLOY_ROOT="$HOME/stratum/deployments"
```

Deployment accepts Git tags only, writes `deployment_manifest.json`, and every
pipeline `run_manifest.json` records runtime mode, release version, commit, and
deployment id. See [Deployment](docs/DEPLOYMENT.md).

For Codex collaboration rules and documentation layout, start with
[AGENTS.md](AGENTS.md) and [Documentation Map](docs/README.md).

## Quick Start

```bash
# Full pipeline
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-30

# Higher-scale temporal run
python stratum/orchestrator/pipeline.py --domain storage --timescale weekly --date 2026-W22

# Skip LLM stages (deterministic only, requires raw.json)
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-30 \
    --raw-input raw.json --skip-agent

# Watchlist acquisition test (no API calls)
python -c "
from stratum.sourcing.watchlist import collect
results = collect('storage', '.', '2026-05-30')
print(f'{len(results)} articles')
"
```

## Adding a New Domain

```bash
cp -r domains/storage domains/new_domain
# Edit domain.yaml (companies, terms, sources, pipeline rules)
# Edit queries.yaml (search queries by locale)
# Optional: templates/daily.html (HTML template)
```

Zero framework changes required.

## Development

```bash
# Run all tests
make test

# Run fast unit tests while iterating
make test-unit

# Run a specific test file
make test-file FILE=tests/test_search.py
```

## Design Principles

Stratum's project-level laws are in [Engineering Rules](docs/ENGINEERING_RULES.md).
In short:

1. Preserve the working intelligence pipeline.
2. Keep ownership singular.
3. Make handoffs explicit.
4. Delegate by responsibility.
5. Keep evidence auditable.
6. Let documentation earn its place.

## License

MIT
