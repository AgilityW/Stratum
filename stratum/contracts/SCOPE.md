# contracts - 共享数据契约

## Purpose

`stratum/contracts` 放跨模块共享的数据模型和 JSON Schema。它的职责是让 stage、subsystem、测试对同一批结构有共同名字和字段预期。

## Current Contents

| File | Role |
|:---|:---|
| `raw_search_result.json` | Search and collector raw discovery result contract |
| `raw_search_stats.json` | Search execution stats and diagnostics sidecar contract |
| `collector_stats.json` | Collector sidecar and source-health handoff contract |
| `verified_article.json` | Verify stage output contract |
| `article_record.json` | Normalize stage article contract, including lineage fields used by downstream stages |
| `story_cluster.json` | Cluster stage output contract |
| `event_thread.py` | cross-temporal event-thread dataclasses and scale helpers |
| `__init__.py` | re-export for `event_thread.py` |

## Boundaries

### 做什么

- 定义可被多个模块共享的数据形状。
- 提供轻量 helper，例如 scale order 查询。
- 为 pytest schema/integrity tests 提供稳定文件位置。
- 记录跨 stage 需要保留的来源线索，例如 `engine`、`source_type_hint`、`canonical_url`、`date_source`。

### 不做什么

- 不包含领域知识。
- 不访问网络、DB 或文件系统运行时数据。
- 不实现 pipeline stage 算法。

## Import Rule

Python dataclass 契约优先通过顶层导入：

```python
from stratum.contracts import CrossTemporalState, BriefingRef
```

JSON Schema 由测试和 stage 通过路径读取。

## Discovery Contract Notes

`raw_search_result.json` 同时覆盖 Search API 结果和 collectors sidecar 结果。`engine` 是自由字符串，因为实际来源可能是 `bocha`、`tavily`，也可能是 `rss:<source>`、`direct_fetch:<source>` 等采集策略 ID。

`raw_search_stats.json` 覆盖 `raw.stats.json`，也就是 Search 的执行与质量诊断
sidecar。它要求 `queries` 保留每个 `QueryStats` 的 `query_id`、engine、
status、result count、locale/intent/dimension、latency/error 和可选
`include_domains`；`diagnostics` 覆盖 locale/source-type/dimension 产出、
source-type floor gaps、domain-filter coverage、top source domains 和低产出
queries。这个契约保护 DB query-stat ingest、Search recall debug 和后续
coverage 调优不被字段漂移破坏。

`collector_stats.json` 覆盖 collector source-level health sidecar。它是
Collectors 与 Monitoring 之间的共享契约，包含每个 source 的 access、status、
hits、duration、dated count 和可选 error。未知采集方式使用
`access: unknown` 与 `status: unsupported`，错误文本保留原始配置值。

`date_source` 表示日期从哪里来，当前允许 `search_api`、`web_extract`、`snippet_regex`、`url_path`、`freshness_window`、`none`。Verify 和 Normalize 应保留这个字段。
`date_confidence` 是 Verify 对该 lineage 的质量解释：`search_api`、`web_extract`、`url_path` 为 high，`freshness_window` 为 medium，`snippet_regex` 为 low，`none` 为 none。低置信但仍通过默认策略的记录会带 `quality_flags`，让下游能审计弱日期证据。

`canonical_url` 是跨 Search、Collectors、Verify、Normalize 的稳定文章身份键。原始 `url` 应保留用于溯源和打开页面，但去重、ArticleRecord `id`、`content_hash` 应优先使用 canonical URL。

ArticleRecord `source_locale` uses the same BCP47-style boundary as Search
query locales: language tags plus optional script/region subtags such as `en`,
`en-US`, `zh-CN`, `zh-cn`, or `zh-Hans-CN`.

`query_dimension` 是 Search 配置传入 Normalize 的意图标签，例如 `baseline`、`verification`、`supply_chain`。它必须随 ArticleRecord 保留，方便后续分析哪些新闻来自基线搜索、验证搜索或专项维度。

`story_cluster.json` 以 `article_ids` 作为主 join key，同时允许 `source_domains` 和 `canonical_urls` 作为审计字段。它们不替代 `articles.jsonl`，只用于快速检查来源混合、重复 URL 和聚类解释性。
StoryCluster id follows `sc-{domain_id}-{seq:04d}`. The `domain_id` part is
the domain directory id, so the schema allows lowercase letters, digits,
underscores, and hyphens.

## Pending Consolidation

`stratum/subsystems/story-tracking/story_contracts.py` 目前仍是 story-tracking 的本地契约。以后如果多个 subsystem 同时依赖 EventRecord/CausalEdge/Judgment，再迁入 `stratum/contracts`。
