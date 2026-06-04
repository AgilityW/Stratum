# domains/storage - Storage domain configuration

## Purpose

`domains/storage` is Stratum's storage-industry domain instance. It centralizes
companies, technical terms, sources, Search queries, templates, validation
rules, and render labels.

Framework code must read storage domain knowledge from this directory. It must
not hardcode storage companies, technical terms, or source rules in `stratum/`.

## Files

| File | Role |
|:---|:---|
| `domain.yaml` | domain metadata, pipeline rules, source registry, source classification, render tags |
| `queries.yaml` | structured Search query templates by intent, dimension, and locale |
| `taxonomy.yaml` | story-tracking controlled vocabulary |
| `templates/daily.html` | domain-level render template |
| `tests/fixtures/` | domain-specific fixture area |

## Boundaries

### Owns

- Storage companies, aliases, source domains, keywords, terms, validation blocklists.
- Watchlist source registry (`source_registry.sources`).
- Query templates for Search stage. Source-scoped query templates must use
  structured `include_domains`; query text should stay engine-neutral and must
  not embed `site:` operators. Values should be bare hostnames such as
  `digitimes.com`, not URLs or paths.
- Source display aliases under `pipeline.source_aliases`; values may be a
  single domain string or a list of domain patterns when one publisher brand
  spans multiple domains.
- Source-specific boilerplate cleanup rules under `pipeline.boilerplate`.
  Raw search data must remain untouched; these rules only shape the evidence
  text passed into Edit and the final artifact quality gate.
- Render template assets that are specific to storage.

### Does Not Own

- Runtime output. Pipeline output belongs under configured `reports_dir`/`output_dir`.
- Python implementation logic.
- API keys or secrets.
- Prompt override assets. Edit prompts and templates live under
  `stratum/stages/edit/`; storage policy is injected from `domain.yaml`.

## Main Consumers

- `stratum/orchestrator/pipeline.py`
- `stratum/stages/acquisition/search.py`
- `stratum/stages/verify/verify.py`
- `stratum/stages/normalize/normalize.py`
- `stratum/stages/edit/edit.py` via `domain.yaml` policy injection
- `stratum/stages/render/render.py`
- `stratum/sourcing/watchlist/registry.py`
- `stratum/sourcing/watchlist/keywords.py`
- `stratum/db/seed.py`

## Extension Rule

To create a new domain, copy this directory and change configuration values. A new domain should not require code changes in `stratum/`.
