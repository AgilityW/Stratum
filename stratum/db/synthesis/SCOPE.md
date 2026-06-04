# db/synthesis - DB-native scale synthesis package

## Purpose

`stratum/db/synthesis` owns deterministic DB-native synthesis for weekly,
monthly, quarterly, and yearly structured reports. It consumes lower-scale DB
state plus same-scale fresh evidence and produces target-scale reports,
synthesized events, evidence links, and lineage records.

This package exists so synthesis can grow like `stratum/db/migrations`: a
cohesive DB submodule with explicit internal boundaries instead of one large
service file.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | Stable public and compatibility import surface for `stratum.db.synthesis` |
| `engine.py` | Top-level synthesis orchestration, DB foundation checks, persistence handoff, and compatibility helpers |
| `events.py` | `SynthesizedEventBuilder` for target-scale event construction, title/theme selection, confidence aggregation, priority, lineage, and field-limit policy |
| `evidence.py` | Fresh-evidence matching, `CitationRanker`, representative evidence selection, and integration-decision rendering |
| `judgment_feedback.py` | `JudgmentFeedbackScorer` for mapping reviewed judgments back to synthesis thread groups |
| `payload.py` | Structured report payload assembly for report, section, item, policy-decision metadata, evidence-link, and lineage records |
| `policy.py` | `SynthesisPolicy` for baseline strength, fresh evidence quality, domain-specific evidence classes, directionality, conflict level, and integration decisions |
| `ranker.py` | `ThemeRanker` for priority, persistence, evidence quality, impact, novelty, lifecycle, judgment feedback, and uncertainty scoring before report assembly |
| `text.py` | Report-facing text policy, Chinese product-output wording, section labels, language filtering, and executive-level framing |

## Boundaries

### Owns

- Assemble higher-scale report payloads from DB cascade inputs.
- Keep payload shape assembly in `payload.py`, separate from orchestration and
  tunable algorithm modules.
- Build synthesized target-scale event rows from ranked lower-scale thread
  groups.
- Rank candidate themes by priority, persistence, evidence quality, impact,
  novelty, lifecycle, reviewed judgment feedback, and uncertainty through named
  algorithm components.
- Map supported/challenged/invalidated judgments back to candidate thread
  groups through `JudgmentFeedbackScorer`, so completed review outcomes affect
  theme ordering instead of only appearing in the Judgment Tracker section.
- Select representative fresh evidence through `CitationRanker`, including
  source/source-type diversity and counter-evidence inclusion before payload
  assembly links citations to report items.
- Evaluate baseline strength, fresh evidence quality, domain-specific evidence
  classes, directionality, contradiction/challenge roles, and integration decisions through a
  configurable synthesis policy.
- Persist trend-item synthesis policy output as structured `policy_decision`
  metadata so downstream validation and review can audit baseline/fresh/decision
  fields without parsing report prose.
- Own scale-specific threshold profiles for weekly, monthly, quarterly, and
  yearly synthesis without forking report assembly or runtime orchestration.
- Keep report-facing text generation deterministic and traceable to structured
  inputs through `text.py`, not directly inside synthesis orchestration.

### Does Not Own

- Does not read arbitrary SQLite tables directly outside the DB service and
  persistence contracts already owned by `stratum/db`.
- Does not call search APIs, watchlist, renderers, or LLMs.
- Does not own report-window resolution.
- Does not mutate schema; migrations remain under `stratum/db/migrations`.

## Compatibility

Package-level imports such as `from stratum.db.synthesis import
synthesize_cascade_report` are the stable public surface. Callers should prefer
the public package exports for `SynthesisPolicy`, `ThemeRanker`,
`CitationRanker`, `JudgmentFeedbackScorer`, `SynthesizedEventBuilder`,
`SynthesisTextBuilder`, and `build_report_payload` instead of importing private
helpers.
