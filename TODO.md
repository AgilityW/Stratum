# TODO — Daily Briefing 项目

## 架构待决策

- [ ] **HTML 视觉风格确认**：深蓝 `#1a1a2e` 标题栏 + 白色 `#ffffff` 内容区 + 浅灰 `#f0f4f8` 背景。需要看 mockup 还是直接认可？
- [ ] **品牌色核对**：Samsung `#1428A0` / SK hynix `#E6002D` / Micron `#004B87` / Kioxia `#E5004C` / WDC `#0070C0`
- [ ] **推送时间确认**：7:30 CST，每周七天
- [ ] **周末行为**：如果周末长期无更新，是否周六日合并或暂停？

## Hermes 平台对齐（架构设计已完成，待执行）

- [ ] **Skill 注册**：`skill_manage` 注册两个 skill
  - `daily-briefing` → 框架 skill → `~/.hermes/skills/executive-briefing/daily-briefing/`
  - `daily-briefing-storage` → 存储通道 skill → `~/.hermes/skills/executive-briefing/daily-briefing-storage/`
- [ ] **Cron 创建**：`cronjob create`
  - `skills: ["daily-briefing"]`
  - `schedule: "30 7 * * *"`
  - `deliver: weixin`
  - `enabled_toolsets: [browser, web, terminal, file, skills, session_search]`
- [ ] **调用链验证**：cron → `daily-briefing` → `skill_view('daily-briefing-storage')` → 采集 → .md → .html → 推送

## 技术验证（实施阶段）

- [ ] **Subagent Worker A (RSS+Bocha)** 连通性测试
  - RSS URL 可达？
  - Bocha API key 可用？
  - `curl -o` 模式通过 tirith
- [ ] **Subagent Worker B (Tavily)** 连通性测试
  - Tavily API key 可用？
  - `site:x.com` 搜索覆盖率
- [ ] **Subagent Worker C (Browser)** 脆弱点测试
  - Samsung 地区弹窗
  - WDC cookie 弹窗
  - B&F snapshot 大小
  - Kioxia 日期缺失
- [ ] **去重逻辑验收**：Samsung RSS vs browser 合并、B&F 与 SR 交叉覆盖
- [ ] **md → HTML 转换验证**：品牌色映射、段落样式、微信公众号 inline 完整性
- [ ] **首期端到端**：手动触发一期 → 检查 .md 内容质量 → 检查 .html 渲染 → 微信推送效果

## 未来扩展

- [ ] **Finance channel**：注册 `daily-briefing-finance`、信源定义、模板适配
- [ ] **多 channel 并行调度**：框架层支持同时跑 N 个 channel
