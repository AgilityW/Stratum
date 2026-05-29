# Story Evolution — Implementation TODO

> 基于 STORY_EVOLUTION.md v1.0 和更新的 SCOPE.md 文件
> 改动模块: story_bridge / normalize / cluster / pipeline

---

## T1: story_bridge — export_thread_keywords()

**文件**: `stratum/orchestrator/story_bridge.py`

**新增函数**: `export_thread_keywords(repo, domain_id, output_path)`
- 读取所有 active/pending 的 EventRecord
- 对每条事件，从 title + entities + terms 推导关键词列表
- 关键词推导规则: title 中出现的公司名、产品名、专有名词；entities 列表
- 输出 thread_keywords.json（格式见 STORY_EVOLUTION.md § Data Contract ①）

**测试**: 用 events.jsonl 的 7 个 active event 验证输出格式

---

## T2: normalize — 三步 Term 提取

**文件**: `stratum/stages/normalize/normalize.py`

**改动**:
1. 新增 CLI 参数 `--thread-keywords <path>` (可选)
2. 新增 `extract_title_patterns(title)` — 正则从标题中抽:
   - 公司名（大写字母序列、中文公司名关键词）
   - 产品名（HBM4E、DDR5、NAND 等）
   - 数字+单位（12层、48GB、295亿、20%）
3. 重构 `extract_terms()` → `extract_terms_v2()`:
   - 合并三个来源: static + title_patterns + thread_keywords
4. thread 匹配逻辑: 如果 thread_keywords 中的 keywords 命中标题/摘要，设置 `event_thread_id`

**测试**: 
- 单测 extract_title_patterns（输入标题→预期术语）
- 集成测: 给定 thread_keywords.json + articles，验证 event_thread_id 正确赋值
- 向后兼容: 不传 --thread-keywords 时行为不变

---

## T3: cluster — thread 锚定 + 分层聚类

**文件**: `stratum/stages/cluster/cluster.py`

**改动**:
1. 阈值默认值 0.25 → 0.35
2. 新增 `--max-size` 参数，默认 10
3. `cluster_articles()` 改为三阶段:
   - Phase 0: 同 event_thread_id 强制合并为簇
   - Phase 1: 剩余文章 Union-Find Jaccard ≥ threshold
   - Phase 2: 超簇（>max_size）以 threshold+0.1 递归拆分
4. `build_cluster_object()` 新增字段: `thread_id`, `is_continuation`

**测试**:
- 单测 max_size 拆分正确
- 单测 thread_id 锚定优先级高于 Jaccard
- 回归: 旧 0.25 阈值行为仍可通过 CLI 参数复现

---

## T4: pipeline — 串联闭环数据流

**文件**: `stratum/orchestrator/pipeline.py`

**改动**:
1. Stage 5→6 之间（cluster 完成 → edit 之前）:
   - 新增函数 `_export_thread_keywords(domain_id, paths)`
   - 从 story-tracking events 导出 thread_keywords.json
2. Stage 4 (normalize) 调用时增加参数:
   - `--thread-keywords` → thread_keywords_path
   - 如果文件不存在则省略此参数（向后兼容）
3. 确保 thread_keywords_path 在 paths dict 中定义

**测试**:
- 全链路: 跑一次 real pipeline，验证 normalize 消费了 thread_keywords
- 空数据: story-tracking 无数据时不报错

---

## T5: 端到端验证

**验证**:
1. 启动前: 确认 events.jsonl 有 7 个 active event
2. 运行 `python3 pipeline.py --domain storage --date 2026-05-29`
3. 检查:
   - thread_keywords.json 生成且包含 7 条 thread
   - articles.jsonl 中有 event_thread_id 的记录 ≥ 5
   - clusters.json 的簇数 ≥ 4（从 3 增加）
   - 每个簇 ≤ 10 篇（max_size 生效）
   - 有 thread_id 的簇带 `is_continuation: true`
4. 最终输出 briefing HTML+PDF 正常生成
