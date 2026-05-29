# orchestrator — 管线编排 + Agent 契约 + 桥接层

## Purpose
Stratum 的中央调度器。串联 8 个 pipeline stage，定义 Agent 与确定性代码的边界，桥接 Agent 产出到故事追踪系统。

## Boundaries

### ✅ 做什么
- pipeline.py — 8 阶段日频简报管线编排（search → enrich → verify → normalize → cluster → edit → validate → render）
- agent_interface.py — Agent Search/Edit 阶段的输入输出数据契约
- story_bridge.py — Agent EventThread → EventRecord 转换 + Gate 验证 + EventStore 入库
- BriefingContext 注入 — Stage 5→6 之间生成 story_context.json 供 Agent 读取
- Story Bridge 写入 — Stage 8 之后将 Agent 产出的事件线程写入 story-tracking

### ❌ 不做什么
- **不执行确定性计算** — enrich/verify/normalize/cluster/validate/render 由各 stage 独立脚本完成
- **不调用 LLM** — Agent 阶段只打印指令并退出，LLM 由外部 Hermes skills 驱动
- **不管理存储** — 存储归各 subsystem 的 Repository
- **不定义业务规则** — Gate 和 tag 归一化归 story-tracking

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| domain.yaml | domains/{id}/domain.yaml | YAML |
| queries.yaml | domains/{id}/queries.yaml | YAML |
| raw.json | Agent Search 产出 | JSON |
| event-threads.json | Agent Edit 产出（可选）| JSON |

### 输出
| 数据 | 路径 | 格式 |
|:---|:---|:---|
| story_context.json | {workspace}/{domain}/data/{date}/story_context.json | JSON |
| EventRecords | {workspace}/{domain}/data/story-tracking/events.jsonl | JSONL |

### 中间产物（pipeline 内部）
- enriched.json → verified.jsonl → articles.jsonl → clusters.json → briefing.md → HTML/PDF

## Design Principles

### 铁律
1. **Agent 是外部进程** — pipeline.py 不做 LLM 调用，只打印指令然后 exit
2. **stage 脚本独立可运行** — 每个 stage 可以单独调用和测试
3. **桥接层零侵入** — Story Bridge 用 try/except 包裹，story-tracking 未初始化时静默跳过
4. **Domain-agnostic** — orchestrator 不包含任何领域特定逻辑

## Dependencies

### 依赖
- `stratum/stages/` — 6 个确定性 stage 脚本
- `stratum/subsystems/story-tracking/` — EventStore, BriefingContext, Gate, Taxonomy
- `domains/{id}/` — domain.yaml, queries.yaml, taxonomy.yaml, prompts/, templates/

### 被依赖
- Hermes skills — 调用 pipeline.py 执行管线
- Cron — 定时触发

## Evolution Notes

### 已知局限
- 只支持 daily scale，weekly/monthly 管线的 orchestration 尚未实现
- Agent Edit placeholder 不校验 briefing 质量——validate stage 只做形式检查
- 多域并行运行无内置支持
