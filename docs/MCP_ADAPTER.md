# MCP Adapter

This document defines the additive MCP-style adapter boundary for Stratum.

## Position

`stratum/mcp_adapter` is not a server. It is a transport-neutral adapter layer
that exposes tool descriptors and delegates tool calls to
`stratum.capabilities`.

That keeps the current production pipeline unchanged while making future MCP
packaging straightforward.

## Current Surface

Stable package entrypoint:

- `stratum.mcp_adapter`

Stable functions:

- `list_tools`
- `get_tool`
- `call_tool`

## Design Rules

- Tool descriptors must map to capability-layer names, not to stage scripts.
- Tool invocation must delegate through `call`.
- Adapter payloads are additive and must not replace underlying business
  contracts such as SourceTrace, Signal Bursts, Signal Awareness, or DB read
  payloads.
- A future real MCP server should wrap this adapter package before reaching
  deeper framework code.

## Current Tool Families

- Analysis tools:
  - `source_trace_run`
  - `signal_bursts_run`
  - `signal_awareness_run`
- Collection diagnostics tools:
  - `discovery_diagnostics_build`
  - `source_expansion_evaluate`
- Semantic read tools:
  - `report_context_get`
  - `story_context_get`
  - `thread_timeline_get`
  - `thread_keyword_events_get`
  - `entity_timeline_get`
  - `technology_progress_get`
  - `trend_summary_get`
  - `key_events_get`
  - `key_timeline_get`
  - `judgment_status_get`
  - `due_judgments_get`
  - `active_search_queries_load`
  - `search_engine_health_load`
  - `search_engine_health_get`
  - `report_item_evidence_get`
  - `report_lineage_trace`
- Research context tools:
  - `briefing_context_generate`
  - `thread_lifecycle_diagnostics`
- Evaluation tools:
  - `report_evaluation_run`
- Planning tools:
  - `watch_queries_generate`
- Synthesis-read tools:
  - `cascade_inputs_get`
  - `synthesis_policy_config_get`
- Domain config tools:
  - `signal_awareness_config_get`
- Dry-run tools:
  - `signal_aware_daily_attach`

## Guardrail

This adapter is allowed to grow only if all of the following remain true:

1. `stratum/orchestrator/pipeline.py` stays the production path.
2. Existing stage and subsystem contracts stay unchanged unless explicitly
   migrated.
3. New tool surfaces are backed by `stratum.capabilities` instead of deep
   orchestrator or stage internals.
