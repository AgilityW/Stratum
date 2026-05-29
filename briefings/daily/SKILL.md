---
name: daily-briefing
description: "日报框架 — Pipeline 串联 + 编辑标准 + 输出规范。领域无关。"
category: executive-briefing
version: "2.0"
contract:
  input: "domain config (domain.yaml) + pipeline output (articles.jsonl + clusters.json)"
  output: "daily briefing markdown → HTML → PDF"
---
# Daily Briefing — Framework

日报的通用框架。定义 **如何判断、如何写作、如何输出**。领域知识全部从 `domains/{domain}/` 注入。

## Pipeline 流程

```
Agent Search → Enrich → Verify → Normalize → Cluster → Agent Edit → Validate → Render
   (LLM)      (det.)   (det.)    (det.)     (det.)     (LLM)      (det.)     (det.)
```

详细编排见 `stratum/orchestrator/pipeline.py`。框架只关心 Agent Edit 阶段的编辑规范。

## 编辑标准

### Admission Test（通用）

每篇文章必须过三道门：

1. **信息是否改变判断？**
   - ✅ 改变对行业/客户/供应链/竞争格局/价格趋势的判断 → 主版面
   - ⚠️ 确认已知趋势 → 降级
   - ❌ 无增量 → 排除

2. **平台/跨界来源判断**（领域特定规则从 domain 注入）
   - 非本行业公司（如 NVIDIA、Marvell 对存储行业）不自动排除
   - 测试标准：**是否改变了目标行业的架构判断？**
   - 领域特定准入规则见 `domain.yaml → editorial.platform_admission`

3. **时间窗口**
   - 24 小时内 → 主版面
   - 24-48 小时 → 补充
   - >48 小时 → 背景参考

### Item Labeling（通用）

每条目在进入草稿前必须标注：

| 维度 | 标签 | 说明 |
|:---|:---|:---|
| Novelty | `[first disclosure]` `[update]` `[rehash]` `[market rumor]` | 增量程度 |
| Confidence | A / B / C / D | A=官方公告，B=主流媒体，C=行业博客，D=社交媒体 |
| Impact | 领域特定，从 domain.yaml 注入 | 影响维度 |
| Maturity | `[L1 research]` – `[L6 mass production]` | 技术成熟度（技术新闻必标） |
| Fiscal | `[FY2026 Q1]` / `[CY2026 Q1]` | 财务新闻必标 |
| Source | `[outlet, date](URL)` | 缺失 → 丢弃该条目 |

### Technology Maturity Scale（通用）

| Level | 定义 | 示例 |
|:---|:---|:---|
| L1 | 基础研究 / 论文 | 大学实验室 demo |
| L2 | 概念验证 | 工作芯片，无良率数据 |
| L3 | 原型 | 样品展示 |
| L4 | 工程样品 | 客户 sampling 进行中 |
| L5 | 试产 | 小批量生产，良率爬坡 |
| L6 | 量产 | 大批量、已认证、已出货 |

### Contrarian Check（通用）

每条判断必须包含至少 2 个反向信号：
- 什么信号出现会推翻当前判断？
- 格式："如果 [信号] 出现，则 [当前判断] 需要修正。"

### 编辑纪律（通用）

- **News section**: 零观点、零情绪化语言
- **无来源修饰词**: "显著"/"大幅"/"史无前例" → 量化或删除
- **上下游关联逻辑**: 提到组件价格变化，必须解释传导路径
- **一条一段**: 不把技术和财务信息塞进同一段

### 写作规则（通用）

1. **信号前置**: "SK Hynix 市值突破 $1T" 而非 "据 Bloomberg 报道，SK Hynix..."
2. **数字带上下文**: "$42.8B" 首次出现时附 "+81.8% QoQ"
3. **来源行格式**: `*Source, Source · YYYY年M月D日*`（中文）或 `*Source, Source · Month D, YYYY*`（英文）

## 输出格式

使用 domain 中定义的语言和模板。通用结构：

```markdown
# {domain_title}
## {date_line}

{summary}

---

{articles}

---

### 关注
{watch_items}

### 反向信号
{contrarian_signals}

---

*由 AI Agent 自动生成 · {footer_date}*
```

每篇文章格式：
```markdown
### {title}

{body — 3-5 句核心内容，信号前置}

*{source}, {source} · {date}*
```

**严格禁止**：
- 内部标签（[first disclosure]/[B]/[L3] 等）不得出现在读者输出中
- 板块标签（"Thread 1"、"补充"、"对我们的意义"）不得出现
- 采集状态矩阵、版本号、修复日志不得出现

