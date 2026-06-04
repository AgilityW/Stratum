# TODO

Only unfinished work that is currently necessary, concrete, and accepted as a
project-level priority belongs here. General optimization opportunities,
architecture notes, and conditional ideas belong in the relevant design
documents instead.

## Stable Production Core

### Separate production-safe operation from future additive experimentation

- Next action: formalize which entrypoints are baseline production paths and
  which are additive review, attach, dry-run, MCP, or agent-facing paths;
  document the rule and add tests where stable production layers must not
  depend on additive layers.
- Acceptance signal: docs and tests consistently enforce that `pipeline.py` and
  production stage/runtime code remain independent from capability, MCP, and
  future agent orchestration layers.

## Signal Intelligence Layer

### Turn `source_trace`, `signal_bursts`, and `signal_awareness` into an operational signal stack

- Next action: define the production-facing relationship among
  `source_trace`, `signal_bursts`, and `signal_awareness`, including which
  outputs are diagnostic-only, which are operator-facing, and which are allowed
  to shape future collection planning.
- Acceptance signal: one active design path explains the stack end to end,
  contracts stay aligned with that design, and each module has tests proving
  its payloads and package surfaces are stable.

### Validate signal-awareness usefulness on real Storage runs without promoting it to the main pipeline

- Next action: run repeated Storage review attachments with
  `signal_attach.py`, inspect signal outputs and preparation plans, and record
  which recommendations are consistently useful versus noisy.
- Acceptance signal: there is an evidence-backed decision on whether
  `signal_awareness` remains a review-only layer, graduates into a stronger
  preparation subsystem, or needs narrower scope before promotion.

## Capability Platform

### Finish the first production-grade capability inventory

- Next action: audit current high-value internal read/diagnostic/planning
  surfaces and decide which must remain internal versus which should be exposed
  through `stratum.capabilities` as stable callable boundaries.
- Acceptance signal: the capability registry covers the intentionally exposed
  surfaces, docs explain why they are exposed, and no obvious high-value
  research/diagnostic entrypoint remains accidentally hidden in deep modules.

### Define the promotion rule from internal module to capability to MCP tool

- Next action: document the criteria for when a module function can become a
  capability, when a capability can become an MCP-facing tool, and what tests,
  contracts, and naming standards are required at each step.
- Acceptance signal: `CAPABILITY_EVOLUTION.md`, `MCP_ADAPTER.md`, and tests all
  reflect one consistent promotion policy instead of ad hoc additive wrappers.

## Agent Runtime

### Design the first real agent orchestration layer without replacing the pipeline

- Next action: write the boundary for an agent runtime that can call capability
  and MCP-style surfaces for research, diagnostics, context assembly, and
  planning while leaving the current production pipeline as the stable report
  engine.
- Acceptance signal: there is one active design that names the future agent
  runtime owner, entrypoints, allowed capabilities, and non-goals, and it does
  not require the production pipeline to become agent-controlled.

### Define the path from agent-ready tasks to agent-native behavior

- Next action: group current agent tasks into a small number of durable
  workflows such as signal investigation, report context research, and followup
  collection planning; document what higher-level planning behavior is still
  missing.
- Acceptance signal: the project can state clearly which agent behaviors are
  already supported today, which are only task wrappers, and which still need a
  dedicated runtime or planner layer.
