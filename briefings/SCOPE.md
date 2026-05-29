# briefings — Multi-Scale Cognitive Observation Layer

## Purpose

`briefings/` 是 Stratum 的**多尺度观察层**。它不定义模板、不存储 prompt、不实现管线——它定义在每个时间尺度上，系统**观察什么、回答什么问题、如何向上级联、如何向下反馈**。

五个时间尺度构成一条完整的认知闭环：

```
daily       →  信号检测：什么发生了？
weekly      →  信号确认：哪个是真的？
monthly     →  假设验证：上个月判断对吗？
quarterly   →  结构识别：什么被市场低估了？
yearly      →  元认知：今年到底怎么了？我们的判断系统可靠吗？
```

---

## Architecture

### 每个 SKILL.md 的统一模型

每个子目录下的 `SKILL.md` 是 **Hermes 技能文件**，描述在该时间尺度上的**认知工作流**。统一包含七个段落：

| 段落 | 内容 |
|------|------|
| 1. 认知问题 | 这个尺度要回答什么（一句话） |
| 2. 输入契约 | 消费什么数据，来自哪个子系统 |
| 3. 工作流 | Hermes 执行步骤：调什么 pipeline、怎么组装 prompt、怎么验证 |
| 4. 产出 | 输出什么文件、推什么 channel、产什么结构化数据 |
| 5. 级联接口 | 向上游传递什么数据（daily → weekly → monthly → quarterly → yearly） |
| 6. 实体跟踪 | 这个尺度对长期实体跟踪的贡献（粒度、写入什么） |
| 7. 反向反馈 | 向下游子系统发什么信号（源/词/事件/实体/判断系统） |

### 三层分离原则

`briefings/` 本身不存储以下内容：

| 不该在这里 | 正确定位 | 原因 |
|-----------|---------|------|
| LLM prompt 片段 | `edit/prompts/_prompts/` | 给 LLM 看的语义指导 |
| JSON Schema | `edit/prompts/_schemas/` | 给代码验证的硬约束 |
| 输出格式模板 | `domains/{id}/templates/` | 领域特定的 HTML 模板 |
| 管线实现代码 | `stratum/stages/` | 确定性代码 |
| 编辑标准定义 | `edit/prompts/_prompts/` + `_schemas/` | prompt + 闸门组合 |

SKILL.md 引用这些位置，但不重复它们的内容。

---

## Cascade Architecture: Approach 2 — Independent Re-Observation

### 核心原则

**每个时间尺度重新打开同一个时间窗口，用自己的 query 和信源独立搜索原始数据。** 上游尺度的 `briefing.md`（人类可读报告）不传递给下游 LLM。

上游只传递**结构化遗存**——因果链、判断、实体活跃度、事件线状态——作为下游的注意力引导，不是内容边界。

### 为什么是 Approach 2 而不是 Approach 1

| | Approach 1: 摘要的摘要 | Approach 2: 独立重观察 |
|------|----------------------|---------------------|
| weekly 数据源 | 7 天 daily briefing.md | 7 天窗口独立搜索 + daily 结构化遗存 |
| daily 漏掉的信号 | 永远看不到 | 可以捕获（week 窗口重新观察原始数据） |
| 观测窗口形状 | 叠加 7 个 24h 切片 | 一个连续的 7 天窗口 |
| 认知能力 | 只能看到 daily 选择呈现的 | 具备 daily 不具备的跨天模式识别 |

### 具体例子

CXMT 股价连续 5 天每天跌 2%。没有任何一天是"重大事件"。

| | Approach 1 | Approach 2 |
|------|-----------|-----------|
| daily 每日输出 | "CXMT 跌 2%，无特别原因" | 同 |
| weekly 看到什么 | daily 5 天都说是"无特别原因的小跌" | 重新搜索 7 天窗口发现：5 天连跌 10%，分析师开始讨论"IPO 定价过高" |
| weekly 输出 | "本周 CXMT 小幅波动" | "CXMT 连续下跌 10%，市场对 IPO 定价产生疑虑" |
| 认知结果 | **漏掉趋势** | **捕获趋势** |

