# edit - editorial synthesis stage boundary

## Purpose

`stratum/stages/edit` is the LLM-assisted editorial stage that turns clustered
evidence and story context into the final briefing markdown and structured
trace artifacts.

The package remains centered on `edit.py` orchestration, while planner,
renderer, policy, and repair modules keep deterministic responsibilities
separate.

## Modules

| Module | Role |
|:---|:---|
| `__init__.py` | package marker for package-relative imports |
| `edit.py` | stage CLI and orchestration boundary |
| `boilerplate.py` | compatibility wrapper over shared stage boilerplate helpers |
| `planner.py`, `planning_policy.py` | deterministic evidence/category planning |
| `renderer.py`, `output_policy.py` | markdown assembly and output gating |
| `source_repair.py`, `source_alignment.py`, `block_policy.py`, `profile_policy.py`, `structured_output.py` | deterministic repair, fallback, and structured-output normalization |

## Boundaries

### Owns

- Orchestrate prompts, planning, block edits, polish, trace artifacts, and
  structured thread output.
- Keep deterministic editorial policy logic outside the stage body.

### Does Not Own

- Does not verify evidence freshness or source validity.
- Does not own higher-scale DB-native synthesis.
