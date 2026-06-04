# Documentation Map

This directory holds project design, operating rules, deployment notes, and
archives. Root Markdown should stay minimal so Codex can find the right entry
point quickly.

## Active Rules And Specs

| File | Purpose |
|:---|:---|
| `CONTRACT_INVENTORY.yaml` | Machine-readable inventory of structured data handoffs |
| `ENGINEERING_RULES.md` | Baseline stability, contract boundaries, documentation, code cohesion, versioning, and architecture-change rules |
| `CAPABILITY_EVOLUTION.md` | Additive migration path from pipeline-only architecture toward capability, MCP, and future agent layers |
| `MCP_ADAPTER.md` | Transport-neutral MCP-style adapter boundary over the capability layer |
| `DEPLOYMENT.md` | Development/deployment split and production operation |
| `STORAGE_BASELINE.md` | Canonical `0.1` checklist for the current Storage daily production path |
| `SIGNAL_AWARENESS.md` | Independent subsystem design for early signal sensing and dry-run collection-readiness planning |
| `STORAGE_ARCHITECTURE.md` | End-to-end module, stage, and data-flow map for the Storage daily report path |
| `TODO.md` | Current open project-level TODO items, when any exist |
| `ALGORITHM_ARCHITECTURE.md` | Current algorithm ownership map and durable optimization themes |

## Archives

| File | Purpose |
|:---|:---|
| `archive/PROJECT_REVIEW.md` | Historical module-by-module review log |
