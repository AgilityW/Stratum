# temporal - Cross-temporal report execution

## Purpose

`stratum/temporal` defines how Stratum runs reports across time horizons:
`daily`, `weekly`, `monthly`, `quarterly`, `yearly`, and custom report windows.

It is the boundary between CLI orchestration and report-scale behavior:
`orchestrator/pipeline.py` parses config and launches runs, while temporal
profiles describe which stages each time horizon uses and which DB consumption
contract applies.

The package entrypoint `stratum.temporal` is the stable import surface for
timescale profiles, higher-scale execution, and same-scale fresh-evidence
exploring/integration helpers. Runtime callers should prefer it over reaching
into `timescale.py` or `profiles.py` directly unless they intentionally depend
on one implementation module.

## Modules

| Module | Role |
|:---|:---|
| `profiles.py` | Timescale profiles: labels, templates, stage order, DB input contract flags, and synthesis policy profile names. |
| `exploring.py` | Same-scale fresh evidence exploring plan for higher-scale reports, including the report-window freshness threshold. |
| `integration.py` | Integration of same-scale fresh evidence with persisted lower-scale DB memory before synthesis. |
| `timescale.py` | DB-native higher-scale runner for weekly/monthly/quarterly/yearly output. |

Shared window parsing lives in `stratum/contracts/report_window.py` so temporal,
DB service, CLI, and tests use the same definition of standard periods and
custom user-selected date ranges.

## Contracts

### Project-Level Evidence Acquisition

Any run that actively acquires fresh/raw evidence must use the same project
priority order, independent of timescale or domain:

```text
configured watchlist (RSS/direct URL/browser) -> broad search engines (Bocha/Tavily) -> enrich -> verify -> normalize
```

At the code-ownership level, these are three acquisition channels:

- RSS channel: `stratum/sourcing/watchlist/rss_channel.py` and
  `stratum/sourcing/watchlist/rss.py`.
- Fixed URL channel: `stratum/sourcing/watchlist/url_channel.py` with
  `stratum/sourcing/watchlist/direct_fetch.py` and
  `stratum/sourcing/watchlist/browser.py`.
- Broad Search channel: `stratum/sourcing/discovery/` for Bocha/Tavily.

New acquisition algorithms should attach to the channel they optimize. Stage
orchestration should only hand off contracts between channels and downstream
stages; scoring, ranking, provider policy, and validation logic stay inside the
relevant channel or algorithm module.

Domains own source lists and query data; they do not redefine the priority
order. `AcquisitionPolicy` owns the framework order: RSS feeds first, direct
URL fetch next, browser fetch for JS-heavy source-owned pages after that, broad
search engines after watchlist, and database memory for synthesis. Broad
search supplements watchlist coverage gaps and must receive the watchlist-seeded
`raw.json` through `--existing-raw` when watchlist run.
Within a watchlist access tier, `SourcePriorityScorer` may use prior source
health to run healthier sources first. Health never moves broad search ahead of
configured watchlist, and domains do not own this ordering algorithm.
`SourceBudgetPolicy` applies optional `source_registry.budget` limits after
priority scoring, including total source count, per-access caps/floors, and
access/source acquisition costs. `stratum/sourcing/policy.py` owns the budget
algorithm; domain config only supplies budget parameters.

### Daily

Daily uses the full live pipeline:

```text
watchlist -> acquisition -> enrich -> verify -> normalize -> cluster -> edit -> validate -> render -> DB ingest
```

Daily writes raw evidence, normalized articles, events, report artifacts, and
structured DB state. It is the base operational version and must remain runnable
while higher-scale architecture evolves.

### Higher Timescales

Weekly, monthly, quarterly, and yearly use the DB-native temporal runner:

```text
exploring -> DB synthesis -> Markdown -> render
```

Their DB contract is:

- consume all lower-scale structured state inside the concrete report window;
- consume same-scale fresh evidence already written to `articles` with
  `articles.scale = target_scale` and either the standard target period, the
  custom period id, or dates inside the custom window;
- write a structured target-scale report, synthesized events, evidence links,
  lineage, Markdown, HTML/PDF, and a run manifest.

Exploring follows the same project-level evidence acquisition order for
weekly, monthly, quarterly, and yearly reports. It first runs the configured
watchlist, so RSS/direct URL sources seed `raw.json` before broad discovery.
Bocha/Tavily then supplement uncovered query gaps. The resulting pool is
enriched, verified with a window-sized freshness threshold, normalized, and
persisted with `articles.scale = target_scale` and
`articles.run_date = target_period`. Search/API failures are recorded as
`failed_nonblocking`; synthesis still proceeds from already persisted DB state.
If the acquisition stage returns zero raw results because all queries failed, the
fresh stage is also `failed_nonblocking` and does not proceed to downstream
fresh stages for that run.
Exploring owns why and when same-scale fresh evidence is needed. It must
delegate evidence acquisition to the shared sourcing/acquisition path instead of
owning RSS parsing, fixed-URL crawling, provider search, admission scoring,
curation, dedupe, or candidate audit logic.
The integration point is after normalize plus DB persistence and before
DB-native synthesis: synthesis reads lower-scale DB state and same-scale fresh
evidence together, then decides whether fresh evidence confirms, supplements,
challenges, or merely observes each core theme. `Exploring` owns the
same-scale exploring plan and the report-window freshness threshold.
`Integration` emits `IntegrationDecision` so manifests record whether
fresh evidence supplements DB memory, stands alone as a watch item, is excluded
after failure, or leaves the run with insufficient evidence.
Failed or zero-article fresh runs are recorded as nonblocking and are not
included in DB synthesis for that scale.

The synthesis decision layer is shared, but thresholds are scale-specific.
Weekly, monthly, quarterly, and yearly reports all use the same policy concepts:
lower-scale database baseline strength, same-scale fresh evidence quality,
directionality, conflict level, and an integration role such as
baseline-confirmed, baseline-supplemented, fresh-led watch item,
conflict/pending, or insufficient/noise. Temporal profiles declare the
`synthesis_policy_profile` name for each higher scale; the DB synthesis policy
module owns the actual thresholds. Scale-specific render structure can change,
but the decision layer must remain shared.
Thread lifecycle scoring is also shared. Daily event-thread evolution and
higher-scale synthesis ranking both use `ThreadLifecycleScorer`, so active or
escalating stories can be promoted and cooling/dormant/resolved stories can be
demoted without each report scale reimplementing lifecycle rules. Event-thread
evolution also exposes lifecycle diagnostics as structured records for review
and later persistence.

Standard runs keep natural period ids such as `2026-W22`, `2026-05`,
`2026-Q2`, and `2026`. Custom runs use stable ids such as
`custom-2026-05-01_to_2026-07-31`; the report scale still controls the profile
and template, while the window controls what DB records are consumed.

Weekly output is organized as a cross-functional executive briefing. It is not a
daily-report bundle. The Markdown generated from DB-native synthesis must render
the same structured sections written to the report database: Executive Summary,
Core Themes, Signal vs Noise, Judgment Tracker, Fresh Exploration Coverage, Next
Week Watchlist, and source/confidence boundaries. Within each core theme, daily
DB carry-over signals and weekly exploring evidence remain distinct.

## Extension Rule

New report scales or new stage profiles must be added in `profiles.py` first,
then wired into orchestration. This prevents hidden scale-specific branches in
`stratum/orchestrator/pipeline.py` and keeps templates, DB contracts, and tests
aligned.
