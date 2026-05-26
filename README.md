# Daily Briefing — 早报框架

## 定位

可插拔的行业早报系统。每个行业（channel）独立采集、独立输出、独立推送。

看完早报 = 今天不用再翻该行业的任何新闻。

## 架构

```
Hermes 注册层（运行时）
~/.hermes/skills/executive-briefing/
├── daily-briefing/SKILL.md          ← 框架 skill：调度 + HTML 渲染 + 推送
└── daily-briefing-storage/SKILL.md  ← 存储通道 skill：采集 + 汇总 → .md

项目文件层（设计 + 模板）
ProjectSpace/daily-briefing/
├── template.html                    ← HTML 模板（框架按绝对路径读取）
├── README.md                        ← 本文件
├── TODO.md                          ← 项目待办
└── channels/storage/
    └── sources.md                   ← 给人看的信源文档（机器不读）

输出层
WorkSpace/DailyBriefing/
├── storage-YYYY-MM-DD.md            ← 中间产物（内容定型）
└── storage-YYYY-MM-DD.html          ← 最终交付（微信公众号兼容 HTML）
```

## 调用链

```
Cron (7:30 CST daily)
  → 加载 skill "daily-briefing"（框架）
    → skill_view('daily-briefing-storage') 加载通道
      → 按通道 SKILL.md 执行采集
      → 输出 storage-YYYY-MM-DD.md
    → 读 template.html → 渲染 .html
    → send_message 推微信
```

## 设计原则

| 原则 | 说明 |
|:---|:---|
| **Skill 注册制** | 所有 SKILL.md 必须注册到 `~/.hermes/skills/`，cron 按名调用 |
| **框架不采集** | 框架只做调度 + 渲染 + 推送，不碰数据 |
| **通道不渲染** | 通道只做采集 + 汇总，输出纯 .md |
| **模板解耦** | template.html 是纯骨架，三个占位符 `{{DATE}}` `{{WEEKDAY}}` `{{CONTENT}}` |
| **中间产物不删** | .md 留作调试/止损/复用 |

## 与 storage-weekly 的区别

| | storage-weekly | daily-briefing |
|:---|:---|:---|
| 频率 | 每周五 | 每天 |
| 深度 | 三段分析 + 态势矩阵 + 可证伪预测 | 标题 + 1-2 句总结 |
| 覆盖面 | 5 大原厂 + B&F + SR + STH | 原厂 + 媒体 + 生态 + 国内 + X |
| 格式 | Markdown（默认）/ PPT / HTML | HTML（微信公众号兼容） |
| 输出 | Obsidian 存档 | 不存档，文件留 WorkSpace |
| 采集 | 主 agent 串行 | 3 worker 并行 subagent |

## 现有 Channel

| Channel | 注册名 | 状态 | 说明 |
|:---|:---|:---|:---|
| 📦 storage | `daily-briefing-storage` | 架构设计中 | 存储行业日报 |

## 交付

- 时间：每天 7:30 CST
- 渠道：微信
- 频率：每周七天
