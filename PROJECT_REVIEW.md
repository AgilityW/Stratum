# Stratum 项目 Review

Review 日期：2026-05-28  
范围：架构、模块设计、代码实现、文档描述、现有 TODO。

## 总体结论

Stratum 的方向很清楚：它不是单纯的每日新闻摘要，而是试图把每日采集沉淀成多时间尺度的行业情报系统。核心抽象也比较稳：`ArticleRecord -> StoryCluster -> EventThread -> TrendTheme -> QuarterlyThesis -> AnnualNarrative` 负责内容记忆；`SourceRecord -> SourceProfile -> TrialPool` 负责信源智能；`domain.yaml` 承载行业语义，框架和通用模块保持行业无关。

但当前项目更像“设计规范 + 部分原型实现”，还不是一个完整可执行系统。除 `source-graph-engine` 下的 Python 文件外，大部分模块是 `SKILL.md` 说明，并没有对应的可运行实现、测试、统一 CLI 或 artifact store。README 和 TODO 对完成度的表述偏乐观，容易让维护者误以为 v4.0 已端到端落地。

建议下一阶段目标不要继续扩展新功能，而是先把“规范驱动的技能集合”收束成“可运行、可验证、可回归”的最小闭环。

## 架构 Review

### 优点

- 分层方向正确：内容管线和信源智能解耦，`source-recorder` 只读取最终内容产物再写 SourceRecord，能避免内容重组时污染信源统计。
- 行业语义位置清晰：`skills/stratum-storage/data/domain.yaml` 集中管理公司、术语、信源、查询和 gap search，符合“框架无行业逻辑”的目标。
- 多时间尺度建模有价值：日报负责证据，周报/月报/季度/年度负责趋势和判断校准，这比一次性摘要更适合长期研究。
- locale-router 的责任边界清楚：语言展开、engine 匹配、query/channel 过滤独立于采集和编辑。

### 主要问题

- 管线顺序存在文档冲突。`skills/stratum/SKILL.md` 把 `source-graph-engine` 放在 Step 2.5，但又说“After Step 3 results are in”才回灌搜索结果；`docs/multi-scale-intelligence-architecture.md` 则把 graph update 放在 collection、normalize、thread 之后。这说明“生成查询”和“消费结果更新图谱”两个动作应该拆成两个明确阶段。
- README 写的是“18 skills”，实际 `find skills -name SKILL.md` 有 19 个，其中包含 `stratum-deployment`，README 模块表未列入。模块清单和安装统计会不一致。
- Content Pipeline 在 README 标为 Steps 0-8，但 `stratum/SKILL.md` 已经定义到 Step 10，且包含 8.5/8.6。入口文档和核心规范不同步。
- `docs/multi-scale-intelligence-architecture.md` 与根目录 `MULTI_SCALE_INTELLIGENCE_ARCHITECTURE.md` 内容完全相同，维护上会产生双源漂移风险。
- 架构文档仍在描述待新增的 `query-planner`、`periodic-brief-engine`、`source-performance-engine`、`artifact-store`，而当前 README/TODO 又把拆分后的部分能力标为 Done。需要区分“原始设计稿”和“当前实现设计”。

## 模块设计 Review

### stratum / stratum-storage

- `stratum` 的 orchestration 文档足够完整，读者能理解完整日报生命周期。
- `stratum/SKILL.md` frontmatter 中有两个 `version` 字段，YAML 解析时前者会被后者覆盖，属于元数据质量问题。
- `stratum-storage` 对“Newsroom 是验证层，不是发现层”的定位很好，能降低低频官方源对每日采集的噪声。
- `stratum-storage` 的输出规范和编辑纪律清楚，但和 ArticleRecord/StoryCluster schema 之间缺少字段映射说明，例如 labels 在内部存在但最终输出禁止出现，应该明确在哪一层剥离。

### locale-router

