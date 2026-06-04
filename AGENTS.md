# AGENTS.md

This is the Codex operating guide for Stratum. Keep it short and stable; detailed
design belongs in `docs/`, module ownership belongs in `SCOPE.md`, and structured
handoffs belong in `docs/CONTRACT_INVENTORY.yaml`.

## Read Order

1. `README.md` for project purpose and current run commands.
2. `docs/README.md` for the documentation map.
3. The nearest `SCOPE.md` for the module being changed.
4. `docs/ENGINEERING_RULES.md` and `docs/CONTRACT_INVENTORY.yaml` before
   changing any cross-module, stage, runtime, or DB data handoff.
5. `docs/ENGINEERING_RULES.md` before architecture, deployment, or database
   changes.

## Required Rules

- Preserve the current 0.1 baseline while developing toward later 0.x versions.
- Treat contracts as structured data exchanged across dependency boundaries.
- Update `docs/CONTRACT_INVENTORY.yaml` when adding or changing any structured
  handoff, regardless of whether the carrier is JSON, JSONL, SQLite, Python
  records, Markdown, or file artifacts.
- Keep module ownership documented in the relevant `SCOPE.md`.
- Keep root Markdown minimal: `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and
  short project-level files only. Put architecture, specs, rules, and archives
  under `docs/`.
- User requirements may arrive in Chinese or other natural languages. Translate
  those requirements into English when writing engineering docs, code comments,
  config examples, and framework-facing text, unless the non-English text is a
  required product output, domain search term, parser fixture, or localization
  asset.
- Do not commit local secrets, instance config, generated reports, cache files,
  or production runtime data.

## Verification

Run targeted tests for the changed boundary, then run:

```bash
.venv/bin/python -m pytest
```
