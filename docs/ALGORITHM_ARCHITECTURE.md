# Algorithm Architecture

This document maps current algorithm ownership. It is not a backlog and should
not track manual status by hand.

## Rule

Stages own orchestration and contract handoff. Algorithms should not grow
directly inside stages. Algorithm modules own scoring, ranking, policy
decisions, matching, validation, calibration, and measurement.

When an algorithm output becomes a structured handoff, persisted field, report
shape, or policy decision consumed outside its owner, update
`docs/CONTRACT_INVENTORY.yaml`.

## Current Algorithm Surfaces

| Surface | Owner | Main Components |
|:---|:---|:---|
| Acquisition priority | `stratum/sourcing/policy.py` | `AcquisitionPolicy`, `SourcePriorityScorer`, `SourceBudgetPolicy` |
| Watchlist observation, admission, and audit | `stratum/sourcing/watchlist/` | observation records, `AdmissionDecision`, `admit_results_with_candidates`, candidate sidecars |
| Watchlist source expansion | `stratum/sourcing/watchlist/source_expansion.py` | per-source funnel metrics and review-only promotion/deprioritization/parser/date recommendations |
| Discovery query planning | `stratum/sourcing/discovery/query_planner.py` | `QueryPlanner`, `SearchSupplementPolicy`, `QueryPerformanceScorer` |
| Discovery routing and health | `stratum/sourcing/discovery/routing.py`, `stratum/subsystems/monitoring/engine_health.py` | `RoutingPolicy`, `EngineHealthScorer` |
| Discovery observation and curation | `stratum/sourcing/discovery/` | discovery observations, `SearchResultScorer`, `SearchDiversityRanker` |
| Source trace feedback | `stratum/source_trace/` | funnel metrics, missed-signal mining, quality scoring, tuning recommendations |
| Freshness and evidence acceptance | `stratum/stages/verify/` | `FreshnessPolicy`, `EvidenceAcceptancePolicy` |
| Normalize extraction | `stratum/stages/normalize/` | entity/term extraction, thread keyword matching, claim extraction |
| Story clustering | `stratum/stages/cluster/story_clusterer.py` | `StoryClusterer`, `ClusterConfidenceScorer` |
| Event-thread lifecycle | `stratum/subsystems/event_thread/lifecycle_policy.py` | `ThreadLifecycleScorer` |
| DB semantic reads | `stratum/db/read_model.py`, `stratum/db/semantic_reads.py`, `stratum/db/service.py` | report, trend, judgment, evidence, and tracking read models |
| Judgment feedback | `stratum/db/judgment_lifecycle.py`, `stratum/db/synthesis/judgment_feedback.py` | `JudgmentLifecyclePolicy`, `JudgmentFeedbackScorer` |
| Multi-scale synthesis | `stratum/db/synthesis/` | `SynthesisPolicy`, `ThemeRanker`, `CitationRanker`, `SynthesizedEventBuilder`, `SynthesisTextBuilder` |
| Report planning | `stratum/stages/edit/` | report planning, item budget, category candidate, grouping, source alignment, output, and reconciliation policies |
| Claim validation | `stratum/stages/validate/` | `ClaimValidator`, `SourceSupportMatcher`, `SourceDatePolicy` |
| Evaluation | `stratum/evaluation/harness.py` | `EvaluationRunner` |

## Remaining Optimization Themes

Only durable calibration themes belong here:

- Calibrate source budgets, source health, candidate admission, and discovery
  routing using `watchlist_observations.jsonl`, `watchlist_candidates.jsonl`,
  `watchlist_results.json`, `discovery_observations.jsonl`,
  `discovery_candidates.jsonl`, `raw.json`, and source-trace outputs.
- Improve search/query feedback with reviewed low-yield, gap-expansion, and
  provider-health cases.
- Tune synthesis ranking, citation selection, judgment feedback, and
  scale-specific thresholds using reviewed weekly/monthly/quarterly/yearly
  outputs.
- Strengthen validation beyond lexical support when report claims overstate
  evidence class, entity support, or temporal confidence.
- Expand evaluation cases with reviewer labels so algorithm changes are judged
  by report usefulness, traceability, and calibration, not unit tests alone.

Concrete unfinished implementation work belongs in `docs/TODO.md`; completed
extractions belong in module `SCOPE.md` files and tests, not in this document.
