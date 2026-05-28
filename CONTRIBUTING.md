# Contributing

## Adding a Channel (new industry / market)

1. Create `skills/stratum-{channel}/` directory with:
   - `SKILL.md` — editorial rules, output format, channel metadata (no queries!)
   - `data/domain.yaml` — companies, terms, seed_queries, gap_searches, channels, **value_chain**
   - `references/editorial-standards.md` — market-specific editorial rules
2. Run `./install.sh --dev`
3. Test: ask Hermes "Run the daily briefing for {channel}"

### Value Chain Configuration

Each channel defines its industry-specific value chain in `data/domain.yaml → value_chain`. The 11-layer model from storage is a template:

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
- `criticality` determines: auto-archive behavior (critical=never), demotion policy, alert priority.
- `value-chain-monitor` (v2.0) manages source discovery and dynamic evolution across layers.
- Promoted sources feed back into `runtime-config.json` (not domain.yaml — domain is the baseline).

Example `data/domain.yaml`:
```yaml
domain:
  id: semicon-fr
  title: Semi-conducteurs
  emoji: 🇫🇷

companies:
  - id: stm
    type: COMPANY
    aliases: {en: "STMicroelectronics", fr: "STMicroelectronics"}

seed_queries:
  fr:
    - "STMicroelectronics dernière actualité"
    - "Soitec semi-conducteur"
  en:
    - "European semiconductor news"
```

**Queries and data live in `data/domain.yaml`, not in SKILL.md.** SKILL.md only contains editorial rules and output format.

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

# Add seed_queries.{locale} to domain.yaml
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

Modules are channel-agnostic and language-agnostic. All domain logic lives in channel `data/domain.yaml`.

## Pull Requests

1. New channels: `skills/stratum-{channel}/` directory with `SKILL.md` + `data/domain.yaml`
2. New engines: update `config.example.yaml` engine block
3. Bug fixes: patch the relevant module
4. Run `./install.sh --dev` and test before submitting

## Style

- Framework code: English
- Channel descriptions: English
- Channel queries in domain.yaml: native language of the market
- Commit messages: English, conventional commits (`feat:`, `fix:`, `docs:`)
- `config.yaml` is `.gitignore`'d — only `config.example.yaml` is committed
