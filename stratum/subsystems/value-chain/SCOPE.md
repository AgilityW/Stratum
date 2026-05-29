# value-chain — 价值链探测

## Purpose
十一层结构化探测模型。从上游设备/材料到地缘管制，系统性地探测存储产业价值链的每一层。

回答每一层的核心问题：能不能造？拐点到了吗？谁会买？游戏规则变了吗？

## Boundaries

### ✅ 做什么
- 11 层探测模型（运行时配置化）
- 层合并/降级/覆盖告警
- 探测模板执行与结果记录
- 覆盖盲区检测

### ❌ 不做什么
- **不执行具体搜索** — 搜索由 pipeline Agent 或 source-intelligence 驱动
- **不定义探测内容** — 探测逻辑在 domain.yaml 的 value_chain section 中
- **不追踪事件** — 事件归 story-tracking

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| domain.yaml（value_chain section）| domains/{id}/domain.yaml | YAML |

### 输出
| 数据 | 存储 | 格式 |
|:---|:---|:---|
| Probe State | {workspace}/{domain}/data/value-chain/state.json | JSON |

## Design Principles
- **Domain-agnostic 框架 + domain-aware 配置** — 框架不包含任何具体行业知识

## Dependencies

### 依赖
- domain.yaml

### 被依赖
- pipeline（作为搜索查询的补充输入）
