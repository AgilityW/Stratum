# Signal Bursts Scope

Signal Bursts detects emerging or intensifying evidence signals by consuming
SourceTrace outputs, caller-provided terms, and optional DB read-model context.
It is a higher-level analysis layer beside SourceTrace, not a replacement for
SourceTrace and not part of source acquisition.

The package entrypoint `stratum.signal_bursts` is the stable import surface for
burst detection and term normalization helpers.

## Responsibilities

- Use term telemetry as the first stage of signal burst detection.
- Count where caller-provided terms appear across SourceTrace observations,
  candidates, results, raw evidence, and optional DB records.
- Build co-occurrence relationships between terms that appear in the same
  evidence records.
- Group related terms into signal candidates.
- Score signal bursts using volume, freshness, source diversity, source quality,
  official-source support, novelty versus baseline, DB/thread relevance, report
  impact, duplicate penalty, and observation-health penalty.
- Link bursts to existing DB events, threads, judgments, and report items when
  DB context is provided.
- Produce machine-readable outputs that can guide daily/weekly/monthly report
  synthesis, query tuning, source-budget tuning, and admission-policy review.

## Non-Responsibilities

- Does not run RSS, URL, browser, Bocha, Tavily, or any search provider.
- Does not own or generate the authoritative keyword/term list.
- Does not mutate `raw.json`, SourceTrace outputs, source registries, query
  files, or DB state.
- Does not replace SourceTrace analyzers. It consumes SourceTrace outputs and
  adds burst-level interpretation.
- Does not decide final report inclusion. It produces evidence-backed signal
  candidates and confidence diagnostics.

## Inputs

| Input | Owner | Meaning |
|:---|:---|:---|
| `terms` | caller/domain/query/thread policy | Terms and aliases to measure. Signal Bursts consumes this list but does not own it. |
| SourceTrace outputs | `stratum/source_trace` | Outputs such as `source_trace_summary.json`, `source_quality.json`, `dedupe_loss.json`, `temporal_profile.json`, `report_impact.json`, `thread_attribution.json`, `missed_signals.json`, `observation_health.json`, and `issues.json`. |
| SourceTrace raw layers | `stratum/source_trace` / run artifacts | Observation, candidate, result, and consumed records used for term telemetry and representative evidence. |
| DB context | DB service/read model caller | Optional articles, events, threads, judgments, report items, evidence links, and historical term/source baselines. |
| Historical baseline | caller/DB analytics | Optional 7-day/30-day term, source, and thread baselines used to distinguish true bursts from normal high frequency. |

## Data Access

Signal Bursts receives data from callers. It does not query the database or read
pipeline artifacts by itself unless a future runner is explicitly passed paths.
The expected in-memory contract is:

```python
detect_signal_bursts(
    terms=[...],
    records_by_layer={
        "watchlist_observations": [...],
        "discovery_observations": [...],
        "watchlist_candidates": [...],
        "discovery_candidates": [...],
        "watchlist_results": [...],
        "raw": [...],
    },
    source_trace_outputs={
        "source_quality": [...],
        "dedupe_loss": {...},
        "temporal_profile": {...},
        "report_impact": {...},
        "thread_attribution": {...},
        "missed_signals": [...],
        "observation_health": {...},
        "issues": {...},
    },
    db_context={
        "articles": [...],
        "events": [...],
        "threads": [...],
        "judgments": [...],
        "report_items": [...],
        "evidence_links": [...],
    },
    historical_baseline={...},
)
```

The DB service or orchestrator owns SQL and read-model assembly. This module
only consumes those records.

## Stages

