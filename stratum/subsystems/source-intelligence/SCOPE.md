# source-intelligence — 信源自进化编排

## Purpose
信源系统的"大脑"。编排 7 步闭环，让信源池自动发现、评估、引入或淘汰。

对信源说："证明你值得被收录，否则降级。"

## Boundaries

### ✅ 做什么
- 7 步进化闭环编排：Record → Profile → Discover → Trial → Evaluate → Health → Coverage
- 加速信号评估（cited_by_trusted, fills_coverage_gap 等）
- 多样性评分、基线对比、置信度校准

### ❌ 不做什么
- **不做单步实现** — 每步的具体逻辑在对应 subsystem（source-management, monitoring 等）
- **不直接操作存储** — 存储通过各 subsystem 的接口

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| SourceRecords | source-management | JSONL |
| SourceProfiles | source-management | JSON |
| Health Stats | monitoring | NDJSON |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| 编排结果 | 内存中（纯编排层）| Python dict |

## Design Principles

### 铁律
1. **编排层不持有状态** — 所有状态在 subsystem 中
2. **每步可独立运行** — 7 步都可以单独调用和测试

## Dependencies

### 依赖
- source-management, source-graph, monitoring

### 被依赖
- 无直接下游（编排层是终端消费者）