**Daily 窗口是 24h，天然看不见"连续 5 天小跌"就是一个事件。Weekly 窗口是 7 天，天然能看见 daily 看不见的模式。**

### 上行级联：只传结构化数据，不传可读报告

```
        daily                           weekly
        ─────                           ──────
    ┌───────────┐                 ┌──────────────┐
    │ 独立搜索   │                 │ 独立搜索      │  ← 自己的 query + sources
    │ (24h 窗口) │                 │ (7d 窗口)     │
    └─────┬─────┘                 └──────┬───────┘
          │                              │
          ▼                              ▼
    ┌───────────┐                 ┌──────────────┐
    │ LLM 推理  │                 │ LLM 推理     │
    └─────┬─────┘                 └──────┬───────┘
          │                              │
          ├── briefing.md (人看)          ├── weekly.md (人看)
          │                              │
          ├── causal_edges ──────────────┤  消费：检查因果链是否成立
          ├── judgments ─────────────────┤  消费：哪些判断本周被验证
          ├── entity_activity ───────────┤  消费：实体活跃度排名 → 注意力引导
          └── thread_status_changes ─────┤  消费：事件线状态变迁
                                          │
                                          ├── weekly_judgments (向下)
                                          ├── coverage_report
                                          └── source_health_signals → source-profiler
```

### 每个尺度消费的结构化数据

| 尺度 | 独立搜索窗口 | 消费的上游结构化数据 | 注意 |
|------|------------|-------------------|------|
| daily | 24h | story_context + thread_keywords | 基座层，无上游 |
| weekly | 7d | daily 的 causal_edges, judgments, entity_activity, thread_status_changes | **不读 briefing.md** |
| monthly | 30d | weekly 的 trend_judgments + daily/weekly 的 judgments（回测） | **不读 weekly.md** |
| quarterly | 90d | monthly 的 judgment_corrections + causal graph + value-chain 报告 | **不读 monthly.md** |
| yearly | 365d | quarterly 的 structural_judgments + 全年 causal graph + source health | **不读 quarterly.md** |

---

## Five-Scale Cascade

### 数据流

```
                 ┌──────────────────────────────────┐
                 │          Subsystems              │
                 │  source-graph   entity-store     │
                 │  term-graph     story-tracking   │
                 │  value-chain    trial-source     │
                 └──────┬───────────────┬───────────┘
                        │               │
          ┌─────────────▼───┐   ┌───────▼─────────────┐
          │   Upward Feed   │   │  Downward Feedback   │
          │ (结构化数据)      │   │                      │
          │                 │   │                      │
          │  daily ────────►│   │◄─────── daily        │
          │    │            │   │           │           │
          │    ▼            │   │           ▼           │
          │  weekly ───────►│   │◄─────── weekly        │
          │    │            │   │           │           │
          │    ▼            │   │           ▼           │
          │  monthly ──────►│   │◄─────── monthly       │
          │    │            │   │           │           │
          │    ▼            │   │           ▼           │
          │  quarterly ────►│   │◄─────── quarterly     │
          │    │            │   │           │           │
          │    ▼            │   │           ▼           │
          │  yearly         │   │◄─────── yearly         │
          └─────────────────┘   └───────────────────────┘
```

### 上行（Upward Feed）：结构化数据聚合

每个时间尺度独立搜索 + 消费上游结构化遗存：

| 尺度 | 独立搜索 | 上游结构化数据 |
|------|---------|-------------|
| daily | queries.yaml + sources.yaml（24h 窗口） | story_context + thread_keywords（story-tracking） |
| weekly | queries.yaml + sources.yaml（7d 窗口） | daily 的 causal_edges + judgments + entity_activity + thread_status（7天积累） |
| monthly | queries.yaml + sources.yaml（30d 窗口） | weekly 的 trend_judgments + daily/weekly 的 judgments（待验证假设） |
| quarterly | queries.yaml + sources.yaml（90d 窗口） | monthly 的 judgment_corrections + 季度 causal graph + value-chain 报告 |
| yearly | queries.yaml + sources.yaml（365d 窗口） | quarterly 的 structural_judgments + 全年 causal graph + 全年 source health |

### 下行（Downward Feedback）：反向校准