- 设计为纯函数是正确的。
- 目前只有说明，没有实现和测试。语言 fallback、API key 缺失、channel URL locale 推断这类规则很容易在实现时走偏，建议优先代码化。
- 文档中 tavily fallback 可能掩盖错误：如果某语言没有合适 engine，应该区分“显式 fallback”与“配置错误”，至少输出结构化 warning。

### article-normalizer / story-cluster-engine / event-thread-engine

- 三者的抽象关系合理：Article 是证据，Cluster 是当天分析单元，Thread 是跨日记忆。
- 目前都是规范，没有实现。对下游而言，关键风险是 schema 没有机器校验，字段名、枚举值、日期格式一旦偏移，会连锁影响 source-recorder 和周期简报。
- 建议把 JSON Schema 或 Pydantic/dataclass 模型提到 P0，不要只靠 Markdown schema。

### source intelligence 模块

- `source-recorder` 和 `source-profiler` 的解耦设计是项目里最稳的一块。
- `trial-source-manager` 的生命周期设计也对，但它依赖 graph candidate、trial query 注入、SourceRecord sample_count，这些衔接点目前没有统一 artifact contract。
- `health-tracker` 与 `source-profiler` 职责有重叠倾向：一个追踪命中率，一个追踪源质量。建议明确 health 是运行健康，profile 是编辑价值，避免两个模块各自维护一套 source 状态。

### source-graph-engine

- 这是项目里唯一较完整的代码实现，数据结构、演化策略、序列化基本成形。
- 但它现在承担了候选提取、评分、状态转换、边更新、query 生成多种职责。短期可以接受，长期建议把 policy 和 storage/IO 拆开，方便测试和调参。

## 代码 Review

我运行了：

```bash
python3 -m py_compile skills/source-graph-engine/*.py
```

结果：语法编译通过。项目中未发现测试目录或 pytest/unittest 配置。

### P0 代码问题

1. `compute_term_action` 直接复用 `compute_upgrade`，但传入的是 `TermCandidate`。`compute_upgrade` 内部调用 `score_entity_candidate(candidate, {})`，而 `TermCandidate` 没有 `source_tiers` 字段。只要已有 WATCH term 进入升级判断，就会触发 `AttributeError`。

   位置：`skills/source-graph-engine/evolution.py` 第 97-101 行、第 122-127 行。

2. WATCH 节点几乎无法升级为 ACTIVE。新增 entity/term 创建为 WATCH 后不会写入历史观察窗口；后续再次出现时，extractor 因 `graph.find_*_by_alias` 命中而直接 `continue`，导致 `entity_candidates`/`term_candidates` 不包含已知 WATCH 节点，升级逻辑拿不到当天 observation。

   位置：`skills/source-graph-engine/extractor.py` 第 109-127 行，`pipeline.py` 第 123-150 行。

3. Channel 的确认逻辑也拿不到 observation。`compute_channel_action` 需要 `channel_{id}` history，但 pipeline 调用时传 `{}`，因此 `obs` 永远为 0，`CONFIRMATION_REQUIRED` 基本不会产生。

   位置：`skills/source-graph-engine/evolution.py` 第 140-147 行，`pipeline.py` 第 231-244 行。

4. 边权重新增时默认 weight 为 0，重复观测后仍然用 `e.weight * 0.7 + weight * 0.3`，如果调用方不传 weight，边会长期保持 0。当前 `update_edges` 调用 `_upsert_edge` 未传 weight，导致 mention/co_occurrence 边没有有效强度。

   位置：`skills/source-graph-engine/evolution.py` 第 183-213 行、第 216-243 行。

5. `TODAY` 和 `TODAY_STR` 在模块导入时固定。长驻进程或跨午夜执行时会出现日期不一致；`pipeline.py` 使用 CST，`evolution.py` 使用本地 `date.today()`，时区语义也不统一。

   位置：`skills/source-graph-engine/pipeline.py` 第 40-41 行，`skills/source-graph-engine/evolution.py` 第 27-30 行。

### P1 代码问题

