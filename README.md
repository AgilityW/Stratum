# Stratum — Multi-Scale Industry Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-Agent%20Skill-orange)](https://hermes-agent.nousresearch.com)

> **Status**: v4.1 — 20 skill modules. Content pipeline (Steps 0-10), source intelligence subsystem, value chain exploration (11-layer model with dynamic evolution), and multi-scale briefings (daily→yearly) are spec-complete and operational. End-to-end pipeline tested with storage channel producing daily PDF briefings. `source-graph-engine` is the only module with standalone Python code; most modules execute as LLM agent instructions on the Hermes platform.

A multi-scale industry intelligence system for the Hermes agent platform. Five time scales (daily → weekly → monthly → quarterly → yearly), six data layers (Article → StoryCluster → EventThread → TrendTheme → QuarterlyThesis → AnnualNarrative), and a decoupled source intelligence subsystem that discovers, evaluates, and manages information channels.

## Quick Start

```bash
git clone https://github.com/<user>/stratum.git
cd Stratum

cp config.example.yaml config.yaml
# Edit config.yaml — set output_dir to your preferred output path
./install.sh --dev
```

Set API keys:
- `BOCHA_API_KEY` — Chinese/zh-CN/zh-TW search
- `TAVILY_API_KEY` — English/Japanese/Korean/global search

### Configuration

Key settings in `config.yaml`:

```yaml
# Paths — edit for your machine
output_dir: "$HOME/WorkSpace/Stratum"       # all output files go here
health_data_dir: "$HOME/WorkSpace/Stratum/health-data"
chrome_path: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

All SKILL.md paths use `${OUTPUT_DIR}` — resolved from config.yaml at runtime. Change `output_dir` in one place; everything else follows.

## Architecture

### Content Pipeline (Steps 0-10)

```
config → locale-router → collection → verify
  → article-normalizer → story-cluster-engine → event-thread-engine
  → source-graph-engine (evolve) → edit/translate → .md
  → health-tracker → source-recorder → source-profiler
  → render-engine → .html + .pdf → deliver
```

Single cron job (`Publish`, daily 7:30 CST) triggers the full pipeline end-to-end. See `skills/stratum/SKILL.md` for all step definitions.

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

## Modules (20 skills)

| Module | Role | Layer |
|:---|:---|:---|
| `stratum` | Orchestration framework v4.0 | Content |
| `stratum-storage` | Channel: editorial rules, queries, domain data | Content |
| `locale-router` | BCP 47 expansion, engine↔locale matching | Content |
| `source-manager` | URL preflight + auto-healing | Content |
| `verify-engine` | Date / magnitude / fiscal-year checks | Content |
| `article-normalizer` | Raw results → ArticleRecord JSONL | Content |
| `story-cluster-engine` | Articles → same-day StoryClusters | Content |
| `coverage-monitor` | Post-clustering diversity gap detection + followup queries | Content |
| `event-thread-engine` | Cross-day thread tracking + lifecycle | Content |
| `source-graph-engine` | Entity/term/channel graph evolution | Content |
| `health-tracker` | Source hit rate stats | Content |
| `render-engine` | MD → HTML → PDF | Content |
| `value-chain-monitor` | Multi-layer value chain directed exploration + dynamic evolution (v2.0) | Source |
| `trial-source-manager` | Trial pool queue management + 5-dim evaluation + promote feedback (v2.2) | Source |
| `source-recorder` | Read content → write source-records.jsonl | Source |
| `source-profiler` | Aggregate SourceRecords → SourceProfile | Source |
| `weekly-briefing` | 7-day thread change analysis | Multi-scale |
| `monthly-briefing` | TrendTheme synthesis | Multi-scale |
| `quarterly-review` | Thesis evaluation + judgment calibration | Multi-scale |
| `yearly-review` | Annual narrative + structural change | Multi-scale |

*Note: `stratum-deployment` is a deployment reference document, not a pipeline module. 20 pipeline skills total.*

## Usage

### Manual trigger

```bash
cd ~/ProjectSpace/Stratum
make daily        # run full daily pipeline
make weekly       # weekly brief
make monthly      # monthly brief
make quarterly    # quarterly review
make yearly       # yearly review
make test         # run all tests (156/156)
make test-cov     # coverage report
```

### Cron Schedule

| Time | Job | Deliver |
|:---|:---|:---|
| Daily 7:30 CST | Publish | WeChat PDF |
| Sunday 9:00 CST | Stratum - Value Chain | WeChat |
| Sunday 8:00 | Stratum - Weekly | WeChat |
| 1st of month 8:00 | Stratum - Monthly | WeChat |
| 1st of quarter 8:00 | Stratum - Quarterly | WeChat |
| Jan 2 8:00 | Stratum - Yearly | WeChat |
| Thu 23:50 | Storage Weekly Report | WeChat |

The `Publish` job runs the full daily pipeline (Steps 0-10) in a single cron execution — collection, editing, rendering, and delivery. No separate Collect/Render crons.

## Output

All paths resolve from `config.yaml` `output_dir` (default: `~/WorkSpace/Stratum`):

```
${OUTPUT_DIR}/{channel}/
├── {channel}-{date}.md
├── {channel}-{date}.pdf
├── {channel}-{date}.html
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

## Languages

4 source languages expand to 5 locales: `zh` → `zh-CN` + `zh-TW`, plus `en`, `ja`, `ko`. Add a language in one config line. Add queries in one domain.yaml section.

## Documentation

- `docs/multi-scale-intelligence-architecture.md` — content architecture
- `docs/source-intelligence-architecture.md` — source intelligence architecture
- `skills/stratum/SKILL.md` — full pipeline step definitions
- `CONTRIBUTING.md` — contribution guide

## License

MIT — see [LICENSE](LICENSE).
