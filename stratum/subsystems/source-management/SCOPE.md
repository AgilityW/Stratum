# source-management — 信源记录 / 画像 / 试用管理

## Purpose
信源的全生命周期管理。追踪每个信息来源的产出频率、收录率、领域覆盖，管理试用池中新信源的引入和评估。

## Boundaries

### ✅ 做什么
- SourceRecord — 记录每次信源产出的 article 是否被收录
- SourceProfile — 基于 EMA（指数移动平均）的信源健康画像
- Trial Pool — 试用信源队列管理，5 维评估（频率、收录率、独特性、时效性、相关性）
- Recorder → Profiler → Trial 三层流水线

### ❌ 不做什么
- **不执行搜索** — 搜索由 pipeline Agent Search 阶段完成
- **不做信源发现** — 新信源发现归 source-intelligence
- **不跟踪事件** — 事件归 story-tracking

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| Article 收录记录 | pipeline 各阶段 | JSONL |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| SourceRecords | {workspace}/{domain}/data/sources/source-records-*.jsonl | JSONL |
| SourceProfiles | {workspace}/{domain}/data/sources/profiles/ | JSON |
| Trial Pool | {workspace}/{domain}/data/sources/trial-pool.json | JSON |

## Design Principles

### 铁律
1. **EMA 画像** — SourceProfile 使用指数移动平均，近期行为权重更高
2. **试用池有界** — Trial pool 有最大容量，满时淘汰最低分信源

## Dependencies

### 依赖
- pipeline 产出（article 收录/拒收记录）
- domain.yaml（seed channels）

### 被依赖
- source-intelligence（信源自进化闭环）
- monitoring（健康度追踪）
