# search - compatibility facade for acquisition

## Purpose

`stratum/stages/search` is a narrow compatibility facade preserved for older
imports and entrypoints that still refer to the historical search stage name.

The package entrypoint `stratum.stages.search` is intentionally limited. New
code should import `stratum.stages.acquisition` instead.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | compatibility package surface |
| `search.py` | explicit wrapper over acquisition helpers and CLI |

## Boundaries

### Owns

- Preserve backward-compatible imports during the acquisition/search rename.

### Does Not Own

- Does not define canonical discovery stage behavior.
- Does not grow new public APIs beyond wrapper compatibility.
