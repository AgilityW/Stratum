# domains/storage — Storage 领域配置

## Purpose
存储产业的领域知识配置。包括公司/技术词表、搜索查询、提示词模板、简报模板、价值链探测模型。

这是 Stratum 框架的**第一个领域实例**。所有领域特定知识集中在此目录，框架代码零硬编码。

## Boundaries

### ✅ 包含
- domain.yaml — 公司/技术/信源 seed + 种子查询 + 价值链 11 层模型
- taxonomy.yaml — 受控词表（topics × 19, entities × 16）
- queries.yaml — 多语言搜索查询模板
- prompts/daily.md — Agent Edit 阶段的日频简报 prompt
- templates/daily.html — 简报 HTML 渲染模板
- weekly.yaml — 周报配置

### ❌ 不包含
- **任何可执行代码** — 纯配置，由 stratum/ 框架读取
- **运行时数据** — 运行时产出在 {workspace}/storage/

## Data Contracts

### 配置文件格式
| 文件 | 格式 | 读取者 |
|:---|:---|:---|
| domain.yaml | YAML | pipeline.py, stages, value-chain |
| taxonomy.yaml | YAML | story-tracking/taxonomy.py |
| queries.yaml | YAML | agent_interface.py |
| prompts/*.md | Markdown | Agent (LLM) |
| templates/*.html | HTML/Jinja2 | stages/render |

## Design Principles

### 铁律
1. **框架不包含领域知识** — stratum/ 下无公司名、技术名、领域术语
2. **新领域 = 复制此目录** — 创建 domains/robot/ 不改框架一行代码

## Dependencies

### 被依赖
- stratum/ 框架所有模块
