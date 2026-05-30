# stratum - framework code

## Purpose

`stratum/` is the domain-agnostic framework for Stratum. It owns pipeline orchestration, collectors, deterministic stages, shared contracts, SQLite persistence helpers, and reusable subsystems.

All domain knowledge belongs under `domains/{domain}/`.

## Module Map

| Module | Responsibility |
|:---|:---|
| `collectors/` | direct source acquisition beyond search APIs |
| `contracts/` | shared JSON schemas and Python dataclasses |
| `db/` | SQLite schema, seeding, ingest, read helpers |
| `orchestrator/` | top-level pipeline execution |
| `stages/` | 8 stage CLI scripts |
| `subsystems/search/` | search engine abstraction, execution, curation |
| `subsystems/event-thread/` | deterministic thread lifecycle and cross-scale links |
| `subsystems/story-tracking/` | story dataclasses and briefing context assembly |
| `subsystems/monitoring/` | health and coverage monitoring |

## Boundaries

### 做什么

- Provide reusable, domain-neutral code.
- Read domain config via explicit file paths or domain ids.
- Expose stage scripts that can run independently from the CLI.
- Keep tests close to pure functions and high-risk integration edges.

### 不做什么

- Does not hardcode storage/robot companies, sources, terms, or editorial rules.
- Does not store runtime data inside the repo by default.
- Does not hide external side effects inside pure subsystems.

## Runtime Shape

The main entry point is:

```bash
python stratum/orchestrator/pipeline.py --domain storage --date YYYY-MM-DD
```

The standard stage flow is:

```text
search -> collect -> enrich -> verify -> normalize -> cluster -> edit -> validate -> render -> db ingest
```

## Testing

Use:

```bash
make test-unit
make test
```

`make test-unit` is the fast feedback loop for stage/subsystem changes. `make test` includes integration, module, data, and infra tests.
