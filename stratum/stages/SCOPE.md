# stages — 确定性 Pipeline 阶段

## Purpose
日频简报管线的 6 个确定性处理阶段。每个阶段是独立可运行的纯函数脚本，通过标准 CLI 接口串联。

阶段顺序：enrich → verify → normalize → cluster → validate → render

## Boundaries

### ✅ 每个 stage 的共性契约
- 标准 CLI：`--input <path> --output <path> [--domain <config>] [--date <ISO>]`
- 只读输入文件，只写输出文件
- 不访问网络，不调用 LLM
- 独立可测试

### ❌ 不做什么
- **不执行 Agent 步骤** — Search 和 Edit 由 agent_interface.py 定义契约，pipeline.py 调度
- **不包含领域知识** — 领域配置从 domain.yaml 注入

## 各 Stage 速览

| Stage | 输入 | 输出 | 职责 |
|:---|:---|:---|:---|
| enrich | raw.json | enriched.json | 补全日期等元数据 |
| verify | enriched.json | verified.jsonl | 过验证门（去重、去噪） |
| normalize | verified.jsonl | articles.jsonl | 标准化为 ArticleRecord |
| cluster | articles.jsonl | clusters.json | 按实体/术语聚类 |
| validate | briefing.md + articles.jsonl | gate pass/fail | 简报形式校验 |
| render | briefing.md + template | HTML + PDF | 模板渲染输出 |

## Design Principles

### 铁律
1. **纯函数** — 只读输入、只写输出，无副作用
2. **单文件脚本** — 每个 stage 一个 .py 文件，通过 subprocess 调用
3. **Domain-agnostic** — 领域配置通过 --domain 参数注入

## Dependencies

### 依赖
- domain.yaml（运行时注入）

### 被依赖
- orchestrator/pipeline.py
