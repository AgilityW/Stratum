# Stratum — Multi-Scale Industry Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-Agent%20Skill-orange)](https://hermes-agent.nousresearch.com)

> **Implementation Status**: 18 skill modules defined (SKILL.md + supporting code). Content pipeline, source intelligence, and multi-scale briefings are spec-complete. `source-graph-engine` is the only module with standalone Python code; most modules execute as LLM agent instructions on the Hermes platform. P0 Python bugs in source-graph-engine are being fixed. End-to-end pipeline testing is the next milestone (see TODO.md).

A multi-scale industry intelligence system for the Hermes agent platform. Five time scales (daily → weekly → monthly → quarterly → yearly), six data layers (Article → StoryCluster → EventThread → TrendTheme → QuarterlyThesis → AnnualNarrative), and a decoupled source intelligence subsystem that discovers, evaluates, and manages information channels.

## Quick Start

```bash
git clone https://github.com/<user>/stratum.git
cd stratum

cp config.example.yaml config.yaml
./install.sh --dev
```

Set API keys:
- `BOCHA_API_KEY` — Chinese/zh-CN/zh-TW search
- `TAVILY_API_KEY` — English/Japanese/Korean/global search

## Architecture

### Content Pipeline (Steps 0-8)

```
config → locale-router → collection → verify
  → article-normalizer → story-cluster-engine → event-thread-engine
  → edit → .md
```

### Multi-Scale Pipelines (independent crons)

```
Daily brief → Weekly brief → Monthly brief → Quarterly review → Yearly review
     ↑              ↑              ↑               ↑                ↑
 StoryCluster   EventThread    TrendTheme    QuarterlyThesis   AnnualNarrative
```

### Source Intelligence (decoupled, Steps 2.6 + 8.5-8.6)

```
source-graph-engine (discover new domains)
  → trial-source-manager (manage trial queue)
    → source-recorder (read finalized content → write source-records)
      → source-profiler (aggregate → SourceProfile with checkpoints)
```

Source pipeline consumes content outputs, never modifies them. Content pipeline is unaware of source intelligence.

## Modules (18 skills)

| Module | Role | Layer |
|:---|:---|:---|
| `stratum` | Orchestration framework v4.0 | Content |
| `stratum-storage` | Channel: editorial rules, queries, domain data | Content |
| `locale-router` | BCP 47 expansion, engine↔locale matching | Content |
| `source-manager` | URL preflight + auto-healing | Content |
| `verify-engine` | Date / magnitude / fiscal-year checks | Content |
| `article-normalizer` | Raw results → ArticleRecord JSONL | Content |
| `story-cluster-engine` | Articles → same-day StoryClusters | Content |
| `event-thread-engine` | Cross-day thread tracking + lifecycle | Content |
| `source-graph-engine` | Entity/term/channel graph evolution | Content |
| `health-tracker` | Source hit rate stats | Content |
| `render-engine` | MD → HTML → PDF | Content |
| `trial-source-manager` | Trial pool queue management | Source |
| `source-recorder` | Read content → write source-records.jsonl | Source |
| `source-profiler` | Aggregate SourceRecords → SourceProfile | Source |
| `weekly-briefing` | 7-day thread change analysis | Multi-scale |
| `monthly-briefing` | TrendTheme synthesis | Multi-scale |
| `quarterly-review` | Thesis evaluation + judgment calibration | Multi-scale |
| `yearly-review` | Annual narrative + structural change | Multi-scale |

*Note: `stratum-deployment` is a deployment reference document, not a pipeline module. 18 pipeline skills total.*

## Languages

4 source languages expand to 5 locales: `zh` → `zh-CN` + `zh-TW`, plus `en`, `ja`, `ko`. Add a language in one config line. Add queries in one domain.yaml section.

## Cron Schedule (7 jobs)

| Time | Job | Deliver |
|:---|:---|:---|
| Daily 7:00 CST | Stratum - Collect | Local |
| Daily 7:20 CST | Stratum - Render | WeChat PDF |
| Sunday 8:00 | Stratum - Weekly | Local |
| 1st of month 8:00 | Stratum - Monthly | Local |
| 1st of quarter 8:00 | Stratum - Quarterly | Local |
| Jan 2 8:00 | Stratum - Yearly | Local |
| Thu 23:50 | Storage Weekly Report | WeChat |

The daily pipeline runs Steps 0-8.6 in Collect, Steps 9-10 in Render. See `skills/stratum/SKILL.md` for full step definitions.

## Output

```
~/WorkSpace/Stratum/{channel}/
├── {channel}-{date}.md
├── {channel}-{date}.pdf
└── data/
    ├── articles/{date}/articles.jsonl
    ├── story-clusters/{date}/story-clusters.json
    ├── event-threads/event-threads.json
    ├── graphs/storage-graph.json
    ├── sources/{date}/source-records.jsonl
    ├── sources/profiles/{source}.json
    ├── sources/trial-pool.json
    ├── trend-themes/{month}/trend-themes.json
    ├── quarterly-theses/{quarter}/thesis-outcomes.json
    └── annual-narratives/{year}/annual-narrative.json
```

## Documentation

- `docs/multi-scale-intelligence-architecture.md` — content architecture
- `docs/source-intelligence-architecture.md` — source intelligence architecture
- `CONTRIBUTING.md` — contribution guide

## License

MIT — see [LICENSE](LICENSE).
