# Stratum — Storage Industry Intelligence Pipeline

> **v5.0** — Domain-agnostic framework. 8-stage deterministic pipeline. Three-tier collection (search + direct fetch + RSS + browser). SQLite-backed story tracking. Template-driven HTML/PDF rendering.

## Architecture

```
Stratum/
├── stratum/                     # Framework — zero domain knowledge
│   ├── collectors/              #   Content acquisition beyond search
│   │   ├── direct_fetch.py      #     HTTP GET → HTML parse (newsrooms, blogs)
│   │   ├── rss.py               #     RSS/Atom feed parser
│   │   ├── browser.py           #     Headless Chrome via Playwright
│   │   ├── keywords.py          #     Domain keyword extraction
│   │   └── registry.py          #     Source registry (reads domain.yaml)
│   ├── orchestrator/
│   │   └── pipeline.py          #   Main pipeline executor (8 stages + collector)
│   ├── stages/                  #   8 pipeline stages
│   │   ├── search/              #     Search engine API calls
│   │   ├── enrich/              #     Date extraction from snippets
│   │   ├── verify/              #     Blocklist, date window, magnitude sanity
│   │   ├── normalize/           #     Entity/term extraction, source classification
│   │   ├── cluster/             #     Jaccard + Union-Find story clustering
│   │   ├── edit/                #     LLM-powered dynamic block editing + template assembly
│   │   ├── validate/            #     Content gate (claims vs verified articles)
│   │   └── render/              #     MD → HTML → PDF (template-driven)
│   ├── subsystems/
│   │   ├── search/              #   Search engine abstraction (Tavily, Bocha)
│   │   ├── story-tracking/      #   Cross-day event tracking (SQLite)
│   │   ├── event-thread/        #   Event threading engine
│   │   └── monitoring/          #   Health + coverage tracking
│   ├── db/                      #   SQLite schema, ingest, connection
│   └── contracts/               #   JSON schemas (data contracts)
│
├── domains/                     # Domain-owned config and assets
│   ├── storage/                 #   Storage industry
│   │   ├── domain.yaml          #     Companies, terms, source_registry, pipeline rules
│   │   ├── queries.yaml         #     Search queries by locale (5 locales)
│   │   ├── taxonomy.yaml        #     Industry taxonomy
│   │   ├── prompts/daily.md     #     Reserved domain prompt override asset
│   │   └── templates/daily.html #     HTML template
│   └── robot/                   #   Robotics (placeholder)
│
├── tests/                       # Unit + integration + data integrity tests
├── config.yaml                  # Runtime config (output_dir, db_dir, API keys)
└── config.example.yaml          # Config template
```

## Pipeline (8 stages + collector)

```
Stage 1.0:  Search     → raw.json         (Tavily/Bocha search APIs)
Stage 1.5:  Collect    → raw.json merge   (direct_fetch + RSS + browser)
Stage 2:    Enrich     → enriched.json    (date extraction)
Stage 3:    Verify     → verified.jsonl   (blocklist, freshness, magnitude)
Stage 4:    Normalize  → articles.jsonl   (entities, terms, classification)
Stage 5:    Cluster    → clusters.json    (Jaccard story grouping)
Stage 6:    Edit       → briefing.md      (dynamic block editing + template assembly)
Stage 7:    Validate   → gate pass/fail   (claims vs verified articles)
Stage 8:    Render     → HTML + PDF       (template-driven)
```

**Collection tiers** (source_registry in domain.yaml):

| Tier | Method | Sources |
|------|--------|---------|
| `direct_fetch` | HTTP + HTML parse | Micron newsroom/blog, SK hynix, WD blog |
| `rss` | XML feed parse | ServeTheHome, StorageNewsletter, EE Times, SemiEngineering |
| `browser` | Playwright headless | Samsung newsroom/tech-blog, WD newsroom |
| `site:` queries | Tavily search | Digitimes, TrendForce, Tom's Hardware, etc. |
| `broad` queries | Tavily search | New source discovery |

**Iron law**: `stratum/` has **zero** hardcoded domain data. Domain-owned knowledge lives under `domains/{id}/`: `domain.yaml` for entities, sources, validation/editorial rules; `queries.yaml` for search templates; HTML template files for rendering. The active Edit engine lives in `stratum/stages/edit/`: it builds dynamic categories from normalized evidence, edits those blocks with LLM calls, and renders Markdown through timescale templates in `stratum/stages/edit/templates/`. Domain prompt files under `domains/{id}/prompts/` are reserved for future override support.

**Edit artifacts**: Stage 6 writes `briefing.md` plus debugging sidecars:

| Artifact | Meaning |
|---|---|
| `briefing_plan.json` | Dynamic category plan, selected items, omitted/dropped candidates |
| `briefing_chunks.json` | Category block edit outputs. The filename is kept for compatibility; the content is block-oriented in Edit v3. |
| `edit_trace.json` | Block status, timescale, category counts, and plan counts |
| `event-threads.json` | Optional structured thread/edge/judgment data for DB ingest |

The orchestrator is currently daily-first (`make weekly/monthly/quarterly/yearly` intentionally exits), but the Edit engine has manifest profiles and Markdown templates for `daily`, `weekly`, `monthly`, `quarterly`, and `yearly`.

## Quick Start

```bash
# Full pipeline
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-30

# Skip LLM stages (deterministic only, requires raw.json)
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-30 \
    --raw-input raw.json --skip-agent

# Collector test (no API calls)
python -c "
from stratum.collectors import collect
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
# Reserved: prompts/daily.md (future domain prompt override)
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

1. **Domain directory is truth** — domain knowledge lives under `domains/{id}/`, with queries kept in `queries.yaml`
2. **Pure function stages** — every stage reads input, writes output, no side effects
3. **Collector > search** — direct source access wins over search API results
4. **Template-driven rendering** — render.py knows nothing about content; templates own layout
5. **SQLite for persistence** — story tracking, entity snapshots, query stats all in DB

## License

MIT
