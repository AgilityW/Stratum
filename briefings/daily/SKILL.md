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

## 领域接入点

领域通过 `domain.yaml` 注入以下内容：
- `editorial.platform_admission` — 平台来源准入规则
- `editorial.impact_tags` — 影响维度标签
- `editorial.content_routing` — 内容路由规则（Thread 分组）
- `editorial.domestic_coverage` — 特定区域覆盖指导（可选）
- `output_format` — 输出语言和模板（在 `config.yaml` 中）
- `prompts/daily.md` — Agent Edit 的 prompt 模板
