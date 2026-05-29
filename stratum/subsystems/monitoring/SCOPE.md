# monitoring — 健康监控

## Purpose
管道的"体检系统"。持续追踪信源命中率、dry streak（干旱期）、覆盖盲区，生成可操作的告警。

## Boundaries

### ✅ 做什么
- 每日信源命中率统计（source-daily.ndjson）
- Dry streak 检测（某信源连续 N 天无收录）
- 覆盖缺口检测（某领域/实体长期无覆盖）
- Top contributor 排名

### ❌ 不做什么
- **不管理信源** — 信源生命周期归 source-management
- **不执行信源发现** — 归 source-intelligence
- **不做事件追踪** — 归 story-tracking

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| Article 收录记录 | pipeline + source-management | JSONL |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| Source Daily | {health-data}/{domain}/source-daily.ndjson | NDJSON |
| Source Stats | {health-data}/{domain}/source-stats.json | JSON |
| Discovery Report | {health-data}/{domain}/discovery-report.ndjson | NDJSON |

## Design Principles
- 纯统计层，不做决策（决策归 source-intelligence）