- `_slugify` 只替换空格、点和斜杠，对中文、冒号、括号、问号等没有规范化，可能生成不稳定或不适合作为文件/节点 ID 的字符串。
- `ChannelExtractor` 用 `urlparse(ch.url).netloc` 保留 `www.`，但候选域名会 `.replace("www.", "")`，已知 channel 可能被重复发现。
- `pipeline.py` 示例写 `graph, queries, report = evolve(...)`，实际返回 dict，示例会误导调用者。
- `install.sh` 使用 `envsubst`，macOS 默认不一定安装 gettext；项目面向本机 Hermes/Codex 使用时，这会影响 Quick Start。
- `install.sh` 通过 `grep/sed` 解析 YAML，只支持当前简单双引号形式；如果用户把路径改成未加引号或嵌套变量，安装脚本会静默解析错。
- Python 文件使用裸导入 `from graph import ...`，直接从目录运行可行，但作为包或从其他 cwd 调用会脆弱。建议封装成 package 或在 CLI 中显式处理 import path。

## 文档 Review

### 优点

- README 在一屏内讲清楚了项目定位、管线、模块和输出目录，作为概览是有效的。
- `CONTRIBUTING.md` 明确“query/data 在 domain.yaml，SKILL.md 只放编辑规则”，这条很关键。
- 各 `SKILL.md` 的 contract/frontmatter 让模块边界比较容易读。
- `docs/source-intelligence-architecture.md` 用中文描述信源生命周期，和项目目标贴合。

### 问题

- README 的完成度表达需要降级：现在会让人以为 18 个模块都有可运行实现，但实际多数是规范文档。
- README “4 languages by default”后列了 5 个 locale：`zh-CN`, `zh-TW`, `en`, `ja`, `ko`。如果把 `zh` 视为一个源语言，应写清楚“4 source language entries expand to 5 locales”。
- Cron Schedule 写 6 行，但 TODO 里写“7 cron jobs”，且包含 “Storage Weekly”，README 未解释。
- 架构文档没有“当前状态”章节，原始设计、目标设计、已实现状态混在一起。
- 配置示例标题还是 “Daily Briefing”，项目已经改名 Stratum，命名需要统一。
- 文档包含 emoji 和大量符号，作为面向 AI skill 的说明可读性不错，但如果要作为开源项目文档，建议提供一份更朴素的机器可读 contract。

## TODO 建议

### P0：先把系统变成可验证闭环

- [ ] 明确项目状态：在 README 顶部增加“当前实现状态”，区分 spec-only skill、prototype code、可运行模块。
- [ ] 修正 source-graph-engine 的升级路径：已知 WATCH 节点再次出现时也要计入 observation，并保留跨日 history。
- [ ] 为 `TermNode` 写独立的 `compute_term_action`，不要复用 entity scoring。
- [ ] 修正 channel observation 统计，确保新域名能进入 `channels_pending_confirmation`。
- [ ] 给 `_upsert_edge` 传入非零 observation weight，至少让每日同文共现能累积边强度。
- [ ] 统一日期注入方式：`evolve(..., run_date)`，所有模块使用同一 CST run date。
- [ ] 增加最小测试集：graph seed 初始化、entity/term/channel 提取、WATCH->ACTIVE、边权重、序列化 roundtrip。
- [ ] 增加一个最小 CLI：输入 domain.yaml + sample search results，输出 graph-state、discovery-report、new queries。

### P1：收敛模块 contract

- [ ] 为 ArticleRecord、StoryCluster、EventThread、SourceRecord、SourceProfile 定义 JSON Schema 或 Pydantic/dataclass 模型。
- [ ] 实现 locale-router 的纯函数和测试，覆盖 zh expansion、engine fallback、缺 query、缺 API key、channel locale 推断。
- [ ] 增加 artifact-store 的最小版本：统一路径、读写 JSON/JSONL、原子写入、schema 校验。
- [ ] 拆分 source-graph-engine：`extractors`、`scoring_policy`、`transition_policy`、`query_generation`、`storage`。
- [ ] 明确 `health-tracker` 与 `source-profiler` 的边界，并移除重复 source 状态字段。
- [ ] 给 trial-source-manager 定义输入/输出 artifact：candidate format、trial-pool schema、promotion recommendation schema。

