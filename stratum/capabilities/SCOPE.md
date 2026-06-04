# Capabilities Scope

`stratum/capabilities` is the stable capability layer intended for future
MCP-style exposure and agent-facing orchestration.

It does not replace the current daily pipeline. Instead, it aggregates a small
set of already-stable deterministic and semantic surfaces behind explicit
package entrypoints so new AI-facing interfaces do not need to call stage
scripts, orchestrator helpers, or deep module paths directly.

The package entrypoint `stratum.capabilities` is the stable import surface for
these wrappers.

## Responsibilities

- Provide import-stable wrappers around existing analysis and semantic-read
  capabilities.
- Preserve the current pipeline contract by keeping this layer additive.
- Collect the first MCP-ready and agent-ready surfaces in one package.
- Keep capability wrappers thin; underlying modules remain the owners of the
  actual algorithms and contracts.
- Provide a registry and invocation envelope that future MCP adapters can wrap
  without reaching through stage CLIs or orchestrator internals.
- Provide narrow agent-task wrappers that compose existing capabilities without
  becoming a second production pipeline.

## Non-Responsibilities

- Does not own pipeline orchestration.
- Does not replace stage scripts or daily report execution.
- Does not reimplement source_trace, signal_bursts, signal_awareness, or DB
  service algorithms.
- Does not expose transport protocols by itself. MCP adapters can wrap this
  layer later.
- Does not decide or modify the production stage order.

## Initial Capability Families

| Capability | Canonical Owner | Purpose |
|:---|:---|:---|
| `source_trace` | `stratum.source_trace` | Run acquisition observability analysis from a run directory. |
| `signal_bursts` | `stratum.signal_bursts` | Run burst detection from explicit records or a run directory. |
| `signal_awareness` | `stratum.subsystems.signal_awareness` | Run early signal sensing and collection-readiness planning. |
| `discovery_diagnostics` | `stratum.sourcing.discovery` | Build deterministic discovery diagnostics from explicit search payloads. |
| `source_expansion` | `stratum.sourcing.watchlist.source_expansion` | Evaluate source-expansion recommendations from one completed watchlist run. |
| `report_context` | `stratum.db.service` | Return semantic report context for downstream consumers. |
| `story_context` | `stratum.db.service` | Return daily story-context records for follow-up use. |
| `awareness_config` | `domains/{domain}/signal_awareness.yaml` | Load domain-owned signal-awareness config without reaching through orchestrator code. |
| `evaluate_reports` | `stratum.evaluation` | Run deterministic report regression evaluation from a case file. |
| `watch_queries` | `stratum.subsystems.event_thread` | Generate next-run watch queries from thread state. |
| `attach_signal` | `stratum.orchestrator.signal_attach` | Attach signal-awareness review outputs to an existing daily run. |
| `thread_timeline` | `stratum.db.service` | Return one thread timeline for research and diagnostics. |
| `thread_keywords` | `stratum.db.service` | Return active event rows used for thread keyword feedback export. |
| `entity_timeline` | `stratum.db.service` | Return one entity timeline for research and diagnostics. |
| `technology_progress` | `stratum.db.service` | Return technology progress across companies and periods. |
| `trend_summary` | `stratum.db.service` | Return scale-level trend summary for a date window. |
| `key_events` | `stratum.db.service` | Return priority-ranked key events for a date window. |
| `key_timeline` | `stratum.db.service` | Return key timeline milestones for a date window. |
| `judgment_status` | `stratum.db.service` | Return grouped judgment verification status for a date window. |
| `due_judgments` | `stratum.db.service` | Return judgments still pending verification for follow-up review. |
| `active_queries` | `stratum.db.service` | Load active search queries from a SQLite database path. |
| `search_health_db` | `stratum.db.service` | Load latest persisted search-engine health from a SQLite database path. |
| `search_health` | `stratum.db.service` | Load latest persisted search-engine health from a domain DB. |
| `report_evidence` | `stratum.db.service` | Return evidence links for one report item. |
| `report_lineage` | `stratum.db.service` | Trace one report back to lower-scale evidence and lineage links. |
| `cascade_inputs` | `stratum.db.service` | Return higher-scale synthesis input bundle without running synthesis. |
| `briefing_context` | `stratum.subsystems.story_tracking` | Generate structured story-tracking briefing context for research workflows. |
| `format_briefing` | `stratum.subsystems.story_tracking` | Format briefing context into a prompt-ready text block. |
| `thread_lifecycle` | `stratum.subsystems.event_thread` | Return lifecycle diagnostics for current thread state. |
| `synthesis_policy` | `stratum.db.synthesis` | Return configured higher-scale synthesis thresholds for diagnostics. |
| `list_capabilities` / `describe` | `stratum.capabilities.registry` | Describe MCP-ready capability surfaces without invoking them. |
| `call` | `stratum.capabilities.runtime` | Run one named capability through a stable invocation/result envelope. |
| `list_tasks` / `get_task` / `run_task` | `stratum.capabilities.agent_tasks` | Compose capability calls behind a small set of future agent-facing task surfaces. |

## Design Rules

- Keep wrappers thin and deterministic.
- Keep all domain knowledge in `domains/{domain}/`.
- Keep the production pipeline usable exactly as it is today.
- Prefer wrappers around package surfaces, not stage CLI subprocesses.
- Future MCP servers or agent runtimes should wrap this layer before touching
  orchestrator or stages.
- Capability invocation and agent-task envelopes are additive contracts only;
  they must not replace existing stage or subsystem output contracts.
- Collection-control entrypoints such as `run_search`, `watchlist.collect`, or
  `evolve_threads` remain owned by production modules unless they can be
  exposed without creating a second orchestration path.