每个时间尺度的发现反向校准底层子系统：

| 尺度 | 反馈给子系统的信号 |
|------|------------------|
| daily | 新信息源 → trial-source-manager；新术语 → term-graph；新事件线 → story-tracking |
| weekly | 被推翻的判断 → 调整 edit prompt bias；覆盖盲区 → 补充 search query；信源延迟 → source-profiler 降权 |
| monthly | 系统性判断偏差 → edit prompt 加 bias correction；低频实体告警 → entity-store 标记 stale |
| quarterly | 结构变化信号 → entity-store 更新权重；信息源灵敏度排名 → source-profiler；新兴术语热度 → 增加 query 覆盖 |
| yearly | 系统校准：废弃低产 query、调整 entity 追踪优先级、修正 domain.yaml editorial 规则、信源预算重分配 |

---

## Entity Tracking Across Scales

实体（公司、技术、产品）在五个尺度的跟踪粒度不同：

```
                    daily        weekly        monthly       quarterly       yearly
                    ─────        ──────        ───────       ─────────       ──────
事件粒度：          单条新闻      聚合事件       判断验证       结构变化        轨迹归档
实体写入：          event关联    活跃度排名     月度快照       层级移动        年度画像
示例(CXMT)：       DDR5良率80%   3条thread     Q3量产判断    竞争者定位      市场份额0→5%
                                        ↑
                                    可随时纵向拉取"CXMT 全年演变"
```

### 实体纵向追踪协议

1. 每个尺度的 SKILL.md 声明本层对 entity-store 的**写入粒度**
2. entity-store 提供 `get_timeline(entity_id, scale)` 接口：按时间尺度聚合实体事件
3. 跨尺度查询：拉取同一实体在 daily→weekly→monthly→quarterly→yearly 的所有观测，构成完整的**实体演变轨迹**

---

## Directory Structure

```
briefings/
  SCOPE.md                    ← 本文件：跨时间尺度级联架构

  daily/
    SKILL.md                  ← 日报 Hermes 工作流
    queries.yaml              ← 日报专用 query（24h 快讯 + breaking news）
    sources.yaml              ← 日报专用信源（新闻站、RSS feed，不含分析师/研报源）
    manifest.yaml             ← 日报 prompt 装配声明
    → 引用: domains/{domain}/domain.yaml（公司、术语、准入规则）
    → 引用: edit/prompts/_prompts/（写作规则、准入策略）
    → 引用: edit/prompts/_schemas/（CausalEdge、Judgment schema）

  weekly/
    SKILL.md                  ← 周报 Hermes 工作流
    queries.yaml              ← 周报专用 query（7d 趋势、分析师研报、主题深挖）
    sources.yaml              ← 周报专用信源（分析师博客、研报站点、财报源）
    manifest.yaml             ← 周报 prompt 装配声明
    cascade.yaml              ← 级联声明：独立搜索策略 + 消费哪些 daily 结构化数据

  monthly/
    SKILL.md
    queries.yaml              ← 月报专用 query（财报、白皮书、监管动态）
    sources.yaml              ← 月报专用信源
    manifest.yaml
    cascade.yaml              ← 独立搜索策略 + 消费 daily/weekly 结构化数据

  quarterly/
    SKILL.md
    queries.yaml              ← 季报专用 query（跨界信号、宏观指标、技术路线图）
    sources.yaml
    manifest.yaml
    cascade.yaml              ← 独立搜索 + 消费 monthly 修正记录 + value-chain 报告

  yearly/
    SKILL.md
    queries.yaml              ← 年报专用 query（行业回顾、长期叙事验证）
    sources.yaml
    manifest.yaml
    cascade.yaml              ← 独立搜索 + 消费 quarterly 长期判断 + 全年因果网络
```

无模板文件、无 prompt 内容文件、无实现代码。模板在 `domains/{id}/templates/`，prompt 在 `edit/prompts/`。

---

## cascade.yaml 协议

每个非 base 尺度（weekly/monthly/quarterly/yearly）的 `cascade.yaml` 声明两件事：

