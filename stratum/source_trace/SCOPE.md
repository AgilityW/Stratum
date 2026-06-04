# SourceTrace Scope

SourceTrace is the evidence observability layer for source acquisition. It does
not change the production pipeline input. It consumes acquisition sidecars,
pipeline artifacts, and optional DB read-model records to explain what sources
saw, what source admission kept, what downstream stages consumed, and what
ultimately affected reports or long-lived database memory.

The package entrypoint `stratum.source_trace` is the stable import surface for
SourceTrace analyzers and runner helpers.

## Responsibilities

- Analyze the source funnel from candidate discovery to downstream consumption:
  `observed -> candidate -> admitted -> consumed -> verified -> normalized -> reported -> persisted`.
- Score source quality using admission, rejection, consumption, verification,
  novelty, and report-impact signals.
- Mine rejected candidates that later match important DB events, report items,
  threads, or other durable records.
- Analyze canonical URL provenance, duplicate acquisition paths, and dedupe loss.
- Attribute source evidence to events, threads, report items, and judgments when
  DB read models are provided by callers.
- Build source temporal profiles for freshness, dated-rate, delay, and decay.
- Generate source-budget, admission-policy, provenance, and extraction
  recommendations from analyzer outputs.

## Non-Responsibilities

- Does not run RSS, URL, browser, Bocha, Tavily, or any other acquisition method.
- Does not mutate `raw.json`, report artifacts, source registries, or DB state.
- Does not own pipeline stage orchestration.
- Does not call LLMs, render reports, or write production report text.
- Does not decide final report inclusion. It only explains and recommends.

## Inputs

SourceTrace analyzers should accept plain JSON-friendly records, usually loaded
from:

| Input | Meaning |
|:---|:---|
| `watchlist_observations.jsonl` | RSS, direct URL, and browser records after source fetch/parse, before watchlist admission scoring. |
| `discovery_observations.jsonl` | Bocha/Tavily records after provider response normalization, before discovery curation scoring, ranking, and pruning. |
| `watchlist_candidates.jsonl` | Watchlist candidates seen by RSS, direct URL, and browser sources, including accepted, weak-signal, and rejected records with admission scores and reasons. |
| `watchlist_results.json` | Watchlist records admitted before broad discovery merge and raw-pool dedupe. |
| `raw.json` | The downstream raw evidence pool consumed by enrich, verify, normalize, and later stages. |
| DB read-model records | Optional records such as articles, events, threads, report items, evidence links, judgments, and persisted article metadata. |
| `discovery_candidates.jsonl` | Optional broad discovery candidates with curator selected/rejected status. |

## Evidence Layers

SourceTrace separates source acquisition observability into four layers:

| Layer | Files | Meaning |
|:---|:---|:---|
| Observation | `watchlist_observations.jsonl`, `discovery_observations.jsonl` | Structured records seen by source fetchers or search providers before admission or curation policy. |
| Candidate | `watchlist_candidates.jsonl`, `discovery_candidates.jsonl` | Observation records after policy judgment, with status, score, selected/accepted flags, and reason. |
| Result | `watchlist_results.json` | Watchlist records admitted by source admission before raw-pool merge and dedupe. |
| Consumed | `raw.json` | Deduped production evidence pool consumed by downstream pipeline stages. |

## Outputs

The runner layer should write SourceTrace outputs under the run's data directory,
for example:

```text
{reports_dir}/{domain}/data/{date}/source_trace/
```

| Output File | Primary Inputs | Purpose |
|:---|:---|:---|
| `source_trace_summary.json` | All analyzer outputs | High-level SourceTrace overview: funnel totals, source counts, major quality/rejection/dedupe/report-impact signals, and recommendation counts. |
| `source_quality.json` | Funnel metrics, report impact, novelty signals | Rank sources by quality, noise, effective yield, downstream conversion, and impact. |
| `missed_signals.json` | Rejected watchlist candidates plus later DB/report records | Identify candidates rejected by admission that later matched important events, threads, report items, or durable records. |
| `dedupe_loss.json` | `watchlist_results.json`, `raw.json`, optional `discovery_candidates.jsonl` | Explain canonical URL overlap, multi-path acquisition, duplicate loss, and source/search overlap. |
| `thread_attribution.json` | Articles, events, threads | Attribute source evidence to story threads through article and event relationships. |
| `report_impact.json` | Report items, evidence links, articles | Measure which sources support report items, strong evidence links, judgments, or high-value report sections. |
| `temporal_profile.json` | Candidates, results, raw records, optional article records | Build source freshness profiles, dated-rate, average age, stale/fresh counts, and temporal tier. |
| `policy_recommendations.json` | Source quality, missed signals, provenance, temporal profile | Recommend source-budget changes, admission tuning, date extraction improvements, and provenance preservation. |
| `observation_health.json` | `watchlist_observations.jsonl`, `discovery_observations.jsonl`, candidate files | Diagnose parser/provider health, dated-rate, duplicate observation rate, boilerplate titles, and observation-to-candidate conversion. |
| `issues.json` | All analyzer outputs | Machine-readable issue list for parser, admission, provenance, quality, and missed-signal problems. |
| `source_trace_charts.md` | Summary, source quality, observation health | Mermaid charts for quick visual review of the evidence funnel, source quality, and observation health. |

## Module Map

| Module | Scope |
|:---|:---|
| `funnel.py` | Source conversion metrics across acquisition and downstream stages. |
| `quality.py` | Source quality scoring from funnel, novelty, and impact records. |
| `missed_signals.py` | Rejected-candidate mining against later durable records. |
| `provenance.py` | Canonical URL acquisition-path and dedupe analysis. |
| `thread_attribution.py` | Source-to-event-to-thread attribution. |
| `report_impact.py` | Source contribution to report items and evidence links. |
| `temporal_profile.py` | Source freshness and dated-rate profiling. |
| `recommendations.py` | Policy recommendations derived from analyzer outputs. |
| `observations.py` | Observation-layer constants, keys, and summaries before admission or curation. |
| `contracts.py` | Stable SourceTrace input/output filenames and lightweight payload validation. |
| `loader.py` | JSON/JSONL loading, malformed-row isolation, and record normalization. |
| `runner.py` | SourceTrace orchestration from input artifacts to output files. |
| `summary.py` | Top-level SourceTrace run summary assembly. |
| `conversion.py` | Cross-layer lifecycle joins from observation to DB persistence. |
| `observation_health.py` | Parser/provider health diagnostics for observation records. |
| `issues.py` | Actionable issue mining from analyzer outputs. |
| `db_context.py` | Expected DB read-model context shape for callers. |
| `export.py` | Optional CSV exports for human review. |
| `charts.py` | Mermaid chart rendering for visual SourceTrace review. |

## Design Rules

- Keep analyzers pure: accept Python records, return JSON-friendly dict/list
  payloads, and avoid filesystem or DB side effects inside analyzer modules.
- Keep runner/orchestration separate from scoring and attribution logic.
- Preserve `raw.json` as the downstream evidence pool. SourceTrace output is an
  observability side path, not production evidence input.
- Prefer stable, explicit output filenames because these files are intended for
  dashboards, notebooks, CLI inspection, and future DB ingestion.
- Malformed JSONL rows must stay observable: loader isolation is allowed, but
  dropped rows need to surface through run outputs instead of disappearing as
  test-only knowledge.
