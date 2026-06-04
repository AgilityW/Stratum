# acquisition - broad discovery stage boundary

## Purpose

`stratum/stages/acquisition` wraps `stratum.sourcing.discovery` into the stage
contract that produces `raw.json` and discovery diagnostics.

The package entrypoint `stratum.stages.acquisition` is the stable import
surface for query loading, raw-result merge helpers, and acquisition CLI
execution.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for acquisition helpers |
| `acquisition.py` | stage CLI, query resolution, discovery execution, and sidecar writes |

## Boundaries

### Owns

- Load canonical daily discovery queries from SQLite or `queries.yaml`.
- Merge watchlist-seeded raw evidence with discovery supplement results.
- Write raw candidate and observation sidecars beside `raw.json`.

### Does Not Own

- Does not implement provider routing or curation algorithms.
- Does not verify or normalize evidence.