1. **独立搜索策略** — 这个尺度用自己的 query + sources 重新打开时间窗口
2. **结构化遗存消费** — 从上游尺度消费什么数据，不消费 briefing.md

### 示例：weekly/cascade.yaml

```yaml
# briefings/weekly/cascade.yaml

# ── 独立搜索策略 ──
fresh_search:
  window: 7 days
  queries: queries.yaml       # weekly 专属 query（趋势导向，不是 breaking news）
  sources: sources.yaml       # weekly 额外信源（分析师、研报站点）
  base_sources:               # 也使用 base query 的搜索范围
    - domains/{domain}/queries.yaml

# ── 结构化遗存消费 ──
consume:
  - scale: daily
    window: 7 days
    data:
      - causal_edges          # 检查哪些因果链本周成立/断裂
      - judgments             # 哪些 daily 判断本周被验证/推翻
      - entity_activity       # 实体活跃度排名 → 注意力引导
      - thread_status_changes # 事件线状态变迁
    # 不消费 briefing.md — weekly 用自己的眼睛重新看世界

# ── 产出 ──
produce:
  output:
    - weekly.md
    - weekly_judgments.json
    - coverage_report.json
  feed_to:
    - monthly                 # 向上级联
    - story-tracking          # 更新事件线状态
    - source-profiler         # 信源延迟/灵敏度评分
    - entity-store            # 实体活跃度排名

# ── 下行反馈 ──
feedback:
  - to: source-profiler
    signals:
      - latency_in_days       # 哪些源在本周事件上延迟 >48h
      - sensitivity           # 哪些源率先发现趋势（不是 breaking news 而是持续报道）
  - to: query-manager
    signals:
      - coverage_gaps        # 哪些主题本周零覆盖
      - added_queries        # 本周新发现需要持续追踪的 query
```

### 示例：monthly/cascade.yaml

```yaml
# briefings/monthly/cascade.yaml
fresh_search:
  window: 30 days
  queries: queries.yaml
  sources: sources.yaml

consume:
  - scale: daily
    window: 30 days
    data:
      - judgments             # 30 天所有 daily 判断 → 回测准确率
  - scale: weekly
    window: 4 weeks
    data:
      - trend_judgments       # 4 周的趋势判断 → 哪些成立、哪些推翻
      - coverage_reports      # 4 周覆盖率 → 识别系统性覆盖盲区

feedback:
  - to: edit prompt system
    signals:
      - bias_correction       # "连续 3 月高估 CXMT DDR5 进度" → 在 daily prompt 中调整 bias
      - accuracy_by_signal_type # "官方公告类判断准确率 85%，分析师预测类 55%"
```

---

## Data Layer — SQLite 结构化存储 + 文件输出

五个尺度写入同一套数据表，通过 `scale` 字段区分。跨时间维度的查询走 SQL，不扫文件。

### 设计原则

| 数据放在 | 存放内容 | 为什么 |
|---------|---------|--------|
| **SQLite** (`{domain}.db`) | 所有需要"按条件查"的结构化数据 | 多维度查询、跨尺度关联、事件线串连 |
| **文件系统** (`data/{domain}/`) | 人类可读输出 + pipeline 流转文件 | 流式 I/O、版本追踪、channel 推送 |

### 存储位置

```
{WORKSPACE}/                             # $HOME/WorkSpace/Stratum（config.yaml → output_dir）
  data/
    {domain}/
      {domain}.db                         # SQLite 数据库（零依赖，单文件，以 domain 命名）

      daily/{date}/
        articles.jsonl                   # pipeline 流转（search → enrich → verify → normalize）
        clusters.json
        briefing.md → briefing.html → briefing.pdf   # 人类消费 + channel 推送
        event-threads.json              # LLM 产出（edit.py → validate.py 闸门）

      weekly/{YYYY-Www}/
        search_results/raw.json          # 独立搜索原始结果
        briefing.md

      monthly/{YYYY-MM}/
        search_results/raw.json
        briefing.md

      quarterly/{YYYY-Qn}/
        search_results/raw.json
        briefing.md

      yearly/{YYYY}/
        search_results/raw.json
        briefing.md
```

---

### SQLite Schema — 统一表结构，`scale` 字段区分尺度

