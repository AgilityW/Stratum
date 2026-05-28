# Source Intelligence Architecture

> Stratum 信源智能子系统——信号类型驱动渠道发现，评估闭环反馈采集策略

---

## 1. 核心理念

**不找"像 TrendForce 一样的网站"。找我们完全在接收的信号类型。**

当前系统的所有信息来自一个来源：新闻搜索索引。存储行业的很多决定性信号不出现在新闻里——它们出现在专利数据库、招聘页面、设备商财报、学术会议、海关记录。每次发现一种新的信号类型，自然就解锁一整类新的信息渠道。

```
信号类型 → 渠道 → 采集方式 → SourceRecord → SourceProfile
    ↑                                                    │
    └──────────────── 闭环反馈 ──────────────────────────┘
```

---

## 2. 核心对象

### 2.1 SourceRecord（原子层）

和 ArticleRecord 同时落盘，独立存储。记录单次贡献。

```yaml
SourceRecord:
  id: string                    # "sr-{source}-{article_id}"
  source: string                # "TrendForce"
  source_type: official | media | analyst | blog | social | financial | patent | hiring | conference | satellite
  source_locale: zh-CN | en | ja | ko
  signal_type: text_news | structured_data | cross_domain | non_text
  article_id: string
  cluster_id: string
  thread_id: string
  date: string
  role: first_disclosure | confirmation | update | rehash | disputed
  claims_contributed: [string]
  verified_by: [string]
  trial: boolean
```

`signal_type` 是新增字段——同一篇文章可能是 `text_news`，一个专利条目是 `structured_data`，一篇 AI 架构论文关于内存带宽是 `cross_domain`。

### 2.2 SourceProfile（聚合层）

持续更新的画像，带时间维度。每次质变事件触发追加 checkpoint。

```yaml
SourceProfile:
  source: string
  source_type: string
  source_locale: string
  signal_type: string
  status: trial | active | cooling | deprecated

  # 当前快照（机读）
  current:
    novelty_ratio: 0.35
    verifiability: 0.80
    exclusivity: 0.15
    signal_noise_ratio: 0.70
    coverage_domains: [DRAM, HBM, 中国存储]
    coverage_gaps: [日本供应链]
    seed_weight: 1.0
    watch_inject: []

  # 历史轨迹（不可变，thesis 回溯时追加）
  checkpoints:
    - quarter: "2026-Q2"
      type: promotion | evaluation | degradation
      metrics: {novelty: 0.35, verifiability: 0.80, accuracy: 0.70}
      reason: "Q2 thesis confirmed — this source pushed correct signal"

  # 变化事件日志
  events:
    - date: "2026-07-01"
      type: quarterly_review | degradation_alert | promotion | demotion
      detail: "accuracy dropped 0.7 → 0.5"

  # 人读字段
  coverage_note: "CXMT coverage strong, Japanese equipment angle missing"
  recommendation: "补强日本设备商视角"
```

checkpoints 在质变事件触发时追加（thesis 判定、连续四周信号退化），不是定时切——信源变化以月/季为粒度。

### 2.3 TrialPool（管理层——不是数据对象）

Trial 是信源生命周期的一个阶段，不是单独的对象类型。试用中的源仍然生成 SourceRecord（trial=true），仍然有 SourceProfile（status=trial）。TrialPool 是管理元数据——队列状态、进度追踪、加速信号——引导阶段转换的临时信息。晋升后管理元数据清掉，发现上下文转为 Profile.events 第一条。

```yaml
TrialPool:
  entries:
    - source: "eetimes.jp"
      source_type: "media"
      source_locale: "ja"
      discovered_at: "2026-05-28"
      discovery_channel: "search_result"
      discovery_context: "Found via ja seed query"
      signals:
        cited_by_trusted: false
        social_mention: false
        fills_coverage_gap: true
        fills_signal_type_gap: false
      trial_start: "2026-05-28"
      trial_duration_days: 14
      min_samples: 20
      sample_count: 0
      query: "site:eetimes.jp 半導体 メモリ"
      status: "collecting"
  paused: []
  archived: []
```

**为什么不是数据对象**：TrialPool 只记录"这个源还在试用期、还需要多少样本"。试用期结束后这条记录就 archive 了。源的完整画像在 SourceProfile 里——它的 status 字段记录了 trial → active → cooling → deprecated 的完整轨迹。

---

## 3. 信号类型全景

### 3.1 信号类型矩阵