### P2：修正文档与安装体验

- [ ] README 模块数量改为实际数量，补充 `stratum-deployment` 或从安装统计中排除它。
- [ ] 删除或链接化重复架构文档，只保留一个 canonical 文件。
- [ ] 把原始设计稿标记为 historical/spec，并新增 `docs/current-architecture.md` 描述当前真实实现。
- [ ] 修正 `stratum/SKILL.md` 重复 `version` 字段。
- [ ] 修正 README 的 Steps、语言数量、cron 数量、输出文件四件套描述。
- [ ] 更新 `config.example.yaml` 标题为 Stratum，并说明 `config.yaml` 被 gitignore。
- [ ] 让 `install.sh` 不依赖 `envsubst`，或在 README 中列为依赖；同时使用 YAML 解析器替代 grep/sed。

### P3：再扩展高级能力

- [ ] 实现 query-planner：合并 seed/gap/watch/auto queries，做预算、去重、过期和来源标记。
- [ ] 接入 passive discover 四信号：引用链、社交链接、覆盖缺口、跨域先导信号。
- [ ] 加入 quarterly review 到 SourceProfile accuracy 的反向校准。
- [ ] 增加 patent/hiring/conference/financial transcript 等非新闻信号类型。
- [ ] 生成 source archive / report card / coverage map，作为长期研究视图。

## 建议的下一步执行顺序

1. 先修 `source-graph-engine` 的 P0 bug，并补测试。
2. 再实现 `locale-router` + artifact-store 最小版本，让日报管线有真实可调用骨架。
3. 然后把 README/TODO 改成准确反映当前状态，避免“文档说已完成，代码还未落地”的认知偏差。
4. 最后再做 source intelligence 的高级扩展。

---

## Fix Resolution（2026-05-28）

以下问题已在本轮修复：

### 代码
| Bug | 修复 |
|:---|:---|
| `source-graph-engine` WATCH→ACTIVE 路径断裂 | 修正 `_promote_watch_to_active()` 中 status 更新逻辑 |
| `TermCandidate` AttributeError | 补全 `TermCandidate` dataclass 字段 |
| `source_entities` 路径缺失 | 新增 `_load_source_entities()` 从 profiles 加载 |
| `seed_query` 不匹配 | 修正 query planner 中的 seed 生成逻辑 |
| `archive_query` 过滤问题 | 修正 time decay 过滤条件 |

测试：`tests/test_bug_fixes.py`，5 项全部通过。

### 文档
| 问题 | 修复 |
|:---|:---|
| README 18 vs 19 skills | 标注 18 pipeline modules，stratum-deployment 是部署文档 |
| README Steps 与 SKILL.md 不同步 | 加注 "Steps 0-8.6 in Collect, 9-10 in Render, see SKILL.md" |
| SKILL.md 双 version 字段 | 去重，保留 v4.0 |
| 双份架构文档 | 根目录改为指针，canonical 在 docs/ |
| config.yaml 标题 "Daily Briefing" | 改为 "Stratum" |
| 语言数量 "5 source languages" | 改为 "4 source → 5 locales" |
| Cron 6 vs 7 | 补全 7 个 cron job 含 Storage Weekly |
| README 缺少实现状态 | 顶部加 Implementation Status 表格 |

### 新增
- JSON Schema：`schemas/article-record.schema.json` + `schemas/story-cluster.schema.json`
- `.gitignore` 例外：`!data/schemas/` → schemas 目录可追踪

---

## Fix Resolution — 2026-05-28 (路径配置化 + 命名统一)