```sql
-- ═══════════════════════════════════════════
-- 源
-- ═══════════════════════════════════════════

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,              -- 来源域名
    type TEXT NOT NULL,                -- MEDIA/NEWSROOM/BLOG/ANALYST/SOCIAL
    url TEXT,
    locale TEXT,
    reliability REAL DEFAULT 0.5,
    status TEXT DEFAULT 'trial',       -- active/trial/deprecated/blocked
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE source_profiles (
    source_id TEXT PRIMARY KEY REFERENCES sources(id),
    avg_latency_hours REAL,
    hit_rate_7d REAL,
    hit_rate_30d REAL,
    hit_rate_90d REAL,
    exclusive_rate REAL,
    coverage_breadth TEXT,             -- JSON array
    structural_sensitivity REAL,
    evaluated_at TEXT
);

-- ═══════════════════════════════════════════
-- 搜索 Query
-- ═══════════════════════════════════════════

CREATE TABLE queries (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    locale TEXT NOT NULL,
    intent TEXT NOT NULL,              -- detection/confirmation/verification/context/structural
    thread_id TEXT,                    -- NULL = standalone，非 NULL = 跟随事件线
    domain TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT,
    last_run TEXT,
    hit_count_7d INTEGER DEFAULT 0,
    hit_count_30d INTEGER DEFAULT 0,
    signal_score REAL DEFAULT 0
);

-- ═══════════════════════════════════════════
-- 实体（公司、技术、产品、标准）
-- ═══════════════════════════════════════════

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,                -- COMPANY/TECHNOLOGY/PRODUCT/STANDARD
    name_en TEXT,
    name_zh TEXT,
    aliases TEXT,                      -- JSON array
    status TEXT DEFAULT 'emerging',    -- emerging/active/dominant/cooling/deprecated
    importance REAL DEFAULT 0.5,
    first_seen TEXT,
    last_seen TEXT,
    domain TEXT NOT NULL
);

-- ═══════════════════════════════════════════
-- 术语
-- ═══════════════════════════════════════════

CREATE TABLE terms (
    id TEXT PRIMARY KEY,
    type TEXT,
    name_en TEXT,
    name_zh TEXT,
    aliases TEXT,
    parent_id TEXT REFERENCES terms(id),
    frequency_7d INTEGER DEFAULT 0,
    frequency_30d INTEGER DEFAULT 0,
    trend TEXT DEFAULT 'stable',       -- rising/stable/declining/emerging
    domain TEXT NOT NULL
);

-- ═══════════════════════════════════════════
-- 事件线（跨天追踪的容器）
-- ═══════════════════════════════════════════

CREATE TABLE threads (
    id TEXT PRIMARY KEY,               -- et-2026-001
    label TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'emerging',    -- emerging/active/cooling/dormant/resolved
    priority INTEGER DEFAULT 3,
    first_event_date TEXT,
    last_event_date TEXT,
    event_count INTEGER DEFAULT 0,
    domain TEXT NOT NULL,
    parent_thread_id TEXT REFERENCES threads(id)
);

-- 事件线 ↔ 实体（多对多）
CREATE TABLE thread_entities (
    thread_id TEXT REFERENCES threads(id),
    entity_id TEXT REFERENCES entities(id),
    PRIMARY KEY (thread_id, entity_id)
);

-- ═══════════════════════════════════════════
-- 事件（事件线中的单日/单节点）
-- ═══════════════════════════════════════════

CREATE TABLE events (
    id TEXT PRIMARY KEY,               -- ev-2026-05-30-001
    thread_id TEXT NOT NULL REFERENCES threads(id),
    scale TEXT NOT NULL,               -- daily/weekly/monthly/quarterly/yearly
    date TEXT NOT NULL,                -- 所属日期/周期
    title TEXT,
    article_ids TEXT,                  -- JSON array
    entity_ids TEXT,                   -- JSON array
    term_ids TEXT,                     -- JSON array
    confidence TEXT DEFAULT 'B',
    briefing_id TEXT,
    created_at TEXT
);

-- ═══════════════════════════════════════════
-- 因果边
-- ═══════════════════════════════════════════

CREATE TABLE causal_edges (
    id TEXT PRIMARY KEY,
    cause_thread_id TEXT NOT NULL REFERENCES threads(id),
    effect_thread_id TEXT NOT NULL REFERENCES threads(id),
    mechanism TEXT NOT NULL,
    confidence TEXT DEFAULT 'B',
    scale TEXT NOT NULL,               -- daily/quarterly
    source_briefing TEXT,
    verified INTEGER,                  -- NULL=pending, 0=false, 1=true
    verified_at TEXT,
    created_at TEXT
);

-- ═══════════════════════════════════════════
-- 判断（可验证的假设）
-- ═══════════════════════════════════════════

CREATE TABLE judgments (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,         -- entity/event_pair
    target_entity_ids TEXT,            -- JSON array
    target_thread_ids TEXT,            -- JSON array
    hypothesis TEXT NOT NULL,
    confidence TEXT DEFAULT 'B',
    expected_verification TEXT,
    scale TEXT NOT NULL,               -- daily/weekly/quarterly/yearly
    source_briefing TEXT,
    result TEXT,                       -- NULL/correct/incorrect/partially_correct
    verified_at TEXT,
    actual_outcome TEXT,
    created_at TEXT
);

-- ═══════════════════════════════════════════
-- 覆盖率
-- ═══════════════════════════════════════════

CREATE TABLE coverage (
    id TEXT PRIMARY KEY,
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    domain TEXT NOT NULL,
    covered_threads TEXT,              -- JSON array
    missed_threads TEXT,
    stale_entities TEXT,
    source_contribution TEXT           -- JSON {source: article_count}
);

-- ═══════════════════════════════════════════
-- 级联运行日志
-- ═══════════════════════════════════════════

CREATE TABLE cascade_logs (
    id TEXT PRIMARY KEY,
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    run_at TEXT,
    consumed_from TEXT,
    consumed_window TEXT,
    consumed_count INTEGER,
    fresh_search_articles INTEGER,
    produced_judgments INTEGER
);

-- ═══════════════════════════════════════════
-- 实体快照（各尺度的定期快照）
-- ═══════════════════════════════════════════

CREATE TABLE entity_snapshots (
    entity_id TEXT REFERENCES entities(id),
    scale TEXT NOT NULL,
    period TEXT NOT NULL,
    status TEXT,
    key_events TEXT,                   -- JSON array
    article_count INTEGER,
    thread_ids TEXT,                   -- JSON array
    PRIMARY KEY (entity_id, scale, period)
);
```

