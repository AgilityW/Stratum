# contracts — 共享数据契约

## Purpose
跨子系统共享的数据模型定义。目标：消除各子系统的 contracts.py 命名冲突，统一到 `stratum/contracts/`。

## Boundaries

### ✅ 已收敛
- `event_thread.py` — CrossTemporalLink, BriefingRef, CrossTemporalState, TraceResult 等跨时间尺度链接契约
- `source_intelligence.py` — RecordInput/Output, EvalDimensions, PipelineResult 等信源自进化管线契约

### ✅ 将来收敛
- `story_contracts.py`（当前在 story-tracking/）— EventRecord, CausalEdge, Judgment, TimelineEntry, ScaleRef

### ❌ 不做什么
- **不定义业务逻辑** — 纯数据契约，无函数
- **不包含领域知识** — 领域特定类型在 domains/{id}/

## 模块清单

| 文件 | 来源 | 状态 |
|:---|:---|:---|
| `__init__.py` | 新建 | ✅ 统一导入入口 |
| `event_thread.py` | event-thread/contracts.py | ✅ 已收敛 |
| `source_intelligence.py` | source-intelligence/contracts.py | ✅ 已收敛 |
| `story.py`（待定） | story-tracking/story_contracts.py | ⬜ 待收敛 |

## Design Principles
- 模块名不加 `contracts` 后缀（`event_thread.py` 而非 `event_thread_contracts.py`），目录名为 contracts 已表明意图
- `__init__.py` 做 re-export，所有消费者统一用 `from stratum.contracts import X`

## Dependencies

### 被依赖
- event-thread/cross_temporal.py、test_cross_temporal.py
- source-intelligence/evolution_pipeline.py、test_pipeline.py
- 未来：story-tracking 全模块
