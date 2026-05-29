# Stratum — Multi-Scale Industry Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Status**: v5.0 — Layered architecture. Domain-agnostic framework (`stratum/`) with domain configs (`domains/`). 8-stage deterministic pipeline. Template-driven rendering. 862 tests, 0 failures.

## Architecture (v5.0)

```
Stratum/
├── stratum/                    # Framework — zero domain knowledge
│   ├── stages/                 # 6 deterministic stages (pure functions)
│   │   ├── enrich/             #   Date extraction from search snippets
│   │   ├── verify/             #   Article verification (blocklist/date/magnitude)
│   │   ├── normalize/          #   Article normalization (entities/terms/classification)
│   │   ├── cluster/            #   Story clustering (Jaccard + Union-Find)
│   │   ├── validate/           #   Content gate (briefing claims vs verified articles)
│   │   └── render/             #   MD→HTML→PDF (template-driven)
│   ├── orchestrator/           # Pipeline executor + agent interface
│   ├── contracts/              # JSON schemas (data contracts)
│   └── subsystems/             # Decoupled intelligence engines
│       ├── source-graph/       #   Entity/Term/Channel graph evolution ✅
│       ├── event-thread/       #   Cross-day story tracking (placeholder)
│       ├── value-chain/        #   Multi-layer exploration (placeholder)
│       ├── monitoring/         #   Health/coverage tracking (placeholder)
│       └── source-management/  #   Source lifecycle (placeholder)
│
├── domains/                    # Domain configs — the ONLY place with domain data
│   ├── storage/                #   Storage industry ✅
│   │   ├── domain.yaml         #     Companies, terms, pipeline rules, editorial
│   │   ├── queries.yaml        #     Search queries by locale
│   │   ├── prompts/daily.md    #     Agent edit prompt
│   │   └── templates/daily.html#     HTML template
│   └── robot/                  #   Robotics industry 🤖 (placeholder)
│
├── briefings/                  # Briefing type definitions (framework layer)
│   ├── daily/SKILL.md
│   └── weekly/SKILL.md
│
└── skills/                     # Hermes agent skills (runtime instructions)
```

## Pipeline (8 stages)

```
1. Agent Search  → raw.json        (LLM — external agent)
2. enrich        → enriched.json   (deterministic, regex date extraction)
3. verify        → verified.jsonl  (deterministic, blocklist/date/magnitude)
4. normalize     → articles.jsonl  (deterministic, entity/term classification)
5. cluster       → clusters.json   (deterministic, Jaccard similarity)
6. Agent Edit    → briefing.md     (LLM — external agent)
7. validate      → gate pass/fail  (deterministic, source/date verification)
8. render        → HTML + PDF      (deterministic, template-driven)
```

**Iron law**: `stratum/` contains **zero** hardcoded domain knowledge. No company names, no technology terms, no industry keywords. Everything flows from `domains/{id}/domain.yaml`.

## Quick Start

```bash
# Full pipeline (agent handles search & edit)
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-28

# Deterministic-only stages (skip LLM — requires raw.json from previous run)
python stratum/orchestrator/pipeline.py --domain storage --date 2026-05-28 \
    --raw-input raw.json --skip-agent

# Run individual stage
python stratum/stages/verify/verify.py \
    --input enriched.json --output verified.jsonl \
    --date 2026-05-28 --domain domains/storage/domain.yaml
```

## Adding a New Domain

```bash
cp -r domains/storage domains/your_domain
vim domains/your_domain/domain.yaml   # Edit companies, terms, sources, queries
vim domains/your_domain/queries.yaml  # Edit search queries
vim domains/your_domain/prompts/daily.md  # Edit agent prompt
vim domains/your_domain/templates/daily.html  # Optional: custom HTML template
```

**Zero framework changes.** Domain config is the single source of truth.

## Adding a New Briefing Type

```bash
cp domains/storage/templates/daily.html domains/storage/templates/weekly.html
# Edit CSS, layout, section structure as needed
```

Pass `--template` to the render stage. No code changes.

## Development

```bash
# Run all tests
python -m pytest tests/ stratum/stages/ -q

# Run specific stage tests
python -m pytest stratum/stages/render/tests/ -v

# Lint
python -m pytest --tb=short
```

## Design Principles

1. **Code gates over prompt fixes** — architecture problems are solved in code, not in prompts
2. **Pure function stages** — every deterministic stage reads input, writes output, no side effects
3. **Domain config is truth** — `domain.yaml` is the only place domain data lives
4. **Template-driven rendering** — render.py knows nothing about briefing types; the template file defines everything
5. **Test coverage is mandatory** — every stage, every function, every refactor gets tests

## License

MIT