### 路径硬编码
| 问题 | 修复 |
|:---|:---|
| 42 处 `~/WorkSpace/Stratum` 硬编码在 15 个文件中 | 全部改为 `${OUTPUT_DIR}` 变量引用 |
| Python 代码 `os.path.expanduser(f'~/WorkSpace/Stratum/{channel}/data')` 4 处 | 统一改为读取 `config.yaml` 的 `output_dir` |
| SKILL.md contract + 文档中的输出路径固定 | 全部变量化，config.yaml 单点配置 |
| `${OUTPUT_DIR}` 未定义 | `stratum/SKILL.md` 加变量说明段 |

### 命名一致性
| 问题 | 修复 |
|:---|:---|
| 项目目录 `~/ProjectSpace/stratum` 小写 | 重命名为 `~/ProjectSpace/Stratum` |
| README + 文档中 `stratum`/`Stratum` 混用 | 文档中和代码路径中的项目名统一为 `Stratum` |
| Skill 名 `stratum`、`stratum-storage` 等保留小写 | 目录名/标识符保持小写 |

### 文档同步
| 问题 | 修复 |
|:---|:---|
| README 仍描述双 cron（Collect + Render） | 重写为单 Publish cron，加 Makefile 用法 |
| README 输出目录硬编码 | 改为 `${OUTPUT_DIR}`，说明 config.yaml 可配 |
| `docs/multi-scale-intelligence-architecture.md` 路径硬编码 | 改为变量引用 |
| `config.yaml` 输出密钥为 `$HOME` 格式 | 保持不变，运行时代码通过 `os.path.expanduser` 解析 |

---

## Fix Resolution — 2026-05-28 (P1 Source Intelligence)

### Coverage Monitor (new skill)
| 问题 | 修复 |
|:---|:---|
| StoryCluster 缺少信源多样性检测 | 新建 `coverage-monitor` skill，跑在 story-clustering 之后 |
| 单信源类型 + 单 locale 的 cluster 无告警 | 检测 missing_types (official/analyst/media) + missing_locales (zh-CN/en) |
| 高置信度缺口无跟进机制 | high-severity gap → 生成 followup queries → 注入次日 locale-router |

### Trial Source Manager v2.1
| 问题 | 修复 |
|:---|:---|
| 5-dim 评估只有文字描述，无可执行代码 | Step 4 (track samples) + Step 5 (trigger evaluate) 全部替换为可执行 Python |
| 无权重定义 | novelty(0.30), verifiability(0.25), exclusivity(0.20), signal_noise(0.15), depth(0.10) |
| 无阈值 | 0.60 promote / <0.60 archive |
| 人工审批流程缺失 | recommendation 写入 trial-pool.json，标记后等待人工确认——不自动 promote |

### SourceProfile ↔ Quarterly
| 决定 | 原因 |
|:---|:---|
| 跳过 | quarterly-review 从未触发过，集成无实际价值。等季度 review 真正跑起来再考虑。 |

---

## Fix Resolution — 2026-05-28 (Value Chain Monitor)

### 设计原则
| 决策 | 理由 |
|:---|:---|
| 十一层探测模型定义在 domain.yaml | 跨行业复用：换 channel 只需换配置，引擎逻辑不变 |
| 通用引擎 zero domain knowledge | 只读 config 执行搜索，不懂 storage/non-storage |
| 每层独立频率控制 | weekly(5层) / biweekly(1层) / monthly(3层) / daily(1层跳过) / event-driven(1层) |
| 新域名只入 trial pool | 不自动 promote，经过 trial-source-manager v2.1 五维评估 |
| 覆盖告警阈值 per-layer | 上游=2周，管制=4周，标准=12周，基础设施=事件驱动(不告警) |

### 实现
| 项 | 内容 |
|:---|:---|
| domain.yaml | 追加 value_chain section，11 层，460 行配置 |
| value-chain-monitor SKILL.md | 新建，6-step 可执行流程，340 行 |
| cron | `Stratum - Value Chain` 每周日 9:00 CST |
| stratum 框架 | contract modules 加入 value-chain-monitor |
| README | 模块表 + cron 表刷新 (20 skills, 7 crons) |

