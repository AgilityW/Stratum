# Stratum — Multi-Scale Industry Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-Agent%20Skill-orange)](https://hermes-agent.nousresearch.com)

A multi-scale intelligence system for the Hermes agent platform. Five time scales (daily → weekly → monthly → quarterly → yearly), six data layers (Article → StoryCluster → EventThread → TrendTheme → QuarterlyThesis → AnnualNarrative), and a decoupled source intelligence subsystem that discovers, evaluates, and manages information channels.

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

## Cron Schedule

| Time | Job | Deliver |
|:---|:---|:---|
| Daily 7:00 CST | Stratum - Collect | Local |
| Daily 7:20 CST | Stratum - Render | WeChat PDF |
| Sunday 8:00 | Stratum - Weekly | Local |
| 1st of month 8:00 | Stratum - Monthly | Local |
| 1st of quarter 8:00 | Stratum - Quarterly | Local |
| Jan 2 8:00 | Stratum - Yearly | Local |

## Output

```
~/WorkSpace/Stratum/
├── storage/
│   ├── storage-{date}.md
│   └── storage-{date}.pdf
└── data/
    ├── articles/{date}/articles.jsonl
    ├── story-clusters/{date}/story-clusters.json
    ├── event-threads/event-threads.json
    ├── sources/{date}/source-records.jsonl
    ├── sources/profiles/{source}.json
    ├── sources/trial-pool.json
    ├── trend-themes/{month}/trend-themes.json
    ├── quarterly-theses/{quarter}/thesis-outcomes.json
    └── annual-narratives/{year}/annual-narrative.json
```

## Languages

4 languages by default: `zh-CN`, `zh-TW`, `en`, `ja`, `ko`. Add a language in one config line. Add queries in one domain.yaml section.

## Documentation

- `docs/multi-scale-intelligence-architecture.md` — content architecture
- `docs/source-intelligence-architecture.md` — source intelligence architecture
- `MULTI_SCALE_INTELLIGENCE_ARCHITECTURE.md` — original design spec
- `CONTRIBUTING.md` — contribution guide

## License

MIT — see [LICENSE](LICENSE).