| 类型 | 当前覆盖 | 信号举例 | 渠道举例 | 频率 |
|:---|:---|:---|:---|:---|
| **text_news** | ✅ 已有 | 价格变动、产品发布、财报 | 新闻媒体、分析师 | 日频 |
| **text_news_ja_ko** | ❌ 盲区 | 原厂独家消息、供应链细节 | Nikkei、The Elec、ET News | 日频 |
| **structured_patents** | ❌ 盲区 | 技术路线变更、研发方向 | USPTO、KIPRIS、WIPO | 季频 |
| **structured_hiring** | ❌ 盲区 | 扩产信号、新业务方向 | LinkedIn、公司招聘页 | 周频 |
| **structured_equipment** | ❌ 盲区 | 产能扩张前置信号 | 设备商财报、海关数据 | 季频 |
| **cross_domain_ai** | ❌ 盲区 | 内存架构需求变化 | AI 论文、MLSys、ISCA | 月频 |
| **cross_domain_datacenter** | ❌ 盲区 | 存储采购量级预判 | 云厂商 Capex、电力招标 | 季频 |
| **cross_domain_supplychain** | ❌ 盲区 | 材料/设备瓶颈 | SUMCO、信越、设备商指引 | 月频 |
| **non_text_conference** | ❌ 盲区 | 技术路线图、工艺节点 | ISSCC、VLSI、IMW 程序册 | 季频 |
| **non_text_satellite** | ❌ 盲区 | 工厂建设进度 | 卫星影像、建设许可 | 按需 |

### 3.2 当前覆盖状态

```
已覆盖：text_news (zh, en)
        —— 信息池内部，充分覆盖

零成本可解锁：text_news (ja, ko)
        —— config.yaml 加两行，新机制不需要

需要新采集方式：structured_*, cross_domain_*, non_text_*
        —— 每个类型对应一个新增的采集插件
```

---

## 4. Discover（发现）

### 4.1 被动发现 — 每次采集都做，零额外成本

在已有信息池内发现新域名：

| 信号来源 | 机制 | 产物 |
|:---|:---|:---|
| 搜索结果域名 | source-graph-engine 提取 | 新域名列表 |
| 竞品引用链 | web_extract 时提取 `<a href>` | 被权威源引用的陌生域名 |
| 社交信号 | 已有 social search 结果解析 URL | 被讨论但不在 seed 的域名 |
| 覆盖缺口 | story-clusters 中 `source_diversity: low` | 单源覆盖的话题 → 搜替代视角 |

### 4.2 信号类型缺口扫描 — 周期性，跨出已有信息池

**不做"搜索"，做"查询"不同数据库**：

| 信号类型 | 查询方式 | 发现逻辑 |
|:---|:---|:---|
| 专利 | `site:patents.google.com "HBM" "3D NAND" after:2026` | 找出专利作者/机构 → 他们是否有公开分析 |
| 招聘 | `site:linkedin.com "HBM" "DRAM engineer"` | 哪家公司大量招 HBM 工程师 → 预判技术方向 |
| 设备 | 设备商财报 transcript 中找 "memory customer" "storage order" | 谁在下设备订单 → 6 个月后的产能信号 |
| 会议 | ISSCC/VLSI 程序册中存储 session 的论文作者/机构 | 学术→工业的技术转移路径 |
| 供应链 | 信越/SUMCO 财报中硅片出货区域变化 | 产能建设的物理证据 |

**触发条件**（不按时间，按信号）：

| 触发条件 | 动作 |
|:---|:---|
| 季度 thesis 回溯发现某信号类型长期缺失 | 启动该类型的 discover |
| 新 EventThread 涉及技术路线判断 | 触发专利 + 会议 discover |
| 新 EventThread 涉及产能判断 | 触发招聘 + 设备 + 卫星 discover |
| SourceProfile 显示某语言覆盖率 < 阈值 | 触发该语言的新源 discover |
| 某个源的 novelty 连续下降 | 搜该源覆盖领域的替代源 |

### 4.3 跨界信号 — 不搜存储，搜必然先于存储变化的东西

| 搜索领域 | 搜索词 | 提前量 | 存储信号 |
|:---|:---|:---|:---|
| 设备商 | "AMAT DRAM order" "Lam memory revenue" | 6-9 个月 | 产能扩张 |
| AI 架构 | "memory bandwidth transformer" "KV cache compression" | 12-18 个月 | HBM 需求天花板 |
| 数据中心 | "datacenter power budget 2027" "liquid cooling tender" | 6-12 个月 | 企业级 SSD 需求 |
| 材料 | "silicon wafer shipment region 2026" | 3-6 个月 | DRAM/NAND 产能分布 |

---

## 5. 信源生命周期

```
Discover ──→ Trial ──→ Evaluate ──→ Promote ──→ Monitor ──→ Demote
  │            │           │            │            │           │
  │         14天隔离    五维评分    人工审批    季度回溯    质量退化
  │        (三信号加速)                                     → trial
  └────────────────────────────────────────────────────────────→ Archive
```

### 5.1 Trial（试用）

