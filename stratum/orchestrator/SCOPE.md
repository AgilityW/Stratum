# orchestrator - pipeline 编排层

## Purpose

`stratum/orchestrator` 是 Stratum 的日频运行入口。它负责把配置、领域、stage 脚本、collector、SQLite story-tracking 串成一次完整 pipeline run。

当前唯一代码入口是 `pipeline.py`。

## Boundaries

### 做什么

- 解析运行参数：domain、date、output-dir、raw-input、from-stage、skip-agent。
- 解析 `config.yaml` 中的 `output_dir`、`reports_dir`、`db_dir`。
- 将解析后的 `db_dir` 写入 `STRATUM_DB_DIR`，确保 DB helper 与本次
  pipeline 使用同一个 SQLite 根目录。
- 调用 8 个 stage：search、enrich、verify、normalize、cluster、edit、validate、render。
- 在 search 之前调用 `stratum.collectors.collect()`，用 RSS/URL/browser 结果
  seed `raw.json`，再让 Search 只补充未覆盖的部分。
- 在 normalize 前消费上一轮 `thread_keywords.json`。
- 在 edit 前从 SQLite 生成 `story_context.json`。
- 生成 story context 时把 `domain.yaml` 的 `companies[].id` 传给
  Story Tracking 作为 coverage entity universe，使冷启动/未覆盖实体也能
  出现在 coverage gaps 中。
- 在 pipeline 末尾把结构化事件、实体统计、快照写入 SQLite。
- 在成功写入结构化事件后从 SQLite 导出 `thread_keywords.json`，供下一轮
  normalize 使用。

### 不做什么

- 不承载 stage 内部算法。每个 stage 仍由自己的 CLI 脚本负责。
- 不直接调用搜索 API。Search stage 委托 `stratum.subsystems.search`。
- 不直接调用 collector strategy。Collector dispatch 由 `stratum.collectors` 负责。
- 不包含领域知识。领域数据只能来自 `domains/{id}/`。
- 不把 SQLite 数据模型复制成文件层 JSONL 逻辑。

## Data Flow

```text
config.yaml + domains/{id}/
        |
        v
collectors -> raw.json
        |
        v
search supplement -> raw.json
        |
        v
enrich -> verify -> normalize -> cluster
        |
        v
story_context.json -> edit -> briefing.md
        |
        v
validate -> render -> briefing.html/pdf
        |
        v
SQLite ingest
        |
        +--> export thread_keywords.json from SQLite for next run
```

## Runtime Outputs

| Output | Path |
|:---|:---|
| stage data | `{reports_dir}/{domain}/data/{date}/` |
| raw search/collector pool | `raw.json` |
| search query stats sidecar | `raw.stats.json` |
| collector health sidecar | `collector_stats.json` |
| verified articles | `verified.jsonl` |
| verification stats sidecar | `verified.stats.json` |
| normalized articles | `articles.jsonl` |
| clusters | `clusters.json` |
| briefing | `briefing.md`, `briefing.html`, `briefing.pdf` |
| edit context | `story_context.json` |
| run manifest | `run_manifest.json` |
| feedback keywords | `{reports_dir}/{domain}/data/story-tracking/thread_keywords.json` |
| source health records | `{health_data_dir}/{domain}/source-daily.ndjson` |
| SQLite DB | `{db_dir}/{domain}/{domain}.db` |

`raw.json` is the only raw dataset for a domain/date run. Sidecars such as
`raw.stats.json` and `collector_stats.json` record diagnostics, not alternate
raw copies.

After Search completes, the orchestrator ingests `raw.stats.json` into the
SQLite `queries` table so query hit counters and `last_run` stay current.
When a domain DB exists, the orchestrator still passes
`domains/{id}/queries.yaml` into Search as the baseline fallback. The Search
stage decides whether to use active DB queries or fall back to YAML, preventing
an empty DB from suppressing the run's query set.
Collector health records preserve source status in tags and metadata. Status
`unsupported` is written as `scanned: false` because it represents missing
runtime capability or unsupported configuration, not an upstream source scan.

## Failure Policy

- Core deterministic stages fail hard through `run_stage()`.
- Edit failure is reported but validate/render may continue if a prior `briefing.md` exists.
- Collector, story context generation, thread keyword export, and DB ingest are best-effort helpers. They log warnings and do not block the main pipeline.
- `run_manifest.json` records stage-level `success`, `skipped`, `provided`,
  `empty`, `failed`, and `failed_nonblocking` statuses. On hard stage failure,
  the manifest is written before the process exits.
- DB ingest is gated by fresh artifact surfaces: event/thread ingestion runs
  only when Edit may have produced new `event-threads.json`, while entity
  counts and snapshots run only when Normalize produced fresh `articles.jsonl`.
  Validate/render-only resumes record DB ingest as skipped.
- `thread_keywords.json` is exported only after successful event DB ingest. This
  keeps the next run's normalize feedback file aligned with newly persisted
  events instead of the previous SQLite state.
- `thread_keywords.json` is aggregated by `thread_id`. Multiple events in the
  same continuing story contribute a single keyword profile, preventing
  Normalize from treating one thread as several competing candidates.

## Resume Policy

`--from-stage` starts execution at the named stage and skips earlier stages:

- `--from-stage enrich` expects an existing `raw.json`.
- `--from-stage verify` expects an existing `enriched.json`.
- `--from-stage normalize` expects an existing `verified.jsonl`.
- `--from-stage cluster` expects an existing `articles.jsonl`.
- `--from-stage edit` expects existing `articles.jsonl` and `clusters.json`.
- `--from-stage validate` expects existing `briefing.md` and `articles.jsonl`.
- `--from-stage render` expects existing `briefing.md`.

Search-side collectors only run when Search runs, so resume runs do not mutate
an existing `raw.json`.

Resume stage names are validated against the canonical pipeline order. Unknown
stage names fail loudly instead of defaulting to a full run, so typoed internal
calls or future entrypoints cannot silently mutate earlier artifacts.

DB ingest follows the same resume contract: `--from-stage validate` and
`--from-stage render` do not re-ingest prior articles/events, preventing
re-validation or re-rendering from changing SQLite counters.

After fresh event DB ingest, the orchestrator also turns event-thread watch
targets into active SQLite Search queries. Explicit `watch_signals` are used
when present; otherwise the event-thread engine falls back to the thread's
canonical question or title. The orchestrator expands `config.yaml
source_languages` through `locales`, then writes one thread-bound
`verification` query per watch target and locale with `dimension =
thread_watch`. The next Search run can therefore follow emerging, active, and
cooling stories through the normal DB-backed query path even when Agent output
omits optional watch signals.

## Dependencies

- `stratum/stages/*/*.py`
- `stratum/collectors`
- `stratum/subsystems/search`
- `stratum/subsystems/story-tracking/briefing_context.py`
- `stratum/db`
- `domains/{id}/domain.yaml`
- `domains/{id}/queries.yaml`
- `domains/{id}/templates/daily.html`

Edit prompts are loaded from `stratum/stages/edit/prompts/manifest.yaml` and
its fragments. Domain prompt files under `domains/{id}/prompts/` are reserved
assets for future override support; the current pipeline does not read them.
