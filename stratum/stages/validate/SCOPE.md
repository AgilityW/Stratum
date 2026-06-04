# validate - output contract stage boundary

## Purpose

`stratum/stages/validate` performs deterministic validation over briefing
markdown and optional structured output artifacts.

The package entrypoint `stratum.stages.validate` is the stable import surface
for parsing and validation helpers.

## Modules

| Module | Role |
|:---|:---|
| `__init__.py` | stable package surface for validation helpers |
| `validate.py` | stage CLI and validation orchestration |
| `source_support.py`, `claim_validator.py` | deterministic support and overclaim policy |

## Boundaries

### Owns

- Validate cited sources, cited dates, and structured output contracts.
- Keep support and overclaim policy logic outside the stage body.
- Reuse shared `stratum.stages.boilerplate` helpers for deterministic
  boilerplate leakage checks instead of reimplementing source-marker rules.

### Does Not Own

- Does not generate briefing content.
- Does not persist final report bundles.
