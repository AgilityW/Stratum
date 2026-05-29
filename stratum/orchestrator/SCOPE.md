# orchestrator — 管线编排 + 闭环反馈 + 桥接层

## Purpose
Stratum 的中央调度器。串联 8 个 pipeline stage，维护 Story Bridge → normalize 的闭环反馈，桥接 Agent 产出到故事追踪系统。

## Boundaries

### ✅ 做什么
- pipeline.py — 8 阶段日频简报管线编排（search → enrich → verify → normalize → cluster → edit → validate → render）
- edit.py — Agent Edit 阶段（LLM 生成简报），由 pipeline.py 调用
- story_bridge.py — Agent EventThread → EventRecord 转换 + Gate 验证 + EventStore 入库
- BriefingContext 注入 — Stage 5→6 之间生成 story_context.json 供 edit.py 读取
- **thread_keywords 导出** — Stage 5→6 之间从 Story Bridge 导出活跃事件关键词，供 normalize 消费
- Story Bridge 写入 — Stage 8 之后将 Agent 产出的事件线程和因果判断写入 story-tracking

### ❌ 不做什么
- **不执行确定性计算** — enrich/verify/normalize/cluster/validate/render 由各 stage 独立脚本完成
- **不管理存储** — 存储归各 subsystem 的 Repository
- **不定义业务规则** — Gate 和 tag 归一化归 story-tracking
- **不手动介入** — 所有 8 个 stage 全部代码驱动，零人工步骤

## Data Contracts

### 输入
| 数据 | 来源 | 格式 |
|:---|:---|:---|
| config.yaml | project root | YAML |
| domain.yaml | domains/{id}/domain.yaml | YAML |
| queries.yaml | domains/{id}/queries.yaml | YAML |

### 输出
| 数据 | 路径 | 格式 |
|:---|:---|:---|
| briefing.md/html/pdf | {output_dir}/{domain}/data/{date}/ | MD/HTML/PDF |
| story_context.json | {output_dir}/{domain}/data/{date}/story_context.json | JSON |
| **thread_keywords.json** | {output_dir}/{domain}/data/story-tracking/thread_keywords.json | JSON |
| EventRecords | {output_dir}/{domain}/data/story-tracking/events.jsonl | JSONL |
| CausalEdges | {output_dir}/{domain}/data/story-tracking/causal.jsonl | JSONL |
| Judgments | {output_dir}/{domain}/data/story-tracking/judgments.jsonl | JSONL |

### 中间产物（pipeline 内部）
- raw.json → enriched.json → verified.jsonl → articles.jsonl → clusters.json → briefing.md → HTML/PDF

### 闭环数据流 (新增)
```
Story Bridge (events.jsonl)
        │
        ▼ export_thread_keywords()
thread_keywords.json
        │
        ▼ normalize.py --thread-keywords
articles.jsonl (带 event_thread_id)
        │
        ▼ cluster.py (thread锚定)
clusters.json (事件线 + 新信号分离)
```

## Design Principles

### 铁律
1. **全部代码驱动** — 8 个 stage 全部由代码执行，search.py 调搜索引擎 API，edit.py 调 LLM API
2. **stage 脚本独立可运行** — 每个 stage 可以单独调用和测试
3. **桥接层零侵入** — Story Bridge 用 try/except 包裹，story-tracking 未初始化时静默跳过
4. **Domain-agnostic** — orchestrator 不包含任何领域特定逻辑
5. **路径从 config 读取** — output_dir 等路径从 config.yaml 加载，无硬编码

## Dependencies

### 依赖
- `stratum/stages/` — 8 个 stage 脚本（search, enrich, verify, normalize, cluster, edit, validate, render）
- `stratum/subsystems/story-tracking/` — EventStore, BriefingContext, Gate, Taxonomy
- `domains/{id}/` — domain.yaml, queries.yaml, taxonomy.yaml, prompts/, templates/
- `config.yaml` — output_dir, engines, llm 配置

### 被依赖
- Cron — 定时触发

## Evolution Notes

### v2.0 (2026-05-29)
- Agent Edit 从手动 placeholder 改为 edit.py 自动调用 DeepSeek
- 新增 thread_keywords 导出 + normalize 消费闭环
- 路径全部改为从 config.yaml 读取
- 删除 print_agent_placeholder 死代码
