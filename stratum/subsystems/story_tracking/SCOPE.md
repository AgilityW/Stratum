# story_tracking - briefing context and story contracts

## Purpose

`stratum/subsystems/story_tracking` defines structured story objects and deterministic context assembly for the next briefing run.

In the current project shape, persistence is SQLite-backed through `stratum/db`; this subsystem focuses on contracts, repository interfaces, and pure context selection/formatting logic.

The package entrypoint `stratum.subsystems.story_tracking` is the stable import
surface for story contracts and context-generation helpers.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for contracts and context helpers |
| `story_contracts.py` | `EventRecord`, `CausalEdge`, `Judgment`, `BriefingContext`, enums, JSON helpers |
| `context_policy.py` | `ContextSelectionPolicy` for carried-forward, due-judgment, coverage-gap, active-chain, and unassigned-event selection |
| `briefing_context.py` | `BriefingContext` assembly, prompt formatting, and compatibility helper wrappers |
| `repository.py` | abstract repository interfaces |

## Boundaries

### Owns

- Define story/event/judgment dataclasses and enum values.
- Select story context through `ContextSelectionPolicy`, including ranking and
  backfill-safe filtering for carried-forward events, due judgments, coverage
  gaps, active causal chains, and unassigned events.
- Generate `BriefingContext` from events, causal edges, and judgments.
- Format briefing context for prompt consumption.
- Keep repository interfaces explicit for future persistence adapters.

### Does Not Own

- Does not write SQLite directly. `stratum/db` owns DB writes.
- Does not call LLMs.
- Does not fetch articles.
- Does not run pipeline stages.
- Does not define domain-specific taxonomy.

## Main Flow

`orchestrator/pipeline.py` reads SQLite rows, maps them into compatible simple objects, then calls:

```python
generate_context(domain_id, "daily", run_date, events, edges, judgments)
```

The resulting context is written to `story_context.json` for the Edit stage.
Callers can also pass `coverage_entities=[...]` when a domain has a required
coverage universe. Entities in that list with no prior events are surfaced as
`never_seen` coverage gaps, while the default call remains event-history based.
The orchestrator currently passes `companies[].id` from `domain.yaml` for this
purpose.

Context selection is intentionally conservative:

- carried-forward events include `emerging`, `active`, and `cooling` statuses;
  resolved/archived events are not carried forward.
- carried-forward scale references must be inside the context window, from
  `target_date - lookback_days` through `target_date`; historical backfills do
  not see future briefing appearances.
- carried-forward events sort by priority first, then by most recent relevant
  briefing appearance, so prompt space favors the freshest active stories
  within each priority tier.
- due judgments are filtered by `made_at <= target_date` before their
  verification deadline is evaluated, so historical backfills do not see
  hypotheses that had not been made yet. The actual due-window decision is
  delegated to `stratum.db.judgment_lifecycle.JudgmentLifecyclePolicy`, keeping
  prompt context and DB cascade reads aligned on pending/deferred/completed
  judgment semantics and expected-verification date parsing.
- coverage-gap detection also ignores events whose `last_updated` is after the
  target date, so historical backfills do not let future mentions suppress
  missing-coverage prompts.
- coverage-gap detection can include configured entity candidates that have
  never appeared in events, so domain taxonomies/watchlists can drive proactive
  coverage prompts.
- active causal chains include unverified edges only while at least one endpoint
  is still `emerging`, `active`, `cooling`, or unknown, and edges created after
  the target date are ignored for historical backfills.
- unassigned events are also bounded to `target_date`, so future events do not
  leak into a backfilled Edit prompt.
- unassigned events are listed by ID in the prompt context, not only counted, so
  the Edit stage can decide whether to mention, merge, or ignore them.

## Contracts

Key dataclasses:

- `EventRecord`
- `CausalEdge`
- `Judgment`
- `TimelineEntry`
- `ScaleRef`
- `BriefingContext`

JSON helper functions:

- `to_jsonl_line(obj)`
- `from_jsonl_line(line, cls)`

`from_jsonl_line()` rebuilds nested dataclasses and enums, including
`EventRecord.timeline`, `EventRecord.scale_refs`, `TimelineEntry.update_type`,
and `ScaleRef.prominence`. These helpers remain useful for tests, migrations,
and future adapters even though the active runtime persistence is SQLite.

## Testing

- `test_contracts.py` validates dataclass creation, enum values, and JSONL
  serialization/deserialization round trips.
- `test_briefing.py` validates carried-forward events, due judgments,
  shared judgment lifecycle policy consumption, coverage gaps, causal chains,
  target-date backfill boundaries, unassigned events, and prompt formatting.
