# Contributing

## Adding a Domain (new industry / market)

1. Create `domains/{channel}/` directory with:
   - `domain.yaml` — domain metadata, companies, terms, source registry, validation rules, editorial policy, and optional value-chain taxonomy
   - `queries.yaml` — structured Search query templates by intent, dimension, and locale
   - `templates/daily.html` — domain render template
   - `prompts/daily.md` — reserved future domain prompt override asset
2. Run `./install.sh --dev`
3. Test with the pipeline:
   `python3 stratum/orchestrator/pipeline.py --domain {channel} --date YYYY-MM-DD`

### Value-Chain Taxonomy

Domains may define an industry-specific `value_chain` section in `domains/{channel}/domain.yaml`. Treat it as domain taxonomy and coverage metadata for queries, editorial policy, and future monitoring surfaces. The storage model is an example to adapt, not a framework-level runtime module:

```yaml
value_chain:
  layers:
    - id: upstream_equipment
      label: 上游设备/材料
      question: 能不能造？
      criticality: critical          # critical | high | medium
      frequency: weekly               # daily | weekly | biweekly | monthly
      coverage_alert_weeks: 2         # 连续N周无覆盖 → 告警
      seed_sources: [...]             # 该层已知信源
      watch_patterns: [...]           # 该层关心的信号类型
      probe_templates: [...]          # 主动探测查询模板 {company} {year} {quarter}
      gap_indicators: [...]           # 覆盖缺失判定规则
```

**Rules:**
- Adapt the layers to YOUR industry — storage's 11 layers won't fit a different sector.
- Define `probe_templates` with `{company}`, `{year}`, `{quarter}`, `{month}`, `{date}` placeholders.
- `criticality` is descriptive today; use it to guide query/editorial coverage and future alert priority.
- Promoted sources should become explicit `source_registry.sources` entries once trusted; `domain.yaml` is the baseline configuration.

Example `domains/{channel}/domain.yaml`:
```yaml
domain:
  id: semicon-fr
  title: Semi-conducteurs
  emoji: 🇫🇷

companies:
  - id: stm
    type: COMPANY
    aliases: {en: "STMicroelectronics", fr: "STMicroelectronics"}
```

Example `domains/{channel}/queries.yaml`:
```yaml
queries:
  detection:
    supply_chain:
      fr:
        - "STMicroelectronics dernière actualité"
        - "Soitec semi-conducteur"
      en:
        - "European semiconductor supply chain news"
```

Domain assets live under `domains/{channel}/`. Keep Search templates in `queries.yaml` so reviewers and runtime code edit the same source of truth.

## Adding a Search Engine

Add a block to `config.yaml → engines`:

```yaml
engines:
  myengine:
    label: "My Engine"
    languages: [fr, de]
    endpoint: "https://api.example.com/search"
    auth: "apikey ${MYENGINE_API_KEY}"
    freshness: {param: "freshness", day: "d"}
    response_path: "data.items"
    has_date: true
```

| Field | Required | Description |
|:---|:---|:---|
| `label` | ✅ | Human-readable name |
| `languages` | ✅ | BCP 47 locale tags this engine covers |
| `endpoint` | ✅ | POST endpoint URL |
| `auth` | ✅ | Auth header format. Use `${ENV_VAR}` for credentials |
| `freshness.param` | ✅ | Query parameter name for time filtering |
| `freshness.day` | ✅ | Parameter value for "last 24 hours" |
| `response_path` | ✅ | JSON path to results array (dot-separated) |
| `has_date` | ✅ | Does the engine return `datePublished`? |
| `extra` | No | Additional JSON fields sent with every request |

## Adding a Language

```yaml
# config.example.yaml
source_languages: [zh, en, ja, ko, fr]  # add your language

# Add queries.{intent}.{dimension}.{locale} to domains/{channel}/queries.yaml
# Add locale expansion rule if umbrella→subtags (e.g., zh→zh-CN+zh-TW)
```

Make sure at least one engine covers your language. If not, add an engine first.

## Adding a Module

Create `skills/{module-name}/SKILL.md` with a `contract` frontmatter:
```yaml
contract:
  input: "what it reads"
  output: "what it produces"
  role: "pure function description"
```

Modules are domain-agnostic and language-agnostic. Domain configuration lives in `domains/{channel}/`.

## Pull Requests

1. New domains: `domains/{channel}/` directory with `domain.yaml`, `queries.yaml`, template assets, and tests
2. New engines: update `config.example.yaml` engine block
3. Bug fixes: patch the relevant module
4. Run `./install.sh --dev` and test before submitting

## Style

- Framework code: English
- Domain descriptions: English
- Domain queries in `queries.yaml`: native language of the market
- Commit messages: English, conventional commits (`feat:`, `fix:`, `docs:`)
- `config.yaml` is `.gitignore`'d — only `config.example.yaml` is committed
