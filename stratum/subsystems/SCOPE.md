# subsystems - reusable deterministic business engines

## Purpose

`stratum/subsystems` groups reusable deterministic engines that sit below the
pipeline orchestration layer and above raw persistence helpers.

The package entrypoint `stratum.subsystems` is the stable import surface for
subsystem families; callers should choose a named subsystem package instead of
reaching into sibling directories by path.

## Module Families

| Module | Role |
|:---|:---|
| `event_thread/` | event lifecycle, cross-temporal linking, and watch-query generation |
| `signal_awareness/` | independent early-signal sensing and collection-readiness planning |
| `monitoring/` | source health, coverage gaps, and engine health diagnostics |
| `story_tracking/` | story contracts and deterministic briefing context assembly |

## Boundaries

### Owns

- Package deterministic business logic that can be reused across stages,
  orchestrator flows, and DB-native synthesis.
- Keep public subsystem boundaries explicit at the package level.

### Does Not Own

- Does not orchestrate stage execution. `stratum/orchestrator` owns that.
- Does not persist long-lived state directly. `stratum/db` owns SQLite reads
  and writes.
- Does not call external search/watchlist providers.
