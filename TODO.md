# TODO

## ✅ Done — v4.0 Multi-Scale + Source Intelligence

### Content Pipeline
- [x] stratum framework v4.0 — multi-scale pipeline with 8.6 steps
- [x] stratum-storage channel — ja/ko queries + domain.yaml
- [x] locale-router — BCP 47 expansion, engine matching
- [x] source-manager — URL preflight
- [x] verify-engine — date/magnitude/fiscal-year checks
- [x] article-normalizer — ArticleRecord JSONL with artifact_type
- [x] story-cluster-engine — same-day clustering with novelty/confidence
- [x] event-thread-engine — cross-day thread lifecycle
- [x] render-engine — MD → HTML → PDF

### Source Intelligence (decoupled post-processing)
- [x] source-recorder — read content → write source-records.jsonl
- [x] source-profiler — aggregate SourceRecords → SourceProfile
- [x] trial-source-manager — trial pool queue management
- [x] source-graph-engine — entity/term/channel graph evolution

### Multi-Scale
- [x] weekly-briefing — 7-day thread change analysis
- [x] monthly-briefing — TrendTheme synthesis
- [x] quarterly-review — thesis evaluation + calibration
- [x] yearly-review — annual narrative + structural change

### Infrastructure
- [x] config.yaml — ja/ko languages, tavily routing
- [x] trial-pool.json seed
- [x] data directory structure
- [x] install.sh --dev (symlink deployment)
- [x] 7 cron jobs — Collect, Render, Weekly, Monthly, Quarterly, Yearly, Storage Weekly
- [x] Project rename: daily-briefing → Stratum

### Docs
- [x] README.md — architecture overview
- [x] docs/multi-scale-intelligence-architecture.md
- [x] docs/source-intelligence-architecture.md
- [x] MULTI_SCALE_INTELLIGENCE_ARCHITECTURE.md (original spec)

---

## P0 — Test & Validate

- [ ] **End-to-end test: v4.0 pipeline with source-recorder + source-profiler**
  - Run full Steps 0-8.6 and verify all outputs
  - Verify source-records.jsonl has correct roles
  - Verify SourceProfile incremental updates work

- [ ] **ja/ko collection test**
  - Verify Japanese and Korean queries return results
  - Verify trial-pool entries for ja/ko sources accumulate samples

---

## P1 — Source Intelligence Completeness

- [ ] **Passive discover 4-signal extension to source-graph-engine**
  - Citation chains from web_extract
  - Social signal URLs from search results
  - Coverage gap detection from story-clusters source_diversity

- [ ] **Five-dimension evaluation trigger**
  - Wire trial-source-manager evaluation threshold → recommendation output
  - Human approval flow for source promotion

- [ ] **SourceProfile ↔ quarterly-review integration**
  - Thesis backtracking for accuracy scoring
  - Auto-append checkpoints on quarterly review

---

## P2 — Signal Type Expansion

- [ ] Patent search plugin (structured_data)
- [ ] Hiring signal detection (structured_data)
- [ ] Cross-domain search templates (equipment vendor, AI architecture, datacenter)
- [ ] Conference program scanning (non_text)

---

## P3 — Polish

- [ ] Source archive page generation (Markdown → Obsidian)
- [ ] Quarterly source report card
- [ ] Signal type coverage map visualization
- [ ] Split config.yaml: engine registry vs deployment config
