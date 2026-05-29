# briefings — 多尺度简报标准

## Purpose
定义跨时间尺度的简报编辑标准。从日频到年报，每层简报有独立的覆盖面要求、叙事深度和判断粒度。

## Boundaries

### ✅ 做什么
- Daily — 日频雷达：发生了什么
- Weekly — 周度研判：趋势确认还是噪声
- Monthly — 月度复盘：假设验证、判断修正
- Quarterly — 季度审视：哪些结构性变化被低估了
- Yearly — 年度叙事：年度叙事线

每个尺度有独立的 SKILL.md 定义编辑标准。

### ❌ 不做什么
- **不执行管线** — 管线由 orchestrator/pipeline.py 调度
- **不定义模板** — 模板在 domains/{id}/templates/

## Design Principles

### 核心标准
- **Daily**: 全覆盖、不遗漏、结论前置
- **Weekly**: 区分 signal vs noise、标注置信度变化
- **Monthly**: 对上月判断做验证、标注正确/错误/部分正确
- **Quarterly**: 识别被市场低估的结构性变化
- **Yearly**: 构建年度叙事线、评估年初判断准确率

## Dependencies

### 依赖
- Agent (LLM) — 执行编辑
- story-tracking — 提供上下文（carried forward, due judgments, coverage gaps）

### 被依赖
- pipeline（调度）
- domains/{id}/prompts/（注入领域 prompt）
