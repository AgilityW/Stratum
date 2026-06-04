# stratum - framework code

## Purpose

`stratum/` is the domain-agnostic framework for Stratum. It owns pipeline
orchestration, acquisition channels, deterministic stages, shared contracts,
SQLite persistence helpers, and reusable subsystems.

All domain knowledge belongs under `domains/{domain}/`.
All structured data exchanged across module, stage, temporal, and DB boundaries
must be represented in the project contract inventory at
`docs/CONTRACT_INVENTORY.yaml`.

## Module Map

| Module | Responsibility |
|:---|:---|
| `sourcing/watchlist/` | RSS and fixed URL acquisition from configured sources |
| `sourcing/discovery/` | Bocha/Tavily query execution, routing, and curation |
| `capabilities/` | stable additive capability layer for future MCP-style and agent-facing reuse |
| `mcp_adapter/` | additive MCP-style tool descriptor and capability-delegation layer |
| `contracts/` | shared JSON schemas and Python dataclasses |
| `db/` | SQLite schema, seeding, ingest, read helpers |
| `evaluation/` | deterministic report-quality benchmark harness |
| `orchestrator/` | top-level pipeline execution |
| `temporal/` | reusable cross-temporal report profiles and higher-scale execution |
| `stages/` | 8 stage CLI scripts |
| `source_trace/` | acquisition observability analyzers and source-funnel diagnostics |
| `signal_bursts/` | higher-level burst detection over SourceTrace and DB context |
| `subsystems/event_thread/` | deterministic thread lifecycle and cross-scale links |
| `subsystems/signal_awareness/` | independent early-signal sensing and collection-readiness planning |
| `subsystems/story_tracking/` | story dataclasses and briefing context assembly |
| `subsystems/monitoring/` | health and coverage monitoring |

## Boundaries

### Owns

- Provide reusable, domain-neutral code.
- Read domain config via explicit file paths or domain ids.
- Expose stage scripts that can run independently from the CLI.
- Keep tests close to pure functions and high-risk integration edges.

### Does Not Own

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
watchlist -> acquisition -> enrich -> verify -> normalize -> cluster -> edit -> validate -> render -> db ingest
```

## Testing

Use:

```bash
make test-unit
make test
```

`make test-unit` is the fast feedback loop for stage/subsystem changes. `make test` includes integration, module, data, and infra tests.