---

### Pipeline 对数据库的读写

```
daily 运行时：
  Search Stage    → SELECT q.text FROM queries q
                    JOIN threads t ON q.thread_id = t.id
                    WHERE (q.thread_id IS NULL)
                       OR (t.status IN ('emerging','active') AND q.intent='detection')
  Normalize Stage → INSERT OR REPLACE INTO entities / terms（新增实体/术语）
                    UPDATE entities SET last_seen = date(...)
  Story Bridge    → INSERT INTO events (...)
                    UPDATE threads SET status=..., last_event_date=..., event_count=...
  Edit Stage      → INSERT INTO causal_edges (...)
                    INSERT INTO judgments (...)
  后处理           → INSERT INTO entity_snapshots (scale='daily', ...)

weekly 运行时：
  级联查询        → SELECT * FROM causal_edges WHERE scale='daily' AND date BETWEEN ... AND ...
                    SELECT * FROM judgments WHERE scale='daily' AND date BETWEEN ... AND ...
                    SELECT * FROM entities WHERE last_seen > date('now', '-7 days')
  级联查询 query  → SELECT q.text FROM queries q
                    JOIN threads t ON q.thread_id = t.id
                    WHERE (q.thread_id IS NULL)
                       OR (t.status IN ('emerging','active','cooling')
                           AND q.intent IN ('detection','confirmation','verification'))
  LLM 产出        → INSERT INTO judgments (scale='weekly', ...)
                    INSERT INTO coverage (scale='weekly', ...)
                    INSERT INTO cascade_logs (...)
  后处理           → INSERT INTO entity_snapshots (scale='weekly', ...)
```

---

### 跨时间维度查询

