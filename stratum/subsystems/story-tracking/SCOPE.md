# story-tracking — 事件库 + 因果图 + 判断日志 + 关键词反馈

## Purpose
Stratum 的结构化事件智能层。在 Agent 产出的非结构化事件流之上，建立**可查询、可追溯、可验证**的立体追踪系统。

核心能力：Topic × Entity × Time × Scale 四维查询、因果链追溯、判断验证闭环、**活跃事件关键词反向注入 normalize**。

## Boundaries

### ✅ 做什么
- EventStore — 事件全生命周期管理（创建、更新、标签、跨尺度登记）
- Query Engine — 多标签交集 + 时间 + 尺度过滤查询
- Timeline — 跨时间尺度（daily→weekly→monthly→quarterly→yearly）追溯和 rollup
- CausalGraph — 事件间有向因果边（添加、上下游遍历、环检测）
- JudgmentLog — 判断记录、六态验证、准确率统计、到期提醒
- Gate — Agent 生成物的入库验证门
- BriefingContext — 为下次简报生成推送上下文
- Taxonomy — 领域受控词表加载与标签归一化
- Repository — 存储抽象层（当前 JSONL，未来可换 SQLite）
- **Keyword Export** — 导出活跃事件的关键词集合，供 normalize stage 做文章标签匹配 (v5.1 新增)

### ❌ 不做什么
- **不生产事件** — 事件内容由 edit.py（pipeline Edit 阶段）产出，story-tracking 只做管理
- **不调用 LLM** — 所有函数是确定性的纯计算，不访问网络
- **不管理信源** — 信源的生命周期归 source-management/source-intelligence
- **不生成简报** — 简报归 pipeline + edit.py + render stage
- **不包含领域知识** — 领域配置在 domains/{id}/taxonomy.yaml 和 domain.yaml

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| Agent EventThread | pipeline Agent Edit 产出 | JSON (event-threads.json) |
| 领域词表 | domains/{id}/taxonomy.yaml | YAML |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| EventRecord | {output_dir}/{domain}/data/story-tracking/events.jsonl | JSONL |
| CausalEdge | {output_dir}/{domain}/data/story-tracking/causal.jsonl | JSONL |
| Judgment | {output_dir}/{domain}/data/story-tracking/judgments.jsonl | JSONL |
| 元数据 | {output_dir}/{domain}/data/story-tracking/state.json | JSON |
| BriefingContext | {output_dir}/{domain}/data/{date}/story_context.json | JSON |
| **thread_keywords.json** | {output_dir}/{domain}/data/story-tracking/thread_keywords.json | JSON |

### thread_keywords.json (v5.1 新增)
```json
{
  "generated_at": "2026-05-29",
  "domain": "storage",
  "threads": [
    {
      "thread_id": "et-2026-001",
      "title": "CXMT科创板IPO与中国DRAM崛起",
      "keywords": ["CXMT", "长鑫", "长鑫科技", "科创板", "IPO", "295亿", "DRAM"],
      "entities": ["CXMT", "工商银行AIC", "华胥基金"],
      "priority": 1,
      "status": "active"
    }
  ]
}
```
由 orchestrator 在 pipeline 的 Stage 5→6 之间调用导出函数生成。被 normalize stage 消费，用于文章 tags 匹配。

### 内部数据模型
- `story_contracts.py` — 所有 dataclass 定义
- `ScalRef` 反序列化后可能是 dict 或对象 — 使用 `_ref_scale()` helper 统一兼容

## Design Principles

### 铁律
1. **纯函数** — 所有模块函数不访问网络、不调 LLM、无副作用（除 Repository 写入）
2. **Repository 模式** — 业务逻辑只依赖 ABC 接口，不直接读写文件路径
3. **Gate 在前** — Agent 产出必须经 gate 验证才能入库
4. **标签归一化** — 所有 topic/entity tag 经 taxonomy 归一化后再存储
5. **ScaleRef 兼容** — 代码必须同时处理 dict 和 object 两种形态（JSONL 反序列化的产物）
6. **闭环反馈** — 活跃事件的关键词向下游 normalize 阶段注入，形成 term→cluster→story 闭环

### 惯例
- ID 格式：`event-{domain}-{seq:04d}`, `causal-{domain}-{seq:04d}`, `judgment-{domain}-{seq:04d}`
- 日期统一 ISO 8601 字符串
- 查询大小写不敏感
- 判断 verdict 六态：pending / correct / incorrect / partial / deferred / unverifiable

## Dependencies

### 依赖
- 无外部服务依赖
- `domains/{id}/taxonomy.yaml` — 标签词表（运行时加载）
- Agent 产出 `event-threads.json` — 通过 `story_bridge.py` 桥接

### 被依赖
- `orchestrator/pipeline.py` — 调用 BriefingContext 生成 + Story Bridge 入库 + keyword 导出
- `orchestrator/story_bridge.py` — 桥接 Agent 输出到 EventStore
- `stages/normalize.py` — 消费 thread_keywords.json 做标签匹配 (v5.1 新增)

## Evolution Notes

### v5.1 (2026-05-29)
- 新增 keyword export 功能，将活跃事件关键词注入 normalize → cluster 链路
- 闭环：Story Bridge (产出) → normalize (消费) → cluster (锚定) → edit (上下文) → Story Bridge (更新)

### 已知局限
- JSONL 反序列化后嵌套对象（ScaleRef）变成 dict — 当前用 helper 兼容
- Tag 抽取基于关键词匹配 — 当文本中提及实体但非主题时会有噪声
- 因果图无持久化索引 — 当前全量扫描，事件量过万时需要索引
