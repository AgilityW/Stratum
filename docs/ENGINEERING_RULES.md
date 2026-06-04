# Engineering Rules

This document holds project-level rules only. Detailed design belongs in module
`SCOPE.md` files, structured handoffs belong in `CONTRACT_INVENTORY.yaml`, and
historical reasoning belongs in `docs/archive/`.

## Project Laws

0. **Preserve the working intelligence pipeline.** No improvement may break the
   current validated Storage reporting baseline.
1. **Keep ownership singular.** Domain knowledge, orchestration, algorithms,
   contracts, persistence, rendering, and documentation each belong in their
   owning boundary.
2. **Make handoffs explicit.** Data crossing a module, stage, runtime, temporal,
   or DB boundary must have a named contract, owner, consumers, and tests.
3. **Delegate by responsibility.** Orchestrators and stages coordinate; sourcing
   acquires; algorithms decide; DB modules persist and read; renderers deliver.
4. **Keep evidence auditable.** Acquisition, scoring, curation, dedupe, and
   rejection decisions must leave data that can be inspected and improved.
5. **Let documentation earn its place.** Document only durable boundaries,
   contracts, workflows, decisions, and rules future contributors must rely on.

## Operating Rules

**Baseline.** Preserve the current `0.1` working path while later 0.x work is
introduced. Replace a working path only after the replacement is tested,
documented, and promoted as the new baseline.

**Ownership.** One concept gets one canonical home and one canonical spelling.
Compatibility aliases need an explicit reason and must not become permanent
boundaries.

**Stages And Algorithms.** Algorithms must not grow directly inside pipeline
stages. A stage owns orchestration and contract handoff; algorithm modules own
scoring, ranking, policy decisions, matching, calibration, and validation.

**Contracts.** A contract is structured data exchanged across a dependency
boundary. The carrier can be JSON, JSONL, SQLite records, Python records, file
artifacts, or temporal profiles. Add or change a structured handoff only with a
named owner, consumers, invariants, tests, and an updated
`docs/CONTRACT_INVENTORY.yaml`.

**Database.** DB modules own persistence and semantic read surfaces. Other
modules consume DB services, not table internals. Schema changes use versioned
migrations.

**Naming.** Importable Python source paths must use lowercase `snake_case`. Do
not use hyphens in importable Python paths. Project file stems should stay
short and normally use at most one underscore. Public APIs must avoid
redundant package words and suffixes such as `*_capability` when the package
already provides that context.

**Privacy.** Repository-tracked docs, examples, scripts, and tests must not
contain real user home paths, personal vault locations, machine-specific
workspace roots, or secret-like example values. Use environment variables,
generic placeholders, or neutral `$HOME/stratum/...` examples instead.

**Documentation.** Documentation must be necessary, not merely additive. Do not
update docs just because a discussion happened. Avoid low-value notes that make
documents larger without making the project easier to understand or maintain.

**Language.** Engineering docs, code comments, config examples, and
framework-facing text are English-first unless the non-English text is required
product output, domain search data, parser fixture, localization, or archive
content.

**TODO.** `docs/TODO.md` must only contain unfinished items. Each item needs a
concrete next action and an acceptance signal.

**Versioning.** `1.0.0` is reserved for the Storage domain after daily, weekly,
monthly, quarterly, and yearly reports have run through and been validated with
one full year of real data. The current base version is `0.1.0`; deployments
are key releases, with the next production deployment on this line becoming
`0.1.1`.