| Stage | Scope |
|:---|:---|
| Term telemetry | Count term hits by layer, source, engine, source type, freshness, acceptance, and raw consumption. |
| Co-occurrence | Build term-pair and term-group relationships from evidence records. |
| Grouping | Convert co-occurring terms into compact signal candidates with representative records. It uses pair seeds and limited expansion rather than connected components, so weak bridge terms do not merge unrelated stories into one oversized burst. |
| Burst scoring | Score signal strength using telemetry, SourceTrace quality signals, DB relevance, novelty, freshness, duplicate penalties, and group-structure quality so compact, dense evidence groups rank above generic singleton heat. Final ranking uses diversity-aware reranking so highly overlapping candidates do not crowd out adjacent signals. |
| Context linking | Attach existing thread, event, judgment, and report-item context when available. |
| Output assembly | Emit structured burst records, term telemetry, diagnostics, and recommendations. |

## Outputs

The primary output should be:

| Output File | Purpose |
|:---|:---|
| `signal_bursts.json` | Contains term telemetry, co-occurrence diagnostics, burst candidates, burst scores, representative evidence, DB/thread/report links, and recommendations. |

The payload should keep term telemetry inside `signal_bursts.json` because term
telemetry is a stage of burst detection, not a separate top-level product.

The output shape is:

| Field | Meaning |
|:---|:---|
| `terms` | Term telemetry, including layer counts, source counts, raw hits, DB hits, accepted/rejected counts, and official/fresh counts. |
| `co_occurrence` | Term-pair graph diagnostics and representative titles. |
| `burst_candidates` | Term groups before final scoring. |
| `bursts` | Scored signal bursts with classification, confidence, DB links, report treatment, and score components. |
| `report_handoff` | Compact records intended for report synthesis. |
| `recommendations` | Query, source, and synthesis policy suggestions. |
| `diagnostics` | Run-level counts for terms, matched terms, matched records, and bursts. |

## Telemetry Modes

Term telemetry must run with or without DB context:

| Mode | Inputs | Meaning |
|:---|:---|:---|
| `acquisition_only` | SourceTrace layers only | Measures same-day acquisition/search heat across observations, candidates, results, and raw evidence. DB-related counts remain present and set to zero. |
| `context_aware` | SourceTrace layers plus DB context | Adds semantic impact signals such as article, event, thread, judgment, and report-item hits. |

The `terms` records and top-level diagnostics include `telemetry_mode` and
`db_context_available` so downstream consumers can distinguish acquisition-only
heat from context-aware semantic impact. Missing DB context must never block
term telemetry or burst detection.

## Module Map

| Module | Scope |
|:---|:---|
| `contracts.py` | In-memory input shapes and `signal_bursts.json` output filename. |
| `terms.py` | External term and alias normalization plus term matching. |
| `telemetry.py` | Term telemetry stage across SourceTrace layers and DB context. |
| `graph.py` | Co-occurrence graph diagnostics. |
| `grouping.py` | Term grouping into signal candidates. |
| `baseline.py` | Historical baseline comparison and burst classification. |
| `linking.py` | DB event/thread/judgment/report-item linking. |
| `scoring.py` | Burst scoring and recommended report treatment. |
| `handoff.py` | Compact report-synthesis handoff records. |
| `recommendations.py` | Policy feedback from detected bursts. |
| `runner.py` | Public orchestration API and JSON writer. |

## Relationship To SourceTrace

SourceTrace answers:

```text
What did sources see, keep, reject, consume, verify, report, and persist?
```

Signal Bursts answers:

```text
Which term groups are becoming hot signals, and are they meaningful or noise?
```

Signal Bursts should depend on SourceTrace outputs for source quality,
observation health, provenance, temporal freshness, missed signals, and report
impact. It should not duplicate SourceTrace's core observability logic.

## Design Rules

- Keep term lists external. Accept terms from domain config, query policy, active
  thread keywords, or a caller-provided list.
- Treat term telemetry as an internal stage of burst detection.
- Prefer JSON-friendly records and pure functions so this module can be used by
  CLI tools, notebooks, dashboards, or future DB ingestion.
- Keep DB access outside this module. Callers provide DB read-model records and
  historical baselines.
- Always separate signal strength from evidence quality: a high-count term from
  duplicate/noisy sources should not automatically become a high-confidence
  burst.
- Validate the final payload shape at the package boundary so callers and file
  writers cannot silently publish partial or malformed burst outputs.
