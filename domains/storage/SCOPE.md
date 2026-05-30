# domains/storage - Storage 领域配置

## Purpose

`domains/storage` 是 Stratum 的 storage industry domain 实例。这里集中放公司、技术词、信源、搜索 query、模板、验证规则和渲染标签。

框架代码必须从这里读取 storage 领域知识，不能在 `stratum/` 中硬编码 storage 公司名、技术名或来源规则。

## Files

| File | Role |
|:---|:---|
| `domain.yaml` | domain metadata, pipeline rules, source registry, source classification, render tags |
| `queries.yaml` | structured Search query templates by intent, dimension, and locale |
| `taxonomy.yaml` | story-tracking controlled vocabulary |
| `templates/daily.html` | domain-level render template |
| `tests/fixtures/` | domain-specific fixture area |

## Boundaries

### 包含

- Storage companies, aliases, source domains, keywords, terms, validation blocklists.
- Collector source registry (`source_registry.sources`).
- Query templates for Search stage. Source-scoped query templates must use
  structured `include_domains`; query text should stay engine-neutral and must
  not embed `site:` operators. Values should be bare hostnames such as
  `digitimes.com`, not URLs or paths.
- Source display aliases under `pipeline.source_aliases`; values may be a
  single domain string or a list of domain patterns when one publisher brand
  spans multiple domains.
- Render template assets that are specific to storage.

### 不包含

- Runtime output. Pipeline output belongs under configured `reports_dir`/`output_dir`.
- Python implementation logic.
- API keys or secrets.
- Prompt override assets. Edit prompts and templates live under
  `stratum/stages/edit/`; storage policy is injected from `domain.yaml`.

## Main Consumers

- `stratum/orchestrator/pipeline.py`
- `stratum/stages/search/search.py`
- `stratum/stages/verify/verify.py`
- `stratum/stages/normalize/normalize.py`
- `stratum/stages/edit/edit.py` via `domain.yaml` policy injection
- `stratum/stages/render/render.py`
- `stratum/collectors/registry.py`
- `stratum/collectors/keywords.py`
- `stratum/db/seed.py`

## Extension Rule

To create a new domain, copy this directory and change configuration values. A new domain should not require code changes in `stratum/`.
