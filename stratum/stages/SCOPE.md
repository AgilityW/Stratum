# stages — 确定性 Pipeline 阶段

## Purpose
日频简报管线的 8 个处理阶段。每个阶段是独立可运行的脚本，通过标准 CLI 接口串联。

阶段顺序：search → enrich → verify → normalize → cluster → edit → validate → render

## Boundaries

### ✅ 每个 stage 的共性契约
- 标准 CLI：`--input <path> --output <path> [--domain <config>] [--date <ISO>] [--config <yaml>]`
- 只读输入文件，只写输出文件
- 独立可测试
- Deterministic stages (enrich/verify/normalize/cluster/validate/render): 不调 LLM

### ❌ 不做什么
- **不包含领域知识** — 领域配置从 domain.yaml 或 config.yaml 注入

## 各 Stage 速览

| Stage | 输入 | 输出 | 职责 |
|:---|:---|:---|:---|
| search | config.yaml + queries.yaml | raw.json | 调 bocha/tavily API，精确日期过滤 |
| enrich | raw.json | enriched.json | 补全日期等元数据 |
| verify | enriched.json | verified.jsonl | 过验证门（去重、去噪、blocklist） |
| normalize | verified.jsonl + domain.yaml + **thread_keywords.json** | articles.jsonl | 标准化为 ArticleRecord，**三步 term 提取** |
| cluster | articles.jsonl | clusters.json | **thread 锚定 + Jaccard 聚类**，超簇递归拆分 |
| edit | articles.jsonl + clusters.json + story_context.json | briefing.md | 调 LLM 生成简报 |
| validate | briefing.md + articles.jsonl | gate pass/fail | 简报形式校验（来源、日期） |
| render | briefing.md + template | HTML + PDF | 模板渲染输出 |

## 关键 Stage 详细

### normalize — 三步 Term 提取

1. **静态列表匹配** — domain.yaml `flat_entities` + `flat_terms` (现有逻辑)
2. **标题模式提取** — 正则抽取公司名、产品名、数字+单位（如 "12层", "48GB"）
3. **thread_keywords 匹配** — 从 Story Bridge 导出的活跃事件关键词中匹配，命中则：
   - `article.event_thread_id` 设置为匹配的 thread_id
   - `article.terms` 追加 thread 的关键词

新增 CLI 参数: `--thread-keywords <path>` (可选，未提供时退化为仅步骤 1+2)

### cluster — 分层聚类

1. **Phase 0: thread 锚定** — 同一 `event_thread_id` 的文章强制归入同一簇
2. **Phase 1: Jaccard 聚类** — 剩余文章按 entity/term Jaccard ≥ 0.35 聚类 (Union-Find)
3. **Phase 2: 超簇拆分** — >10 篇文章的簇，内部以 threshold+0.1 递归拆分

新增 CLI 参数: `--threshold 0.35` (从 0.25 上调), `--max-size 10`

## Design Principles

### 铁律
1. **单文件脚本** — 每个 stage 一个 .py 文件，通过 subprocess 调用
2. **Domain-agnostic** — 领域配置通过 --domain/--config 参数注入
3. **格式契约化** — 每个 stage 的输入输出 schema 在代码 docstring 中定义

### v5.1 变更 (2026-05-29)
- normalize: 从纯静态 term 提取升级为三步提取，支持 thread_keywords 消费
- cluster: 从纯 Jaccard 升级为 thread 锚定 + 分层聚类，阈值 0.25→0.35，新增超簇拆分
- search/edit: 已在前序版本改为确定性代码驱动

## Dependencies

### 依赖
- domain.yaml（运行时注入）
- config.yaml（search、edit 阶段）
- thread_keywords.json（normalize 阶段，可选）
- story_context.json（edit 阶段）

### 被依赖
- orchestrator/pipeline.py
