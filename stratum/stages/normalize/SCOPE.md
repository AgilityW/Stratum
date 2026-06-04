# normalize - article-shaping stage boundary

## Purpose

`stratum/stages/normalize` converts verified search-like records into stable
article records for clustering, editing, and DB ingest.

The package entrypoint `stratum.stages.normalize` is the stable import surface
for normalization helpers, extraction components, and thread matching.

## Modules

| Module | Role |
|:---|:---|
| `__init__.py` | stable package surface for Normalize |
| `normalize.py` | stage CLI and article-record assembly |
| `extractors.py` | entity, term, title-pattern, and numeric-claim extraction |
| `thread_matcher.py` | thread keyword matching and diagnostics |

## Boundaries

### Owns

- Assemble normalized article records from verified evidence.
- Keep extraction algorithms and thread matching reusable outside stage CLI.

### Does Not Own

- Does not group articles into clusters.
- Does not persist article records directly.
