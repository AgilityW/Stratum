# sourcing - External information acquisition capabilities

## Purpose

`stratum/sourcing` owns reusable external information access capabilities and
the policy algorithms that order those capabilities before a stage run.

The acquisition stage decides when to call sourcing capabilities and how to
write stage artifacts. Sourcing modules own how evidence candidates are found,
ranked, routed, budgeted, and normalized before handoff.

## Modules

| Module | Role |
|:---|:---|
| `watchlist/` | configured recurring sources such as RSS feeds, fixed URLs, and browser-backed pages |
| `discovery/` | query-driven external discovery through Bocha, Tavily, and future providers |
| `policy.py` | project-level sourcing priority, source-health ranking, and source budget policy |

## Boundaries

### Owns

- Access external information channels.
- Normalize sourced candidates to shared raw-result-compatible records.
- Rank configured sources within a sourcing tier.
- Apply source budgets and access priority before channel dispatch.

### Does Not Own

- Does not write pipeline stage artifacts. `stages/acquisition` owns `raw.json`.
- Does not verify freshness, truth, or duplicate admission. Verify owns that.
- Does not decide report scale behavior. `stratum/temporal` owns time-horizon flow.

