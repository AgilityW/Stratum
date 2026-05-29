# source-graph — 信源关系图

## Purpose
构建和维护信源之间的语义关系图。通过实体/术语共现提取信源间的关联，支持信源发现和覆盖分析。

## Boundaries

### ✅ 做什么
- 信源节点与边的图结构
- 实体/术语从 article 内容中提取（extractor）
- 信源关系演化追踪（evolution）
- 图状态持久化

### ❌ 不做什么
- **不管理信源生命周期** — 归 source-management
- **不做信源发现编排** — 归 source-intelligence
- **不追踪信源健康** — 归 monitoring

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| Articles | pipeline 产出 | JSONL |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| Graph State | {health-data}/{domain}/graph-state.json | JSON |

## Design Principles
- 图是信源关系的"语义地图"，不是信源的"管理后台"

## Dependencies

### 依赖
- pipeline 产出
- domain.yaml（seed entities/terms）

### 被依赖
- source-intelligence（信源发现时查询图关系）
- monitoring（覆盖分析时参考图结构）
