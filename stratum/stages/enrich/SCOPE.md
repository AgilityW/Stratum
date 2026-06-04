# enrich - publication-date repair stage boundary

## Purpose

`stratum/stages/enrich` repairs missing publication dates before verification.

The package entrypoint `stratum.stages.enrich` is the stable import surface
for date extraction helpers and stage execution.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for date helpers |
| `enrich.py` | stage CLI and enrichment orchestration |

## Boundaries

### Owns

- Apply deterministic date extraction and fallback lineage to raw evidence.
- Preserve `date_source` for downstream freshness and debugging policy.

### Does Not Own

- Does not decide final freshness admission. Verify owns that.
- Does not call discovery providers.
