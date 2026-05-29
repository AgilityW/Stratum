# Story Evolution Architecture — Design Spec v1.0

## Problem

三件事各干各的：
- **normalize** 提取 16 个区分度为零的通用词，聚类全部串在一起
- **cluster** 靠 Jaccard 分堆，不知道历史上下文
- **Story Bridge** 维护跨天事件线，但从不对上游反馈

结果：47 篇文章产出 3 个混乱簇，LLM 全靠自己整理。量越大越崩。

## Goal

一篇文章进入系统后，同时挂在三个维度：

```
  时间轴（Story Bridge）    因果链（Causal Graph）    实体网（Entity Graph）
       ↑                          ↑                        ↑
  5/27 CXMT过会             CXMT IPO → 银行获利       CXMT ←→ 工商银行AIC
  5/28 Predict上线          存储涨价 → SteamDeck涨价    CXMT ←→ YMTC
  5/29 多方资本曝光                                        NAND涨价 ←→ SanDisk
  5/30 ...
```

## Architecture: 3-Layer Closed Loop

```
                    ┌──────────────┐
                    │ Story Bridge  │
                    │ events.jsonl  │
                    │ causal.jsonl  │
                    │ judgments.jsonl
                    └──────┬───────┘
                           │
           ① 每天运行完，导出 thread_keywords.json
              {"thread_id": "et-2026-001",
               "title": "CXMT科创板IPO",
               "keywords": ["CXMT","长鑫","科创板","DRAM","295亿","IPO"],
               "entities": ["CXMT","工商银行AIC","华胥基金"],
               "priority": 1,
               "open_questions": [...]}
                           │
                           ▼
                    ┌──────────────┐
                    │  normalize   │
                    │              │
                    │ ② 三步提取 terms:
                    │   a) domain.yaml 静态列表 (现用)
                    │   b) 标题正则: 公司名/产品名/数字+单位
                    │   c) thread_keywords 匹配: 命中则打标签
                    │
                    │ 输出:
                    │   article.event_thread_id = "et-2026-001"
                    │   article.terms += ["CXMT","科创板","295亿"]
                    │   article.entities += ["工商银行AIC"]
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   cluster    │
                    │              │
                    │ ③ 分层聚类:
                    │   优先: 同 thread_id 强制合并
                    │   其次: terms Jaccard ≥ 0.35 合并
                    │   约束: 超 10 篇递归拆分
                    │
                    │ 输出:
                    │   簇1 [CXMT IPO] 8篇 ← thread锚定
                    │   簇2 [HBM4E] 5篇    ← thread锚定
                    │   簇3 [NAND涨价] 6篇 ← terms聚类
                    │   簇4 [SteamDeck] 3篇 ← 新信号
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │     edit     │
                    │              │
                    │ ④ LLM拿到:
                    │   每个事件簇+跨天上下文
                    │   新信号标记为潜在新事件
                    │   因果判断回溯
                    │
                    │ 输出:
                    │   briefing.md + 新event_threads
                    │   + causal_edges + judgments
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Story Bridge  │──→ 明天 normalize
                    │  更新闭环     │
                    └──────────────┘
```

## Data Contracts

### ① thread_keywords.json (Story Bridge → normalize)

```json
{
  "generated_at": "2026-05-29",
  "domain": "storage",
  "threads": [
    {
      "thread_id": "et-2026-001",
      "title": "CXMT科创板IPO与中国DRAM崛起",
      "keywords": ["CXMT", "长鑫", "长鑫科技", "科创板", "IPO", "295亿", "DRAM"],
      "entities": ["CXMT", "工商银行AIC", "华胥基金"],
      "priority": 1,
      "status": "active"
    }
  ]
}
```

### ② ArticleRecord 新增字段 (normalize 输出)

```
event_thread_id: Optional[str]     # 匹配到的 Story Bridge thread
event_match_confidence: str        # "direct" | "partial" | null
```

### ③ StoryCluster 新增字段 (cluster 输出)

```
thread_id: Optional[str]           # 锚定的事件线程
is_continuation: bool              # 是否已有事件线的延续
cross_temporal_context: str        # 前情摘要 (LLM消费)
```

## Module Changes

### MODULE A: normalize.py

**改动**: extract_terms 从纯静态列表变成三个来源

```python
def extract_terms_v2(title, snippet, flat_terms, thread_keywords):
    terms = set()
    # Source 1: domain.yaml flat_terms (现有)
    for t in flat_terms:
        if t in text:
            terms.add(t)
    # Source 2: 标题模式提取
    terms |= extract_title_patterns(title)  # 公司名, 产品名, "12层", "48GB"
    # Source 3: thread_keywords 匹配
    for thread in thread_keywords:
        if any(kw in text for kw in thread["keywords"]):
            terms |= set(thread["keywords"])
            article.event_thread_id = thread["thread_id"]
    return list(terms)
```

**新增函数**: `extract_title_patterns` — 正则提取标题中的命名实体

**新增参数**: `--thread-keywords` 指向 thread_keywords.json

### MODULE B: cluster.py

**改动**: 两阶段聚类

```python
def cluster_articles_v2(articles, threshold=0.35, max_size=10):
    # Phase 0: thread_id 锚定 — 同thread强制合并
    thread_groups = defaultdict(list)
    orphans = []
    for i, a in enumerate(articles):
        tid = a.get("event_thread_id")
        if tid:
            thread_groups[tid].append(i)
        else:
            orphans.append(i)
    
    # Phase 1: 对 orphans 做 Union-Find Jaccard
    orphan_clusters = cluster_by_jaccard(
        [articles[i] for i in orphans], threshold, max_size
    )
    
    # Phase 2: 合并 thread_groups + orphan_clusters
    return merge_results(thread_groups, orphan_clusters)
```

### MODULE C: story_bridge.py (or new export function)

**改动**: 新增 `export_thread_keywords()` 函数

```python
def export_thread_keywords(repo, domain_id, output_path):
    """读取所有 active events，export 为 normalize 可消费的格式"""
    events = repo.all_active()
    threads = []
    for ev in events:
        threads.append({
            "thread_id": ev.thread_id,
            "title": ev.title,
            "keywords": _derive_keywords(ev),  # 从 event title + entities 推导
            "entities": ev.entities,
            "priority": ev.priority,
            "status": ev.status,
        })
    # 写入 thread_keywords.json
```

### MODULE D: pipeline.py

**改动**: 在两个阶段之间插入数据流

```python
# Stage 5 → Stage 6 之间:
# 导出 thread_keywords.json
_export_thread_keywords(args.domain, args.date, paths)

# Stage 4 (normalize) 调用时加参数:
"--thread-keywords", thread_keywords_path
```

**不需要动的地方**: edit.py, validate.py, render.py — 它们消费 cluster 输出，cluster 输出格式向上兼容。

## Implementation Order

| Step | Module | Effort | Depends On |
|------|--------|--------|------------|
| 1 | story_bridge: export_thread_keywords() | 小 | — |
| 2 | normalize: 加 --thread-keywords, extract_terms_v2 | 中 | Step 1 |
| 3 | cluster: thread_id 锚定 + 新阈值 | 小 | Step 2 |
| 4 | pipeline: 串联数据流 | 极小 | Step 1+2+3 |
| 5 | 端到端测试 | 中 | Step 4 |

## Success Metrics

改前 (2026-05-29): 3 clusters (19 + 2 + 6), 20 unclustered
改后目标: 6-8 clusters, 每个 ≤ 10 篇, 事件线文章正确锚定, 新信号独立成簇