---

## Fix Resolution — 2026-05-28 (Value Chain Monitor v2.0 — Dynamic Evolution)

### 核心升级
| 机制 | v1.0 | v2.0 |
|:---|:---|:---|
| 信源池 | 静态 domain.yaml | base + runtime-config.json 双文件 |
| 探测模板 | 永久不变 | 按期产出率自动归档/恢复 |
| promote 路径 | trial → 人工确认 → 结束 | trial → 人工确认 → probation 30天 → 期中评估 → confirmed/延伸/demote |
| 膨胀控制 | 无 | 三层刹车: cap(15/5/8), probation, tiered demotion |
| 关键层保护 | 无 | critical 层永不自动淘汰, high 层 flag+二次确认, medium 层自动降 |
| debug | 散落在多个文件 | state.json 单一入口 |
| 审计 | 无 | audit-log.ndjson 记录每一次 evolve 操作 |

### 实现
| 项 | 内容 |
|:---|:---|
| value-chain-monitor v2.0 | 全部重写, 10-step 含 runtime merge/schedule/caps/demotion/probation/state |
| trial-source-manager v2.2 | promote 反馈闭环, 写入 runtime-config |
| promote 反馈链路 | trial→approve→runtime-config→value-chain 下次探测自动纳入 |

---

## Review Addendum — 2026-05-28 (入口层回归)

本轮重新检查当前工作区真实状态，结论是：`source-graph-engine` 单元测试当前通过，但项目入口层存在几个会直接影响维护者使用的回归。优先级高于继续扩展新模块。

### 验证结果

| 命令 | 结果 |
|:---|:---|
| `pytest -q` | 通过，`156 passed in 0.94s` |
| `make test` | 失败：当前环境没有 `python` 命令，Makefile 使用 `python -m pytest` |
| `bash -n skills/health-tracker/scripts/query.sh` | 失败：脚本文件被行号文本污染，shell 语法错误 |
| `pytest tests/data/ -v -m data` | 选中 0 个测试：测试声明了 marker，但测试文件没有实际标记 |

### 新发现问题

| 优先级 | 问题 | 影响 | 位置 |
|:---|:---|:---|:---|
| P0 | `query.sh` 被写入 `1|...` 这类行号前缀 | health-tracker 查询脚本不可执行 | `skills/health-tracker/scripts/query.sh` |
| P1 | Makefile 测试目标依赖 `python`，但当前 macOS 环境只有 `python3` / `pytest` | README 推荐的 `make test` 不可用 | `Makefile` |
| P1 | `test-unit` / `test-schema` / `test-data` 使用 `-m` marker，但测试没有 `@pytest.mark.*` | 分组测试目标会静默跑 0 个测试 | `Makefile`, `tests/` |
| P2 | README、pyproject、模块表版本不一致：README 写 v4.1，`pyproject.toml` 仍为 4.0.0，模块表中 `stratum` 仍写 v4.0 | 发布状态和实际包元数据不一致 | `README.md`, `pyproject.toml` |
| P3 | 本地忽略文件较多：`.DS_Store`、`.pytest_cache/`、多处 `__pycache__/` | 不影响 git 跟踪，但增加 review 噪音 | 工作区 |

### 建议修复顺序

1. 先恢复 `skills/health-tracker/scripts/query.sh` 为合法 shell，并加 `bash -n` 到最小验证步骤。
2. Makefile 增加 `PYTHON ?= python3`，所有 pytest 目标改为 `$(PYTHON) -m pytest`，或直接使用 `pytest`。
3. 给现有测试补 `pytestmark = pytest.mark.unit/schema/data`，或者删除 `-m` 筛选，避免分组目标空跑。
4. 同步 README / `pyproject.toml` / skill frontmatter 的版本号和状态描述；在入口脚本修复前，不建议继续写 “operational / E2E complete”。
5. 清理本地缓存文件，保持后续 review 输出聚焦。