五个尺度在同一个数据库、同一套表，跨尺度查询就是标准 SQL：

| 查询 | SQL |
|------|-----|
| "CXMT 事件线完整时间线" | `SELECT e.date, e.scale, e.title FROM events e WHERE e.thread_id='et-2026-001' ORDER BY e.date` |
| "CXMT Q2 所有判断" | `SELECT * FROM judgments WHERE target_entity_ids LIKE '%cxmt%' AND created_at BETWEEN '2026-04-01' AND '2026-06-30' ORDER BY scale, created_at` |
| "CXMT 从 emerging 到 competitor 的演变" | `SELECT s.scale, s.period, s.status, s.key_events FROM entity_snapshots s WHERE s.entity_id='cxmt' ORDER BY s.period` |
| "哪些事件线本周断更" | `SELECT * FROM threads WHERE last_event_date < date('now', '-7 days') AND status IN ('active','emerging')` |
| "HBM4 事件线上哪个信源最快" | 从 events 取 article_ids → 从 articles JSONL 取 source → 在应用层聚合 |
| "今年判断准确率" | `SELECT result, COUNT(*) FROM judgments WHERE scale='daily' AND result IS NOT NULL GROUP BY result` |
| "weekly 上次消费 daily 到哪了" | `SELECT MAX(date) FROM events WHERE scale='daily'` + `SELECT consumed_window FROM cascade_logs WHERE scale='weekly' ORDER BY run_at DESC LIMIT 1` |

---

### 数据库和文件的关系

```
                    ┌─────────────────────────┐
                    │      {domain}.db          │
                    │  sources, queries,       │
                    │  entities, terms,        │
                    │  threads, events,        │
                    │  causal_edges, judgments │
                    │  coverage, cascade_logs  │
                    └──────┬──────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    pipeline stages    跨尺度查询        实体追踪
    (INSERT/UPDATE)    (SELECT)        (SELECT)
          │                │                │
          ▼                ▼                ▼
    articles.jsonl    weekly 级联      "CXMT Q2 演变"
    clusters.json     monthly 回测     实体纵向拉取
    event-threads.json quarterly 结构   全年画像
    briefing.md       识别
```

**文件不消失**。`articles.jsonl` 是 pipeline stage 的契约格式，`briefing.md` 是人类的阅读界面，`event-threads.json` 是 edit.py → validate.py 的闸门。SQLite 存的是这些文件里**结构化可查询**的部分——你不能在文件系统里 `SELECT entity_id WHERE ...`，但可以在 SQLite 里。

---

## Boundaries

### ✅ 属于 briefings/ 的
- 每个时间尺度的认知问题定义
- 独立搜索策略（queries.yaml + sources.yaml）
- Prompt 装配声明（manifest.yaml）
- 级联声明（cascade.yaml — 独立搜索 + 结构化数据消费 + 产出 + 反馈）
- 工作流（SKILL.md — Hermes 执行手册）
- 实体跟踪在该尺度的粒度和写入协议

### ❌ 不属于 briefings/ 的
- LLM prompt 内容 → `stratum/stages/edit/prompts/_prompts/`
- JSON Schema → `stratum/stages/edit/prompts/_schemas/`
- 输出模板 → `domains/{id}/templates/`
- 管线代码 → `stratum/stages/`
- 子系统实现 → `stratum/subsystems/`
- 领域配置 → `domains/{id}/domain.yaml`
- 数据存储 → `data/`

---

## Dependencies

### 依赖的子系统
| 子系统 | 用途 |
|--------|------|
| `stratum/stages/edit/` | LLM prompt 组装 + Schema 闸门 |
| `stratum/subsystems/story-tracking/` | 事件线管理 + 跨天上下文 |
| `stratum/subsystems/source-graph/` | 信源发现 + 健康度评估 |
| `stratum/subsystems/entity-store/` | 实体画像 + 跨尺度跟踪 |
| `stratum/subsystems/term-graph/` | 术语演化 + 关键字管理 |
| `stratum/orchestrator/pipeline.py` | 管线调度 |

### 被依赖的
- 无（briefings/ 是顶层消费层，不下沉到代码）
