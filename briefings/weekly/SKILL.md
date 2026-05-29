---
name: weekly-briefing
description: "周度雷达报告框架 — 多源手动采集 → 按厂商分类 → Part 1 雷达 + Part 2 Executive Summary。领域无关。"
category: executive-briefing
version: "2.0"
contract:
  input: "domain config (weekly.yaml) + daily clusters from past 7 days"
  output: "weekly radar report in Obsidian"
---
# Weekly Radar — Framework

## 任务性质

手动多源采集 + 判断合成。**不是**自动化 pipeline，**不是**日度简报。适合需要浏览器交互、RSS 抓取、跨源交叉验证的周度汇总场景。

## 执行流程

### Phase 1: RSS 抓取

使用 `domain.yaml → weekly.rss_feeds` 中定义的 RSS 源。并行 curl 到 `/tmp/`，然后用 Python 解析 XML。

```bash
# 框架只定义模式，具体 URL 从 domain 注入
for feed in ${RSS_FEEDS}; do
  curl -sL "$feed" -o "/tmp/$(basename $feed).xml"
done
```

**禁止** `curl | python3` 管道——会触发安全拦截。先存文件再解析。

### Phase 2: 浏览器抓取

并行 navigate 到 `domain.yaml → weekly.browser_sources` 中的 URL。按 domain 中定义的 per-vendor 特殊规则处理弹窗/cookie/日期问题。

### Phase 3: 处理

1. **时间过滤** — 最近 7 天（从执行日往前推）
2. **去重** — 同一事件多源报道时，选最权威/最早信源，仅记录一条
3. **分类标签** — 每条目标注：`[PR]` / `[Tech]` / `[Product]` / `[Earnings]`，重点关注标 ★

### Phase 4: 输出

**Part 1: 散射型雷达** — 按 domain 定义的厂商顺序，每厂商一节：

```
## {厂商名} {状态指示灯} {一句话定性}

* [{标签}] ★ {标题} — {1-2句核心内容}。*{来源}, {日期}*
* [{标签}] {标题} — ...

**判断：{2-3句产业判断，必须包含"这意味着什么"}**
```

状态指示灯：🟢活跃(2+条) / 🟡一般(1条或仅PR) / 🔴静默(无发布)

最后加"深度技术雷达"节，列出非原厂的行业动态。

**Part 2: Executive Summary** — 使用 domain 定义的 `weekly.judgment_dimensions`，每条判断 150-250 字。加"下周关注"（3-4 条前瞻性关注点）。

### 格式约束

- **结论前置**：每条判断先给断言，再给逻辑
- **来源标注**：每条后跟 `*{来源}, {日期}*`
- **禁止**：框架成瘾、一方面另一方面、模棱两可

### 归档

路径：`${OBSIDIAN_VAULT}/Outputs/{domain_id}_Weekly/YYYY-MM-DD.md`

使用执行周的**周五日期**（周四执行 → 用次日周五日期）。

### 常见陷阱（框架级）

1. **curl | python3 被拦截** → 安全策略禁止管道到解释器，先 `curl -o` 再 `python3`
2. **日期不明显的源** → 需结合多源交叉验证时间
3. **RSS feed 不稳定** → 不依赖单一 RSS，浏览器抓取为后备
4. **浏览器弹窗/cookie** → 参考 domain 配置中的 per-source 备注
