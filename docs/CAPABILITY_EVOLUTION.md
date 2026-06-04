# Capability Evolution

This document records how Stratum should evolve toward MCP-style exposure and
future agent orchestration without destabilizing the current production
pipeline.

## Current Position

Stratum is still primarily a deterministic production pipeline. That remains
the correct baseline because daily report generation depends on explicit stage
gates, stable artifact contracts, and predictable failure behavior.

The change direction is therefore additive:

- keep the pipeline as the production path
- add a capability layer for AI-facing reuse
- let future MCP wrappers and agents call capabilities, not stage scripts

## Layer Model

### 1. Production Layer

Current owner: `stratum/orchestrator` plus `stratum/stages`

Purpose:

- run daily and higher-scale report flows
- preserve current Storage baseline behavior
- produce report artifacts and DB writes

### 2. Capability Layer

Current owner: `stratum/capabilities`

Purpose:

- expose stable callable analysis and semantic-read surfaces
- aggregate already-hardened modules behind one import boundary
- serve as the first MCP-ready surface without changing the pipeline contract

### 3. MCP Adapter Layer

Current owner: `stratum/mcp_adapter`

Purpose:

- expose selected capabilities as MCP-style tools without introducing transport
  or server runtime yet
- keep transport concerns outside the production pipeline
- map tool calls to capability-layer functions instead of stage CLIs

### 4. Future MCP Server Layer

Not implemented yet.

Purpose:

- provide actual MCP transport and runtime behavior
- wrap `stratum.mcp_adapter` instead of rebuilding tool metadata
- remain external to production pipeline orchestration

### 5. Future Agent Layer

Not implemented yet.

Purpose:

- decide which capabilities to call
- orchestrate investigation, alerting, topic deep dives, and report-adjacent
  workflows
- leave deterministic production report runs to the pipeline unless a new
  production path is explicitly promoted

## Initial Capability Surface

The first safe capability set is:

- `source_trace`
- `signal_bursts`
- `signal_awareness`
- `discovery_diagnostics`
- `source_expansion`
- `report_context`
- `story_context`
- `evaluate_reports`
- `watch_queries`
- `attach_signal`
- `thread_timeline`
- `thread_keywords`
- `entity_timeline`
- `technology_progress`
- `trend_summary`
- `key_events`
- `key_timeline`
- `judgment_status`
- `due_judgments`
- `active_queries`
- `search_health_db`
- `search_health`
- `report_evidence`
- `report_lineage`
- `cascade_inputs`
- `briefing_context`
- `format_briefing`
- `thread_lifecycle`
- `synthesis_policy`

These were chosen because they are:

- already modular
- already tested
- already useful outside the daily stage chain
- low-risk to expose without changing report production semantics

## MCP-Ready Shape

The first MCP-facing step is not a network server. It is a stable in-process
surface that already looks like future tool transport:

- capability registry: `list_capabilities`, `describe`
- capability invocation envelope: `call`
- MCP adapter surface:
  - `stratum.mcp_adapter.list_tools`
  - `stratum.mcp_adapter.get_tool`
  - `stratum.mcp_adapter.call_tool`
- contract pair:
  - `stratum/contracts/capability_invocation.json`
  - `stratum/contracts/capability_result.json`

That keeps tool discovery and execution additive while the production pipeline
continues to own report delivery.

## Agent-Ready Shape

Agent evolution also starts as an additive layer instead of replacing the
pipeline. The first agent-facing wrapper set is:

- `list_tasks`
- `get_task`
- `run_task`

Current task surfaces:

- `analyze_signal_landscape`
- `lookup_report_context`
- `lookup_story_context`
- `inspect_discovery_diagnostics`
- `inspect_source_expansion`
- `evaluate_report_regression`
- `generate_followup_watch_queries`
- `attach_signal_awareness_to_run`
- `inspect_thread_timeline`
- `inspect_scale_trends`
- `inspect_report_lineage`
- `inspect_report_item_evidence`
- `prepare_scale_synthesis_research`
- `inspect_technology_progress`
- `inspect_due_judgments`
- `inspect_active_search_queries`
- `inspect_search_engine_health`
- `inspect_thread_keyword_events`
- `prepare_briefing_context`
- `inspect_thread_lifecycle`
- `inspect_synthesis_policy`

These tasks are deliberately narrow. They are allowed to compose capabilities,
but they are not allowed to become a parallel production report pipeline.

## Guardrail

Any future MCP or agent integration must prove:

1. the current pipeline remains runnable through `pipeline.py`
2. stage contracts stay unchanged unless explicitly migrated
3. new AI-facing entrypoints depend on `stratum.capabilities` first, not on
   deep orchestrator or stage internals
4. new MCP or agent wrappers use capability or agent-task contracts instead of
   inventing hidden ad hoc payloads

## Current Audit Boundary

As of the current additive rollout, the remaining intentionally internal
entrypoints are mostly:

- production control surfaces such as `stratum.sourcing.discovery.run_search`
  and `stratum.sourcing.watchlist.collect`
- state-mutating thread orchestration such as
  `stratum.subsystems.event_thread.evolve_threads`
- helper functions that only support owner-internal modules

Those stay internal because exposing them directly would blur the boundary
between future AI-facing tooling and the deterministic production pipeline.
