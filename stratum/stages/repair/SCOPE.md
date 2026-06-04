# repair

## Purpose

`stratum.stages.repair` owns post-validate briefing repair. It consumes
`validate_report.json` plus the current briefing Markdown and rewrites or drops
invalid items before the final validation pass.

## Public Surface

- CLI: `repair/repair.py`
- Package: `stratum.stages.repair`

## Contracts

- consumes: `briefing-markdown`
- consumes: `validate-report`
- produces: `briefing-markdown`
- produces: `repair-report`

## Boundaries

- Does not generate the original briefing. `stages.edit` owns generation.
- Does not decide correctness criteria. `stages.validate` owns judgment.
- Does not render or publish artifacts. `stages.render` and the orchestrator own delivery.