新源不进 seed，进独立 trial query pool。每天跑但不参与主线 editorial priority。
标准 14 天，至少 20 条样本。

**加速晋升**（四信号叠加 → 14 天缩至 7 天）：
- 被可信源引用
- 填补已知覆盖缺口
- 社交信号确认
- **填补信号类型空白**（新增——首个专利分析源、首个日文原厂源，加速）

### 5.2 Evaluate（评估）

五维评分，全从 SourceRecord 计算：

| 维度 | 指标 | 算法 |
|:---|:---|:---|
| 时效性 | first_disclosure 占比 | role=first_disclosure / 总量 |
| 可验证性 | 被独立确认比例 | verified_by 非空 / 总量 |
| 独家性 | 独特信号占比 | 该源独有的 cluster / 总量 |
| 信噪比 | 非 rehash 占比 | 1 - (rehash / 总量) |
| 准确度 | 季度回溯正确率 | thesis 回溯：推正确 vs 推错误 |

### 5.3 Promote / Demote（决策）

- 评分达标 → 生成推荐报告，用户审批
- 审批通过 → SourceProfile.status 从 trial → active；TrialPool 该条目 → archived；发现上下文转为 Profile.events 首条
- 质量退化 → SourceProfile.status → cooling → deprecated
- 降级 → 回到 trial pool，SourceProfile.status → trial

### 5.4 Monitor（监控）

每季度 thesis 回溯时：

```
strengthened thesis
  → EventThread.timeline
    → 贡献了正确信号的 SourceRecord
      → 对应源 +1 accuracy

reversed thesis
  → EventThread.timeline
    → 推动了错误方向的 SourceRecord
      → 对应源 -1 accuracy
```

---

## 6. 对象关系

```
Signal Type Gap Analysis (周期性)
  │
  ├──→ text_news_ja_ko: config.yaml 解锁 ──→ seed queries
  ├──→ structured_*: 专利/招聘查询 ──→ trial pool
  ├──→ cross_domain_*: 设备商/AI/材料 ──→ trial pool
  └──→ non_text_*: 会议/卫星 ──→ trial pool
         │
         └──→ SourceRecord (trial=true)
                │
                ├── 评估达标 ──→ SourceProfile (首 checkpoint)
                │                   │
                │                   ├── current snapshot → 管线消费
                │                   └── checkpoints[] → thesis 回溯追加
                │
                └── 评估不达标 ──→ archive

被动发现 (每采集)
  → 新域名 → trial pool → (同上)
```

---

## 7. 数据闭环

```
SourceProfile.checkpoints 变化
  ├── accuracy 下降 → 降级/代替搜索
  ├── coverage_gap 存在 → 触发 discover
  ├── novelty 退化 → 搜替代源
  └── signal_type 新增 → 扩展开采集插件

                  → 下次采集按调整后的策略跑
                  → 新的 SourceRecord
                  → Profile 更新
                  → (循环)
```

---

## 8. 人读输出

从 SourceProfile 渲染，季度/年度：

- 信源档案页：覆盖领域、accuracy 曲线、信号类型、推荐动作
- 季度信源成绩单：推动正确/错误判断的源
- 年度信源报告：白名单/灰名单/需替换列表
- **信号类型覆盖图**：哪个信号类型我们缺失、盲区多大

格式：Markdown → Obsidian `Wiki/Stratum/Sources/`

---

## 9. 实施优先级

| 优先级 | 模块 | 依赖 | 说明 |
|:---|:---|:---|:---|
| **P0** | SourceRecord 独立落盘 | article-normalizer 改造 | 基础——无此全部不能做 |
| **P0** | 日韩语 seed queries | config.yaml 加 `ja, ko` | 零成本，立即解锁 |
| **P0** | TrialPool 管理 | source-recorder | 试用队列，隔离管理 |
| **P1** | SourceProfile + checkpoints | SourceRecord + quarterly-review | 聚合 + thesis 回溯 |
| **P1** | 被动发现四信号 | source-graph-engine 改造 | 竞品引用+社交+缺口+跨界 |
| **P2** | Evaluate 五维评分 | SourceProfile | 试用期自动评估 |
| **P2** | 加速晋升逻辑 | TrialPool.signals | 四信号缩短试用期 |
| **P2** | 信号类型缺口扫描 (专利) | 新增 patent-search 插件 | 首个 structured 信号类型 |
| **P3** | 信号类型缺口扫描 (招聘/设备) | 新增 hiring/equipment 插件 | 扩展开采集面 |
| **P3** | 信源档案页生成 | SourceProfile | 人读 |
| **P3** | 跨界信号搜索 | cross-domain query 模板 | AI/数据中心/材料 |
| **P4** | 非文本信号 (会议/卫星) | 新增采集插件 | 低频高价值 |
