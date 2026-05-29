# event-thread — 跨日事件线程（Agent 驱动）

## Purpose
日频管线的 Agent Edit 阶段产出的事件线程层。Agent 从每日 articles + clusters 中识别跨日延续的事件，生成 EventThread（标题、状态、时间线、观察信号）。

与 story-tracking 的关系：event-thread 是**内容生产层**，story-tracking 是**数据管理层**。Agent 产出 EventThread → story_bridge 转换 → EventStore 入库。

## Boundaries

### ✅ 做什么
- EventThread 数据模型（id, title, timeline, status, watch_signals 等）
- 生命周期状态机（emerging → active → cooling → resolved → archived）
- Jaccard 确定性匹配（cluster ↔ thread 实体重叠度）
- Watch query 生成（从活跃线程提取搜索信号）
- 跨时间尺度链路（daily→weekly→...追溯，见 cross_temporal.py）

### ❌ 不做什么
- **不管理持久化查询** — 查询能力在 story-tracking/query.py
- **不做因果推理** — 因果图在 story-tracking/causal_graph.py
- **不验证判断** — 判断日志在 story-tracking/judgment_log.py
- **不归一化标签** — 标签词表在 story-tracking/taxonomy.py

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| 新 clusters | pipeline Stage 5 产出 | clusters.json |
| 已有 threads | {workspace}/{domain}/data/event-threads/event-threads.json | JSON array |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| EventThread | {workspace}/{domain}/data/event-threads/event-threads.json | JSON array |
| CrossTemporalLink | 内存中（cross_temporal.py）| Python dict |

## Design Principles

### 铁律
1. **Agent 是内容作者** — 线程的主体内容（title, assessment, questions）由 LLM 生成
2. **确定性 fallback** — Jaccard 匹配用于不需要 LLM 的场景（如事件量少时的日间匹配）
3. **ID 不与 story-tracking 共享** — EventThread 的 `et-{year}-{seq}` 和 EventRecord 的 `event-{domain}-{seq}` 是独立命名空间

## Dependencies

### 依赖
- pipeline Stage 5 (Cluster) 产出
- Hermes Agent (LLM)

### 被依赖
- pipeline Stage 6 (Edit) — Agent 读 clusters 产出 EventThread
- story_bridge.py — 转换 EventThread → EventRecord

## Evolution Notes

### 已知局限
- 两个 contracts.py 命名冲突 — event-thread/contracts.py 与 story-tracking/story_contracts.py 同名，pytest 统一收集时会冲突
- 跨时间尺度链路（cross_temporal.py）功能与 story-tracking/timeline.py 部分重叠，待收敛
