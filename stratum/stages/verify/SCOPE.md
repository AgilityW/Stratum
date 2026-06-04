# verify - evidence admission stage boundary

## Purpose

`stratum/stages/verify` decides which enriched records are admissible evidence
for downstream stages.

The package entrypoint `stratum.stages.verify` is the stable import surface for
freshness and evidence-acceptance helpers.

## Modules

| Module | Role |
|:---|:---|
| `__init__.py` | stable package surface for Verify |
| `verify.py` | stage CLI and verification orchestration |
| `freshness_policy.py` | freshness windows and date-confidence policy |
| `evidence_acceptance.py` | duplicate, source-quality, and magnitude gates |

## Boundaries

### Owns

- Apply deterministic freshness and evidence acceptance policy.
- Emit structured verification stats beside `verified.jsonl`.

### Does Not Own

- Does not fetch, enrich, or normalize evidence.
- Does not own editorial block planning.
