# Signal Awareness

Signal Awareness is an independent subsystem that detects early signal shifts
before Stratum expands acquisition scope. It is intentionally
not wired into the main pipeline yet. The current deliverable is a stable,
tested, documented boundary that can be dry-run safely before any future
integration decision.

## Why This Exists

The design target is to catch event-driven coverage shifts earlier. The failure
mode is not usually "the system never found the news"; it is "the system
searched too late, after conference coverage had already started to spread."

The subsystem therefore watches for:

- topic-level count anomalies versus recent history
- anchor-backed signal mentions inside a lead window
- repeated event-like clusters not yet mapped to known anchors
- decay signals strong enough to archive an active preparation profile

## Current Boundary

The canonical code lives in
`stratum/subsystems/signal_awareness/`.

It accepts:

- current article-like records
- caller-provided topic rules
- historical snapshot records
- optional anchor registry records
- optional active-signal state

It emits:

- `signal_awareness.json`
- `signal_plan.json`

It does not:

- mutate `domain.yaml` or query files
- patch source registries
- write SQLite state
- integrate with `orchestrator/pipeline.py`

## Detection Model

### 1. Topic Baseline

Current records are bucketed into caller-defined topics. Each topic count is
compared against historical snapshots using a mean/std baseline and z-score.

### 2. Anchor Signals

Known signal anchors are matched by alias, location, year token, event
clues such as `booth`, `keynote`, `preview`, and source/company diversity.
Anchors can trigger preparation in two ways:

- forced activation inside the configured lead window
- confirmed activation when both anchor evidence and topic burst strength are high

### 3. Unanchored Event Clusters

Records with event-like language but no anchor match are grouped into compact
clusters. These are surfaced as investigatory signals rather than automatic
preparation triggers.

### 4. Action Planning

The preparation plan stays dry-run and side-effect free. It proposes:

- `activate`
- `maintain`
- `archive`
- `observe`

For active actions it also carries:

- temporary source additions
- direct-fetch targets
- query injections
- elevated daily-target ranges

## Future Integration Path

If this subsystem proves stable in dry runs, a later phase can let the
orchestrator consume `signal_plan.json` and decide how to map it
into runtime source/query expansion. That integration is explicitly out of
scope for the current change.

## Daily Review Path

The current safe way to connect this subsystem with the daily path is through
the review entrypoint
`stratum/orchestrator/signal_attach.py`.

Its behavior is:

1. Run or reuse a normal daily report run unchanged.
2. Read the acquisition-side artifacts from that run directory.
3. Compute `signal_awareness.json` and `signal_plan.json`.
4. Write `signal_review.md` as an operator-facing summary.
5. Append shared snapshot history for later baseline comparisons.

This means the subsystem is connected to the daily workflow for testing, while
the main pipeline contract remains unchanged.