## 内部删除原因

采集但排除的条目内部记录原因（不对读者输出）：

| Code | Reason |
|:---|:---|
| `STALE` | 超出时间窗口 |
| `NO_SIGNAL` | 未通过 admission test |
| `DUPLICATE` | 同事件多源，保留最优 |
| `LOW_CONFIDENCE` | 来源低于 D 级且无佐证 |
| `IRRELEVANT` | 主题不匹配 |

## 因果链与判断产出（Agent Edit 阶段）

### 目的

Agent Edit 不仅产出读者可见的 briefing.md，还需产出**内部可验证的因果假设**，供 story-tracking 子系统追踪和回溯。

### 输出位置

在 `event-threads.json` 中，除 `threads` 数组外，额外产出两个数组：

```json
{
  "threads": [...],
  "causal_edges": [...],
  "judgments": [...]
}
```

### CausalEdge 格式

每条因果边连接两个 event-thread，带有置信度和因果机制说明：

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `cause_thread_id` | string | 原因 thread 的 id（如 `"et-2026-001"`） |
| `effect_thread_id` | string | 结果 thread 的 id |
| `mechanism` | string | 因果传导机制，≤ 500 字符 |
| `confidence` | string | A / B / C |

```json
{
  "cause_thread_id": "et-2026-001",
  "effect_thread_id": "et-2026-002",
  "mechanism": "CXMT IPO → 获得 ¥200B 资金 → DDR5 产能扩张 → 对三星/SK 海力士形成价格压力",
  "confidence": "B"
}
```

**生成规则**：
- 仅连接**同一日 briefing 中出现的 thread**（不跨日）
- 因果链必须是**可验证的**——有明确的传导路径，不是"相关即因果"
- 每对 thread 最多一条边
- 置信度：A=强证据支撑（官方声明中的因果陈述），B=合理推断，C=猜测

### Judgment 格式

判断是一个**可测试的假设**——未来某个时点可以被证实或证伪。

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `target_type` | string | `"entity"` 或 `"event_pair"` |
| `target_entity_ids` | list | 当 type=entity 时，taxonomy entity id（如 `["cxmt"]`） |
| `target_thread_ids` | list | 当 type=event_pair 时，涉及的 thread id |
| `hypothesis` | string | 可被验证的陈述，≤ 500 字符 |
| `confidence` | string | A / B / C |
| `expected_verification` | string | 预期可验证的日期 YYYY-MM-DD |

**Entity judgment 示例**：
```json
{
  "target_type": "entity",
  "target_entity_ids": ["cxmt"],
  "hypothesis": "CXMT 将在 3 个月内获得至少 2 家一线 OEM 的 DDR5 验证通过",
  "confidence": "B",
  "expected_verification": "2026-08-28"
}
```

**Event pair judgment 示例**：
```json
{
  "target_type": "event_pair",
  "target_thread_ids": ["et-2026-001", "et-2026-002"],
  "hypothesis": "CXMT IPO 完成后 6 个月内，DRAM 合约价格将下降 ≥5%，主要由 DDR5 价格战驱动",
  "confidence": "C",
  "expected_verification": "2026-11-15"
}
```

**生成规则**：
- 每条 briefing 产出 **1-3 个判断**（质量 > 数量）
- 判断必须满足：**具体**（有量化指标）、**有时限**（expected_verification）、**可证伪**（什么信号出现证明它错了）
- 优先为最高优先级的 thread（priority 1-2）生成判断
- 置信度 C 的判断也必须产出——"不知道但想知道"是有效信号

### 摄入流程

Pipeline 在 Stage 8 之后自动执行：
1. 读取 `event-threads.json` 中的 `causal_edges` 和 `judgments`
2. 通过 `find_by_thread_id` 解析 thread_id → event_id
3. 写入 `causal.jsonl` 和 `judgments.jsonl`
4. 建立 causal edge ↔ judgment 双向链接

## 领域接入点

领域通过 `domain.yaml` 注入以下内容：
- `editorial.platform_admission` — 平台来源准入规则
- `editorial.impact_tags` — 影响维度标签
- `editorial.content_routing` — 内容路由规则（Thread 分组）
- `editorial.domestic_coverage` — 特定区域覆盖指导（可选）
- `output_format` — 输出语言和模板（在 `config.yaml` 中）
- `prompts/daily.md` — Agent Edit 的 prompt 模板
