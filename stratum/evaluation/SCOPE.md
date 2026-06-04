# stratum/evaluation - deterministic report evaluation

## Purpose

`stratum/evaluation` provides fixed, model-free benchmark checks for report
quality. It exists to make algorithm changes measurable before reviewer labels
or model-based scoring are introduced.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | public evaluation API |
| `harness.py` | benchmark case loading, deterministic checks, summary output, CLI |

## Public API

```python
from stratum.evaluation import evaluate_cases, load_cases

summary = evaluate_cases(load_cases("tests/fixtures/evaluation/report_cases.json"))
```

The CLI form is:

```bash
python -m stratum.evaluation.harness --cases tests/fixtures/evaluation/report_cases.json
```

To write a JSON summary:

```bash
python -m stratum.evaluation.harness \
  --cases tests/fixtures/evaluation/report_cases.json \
  --output /tmp/stratum-evaluation-summary.json
```

## Boundaries

### Owns

- Load fixed evaluation case files.
- Score deterministic expectations such as required phrases, required sources,
  traceability terms, citation markers, judgment signals, executive
  implications, confidence terms, and prohibited phrases.
- Emit structured evaluation summaries for regression gates.

### Does Not Own

- Does not generate reports.
- Does not call LLMs or external services.
- Does not replace human review labels; it provides the first stable regression
  layer that reviewer labels can extend later.
- Does not write production runtime data.

## Contracts

Evaluation cases and summaries are structured benchmark artifacts. They are
tracked in `docs/CONTRACT_INVENTORY.yaml` so future algorithm work can add
fields deliberately.

Case records use this shape:

```json
{
  "id": "weekly-storage-executive-baseline",
  "scale": "weekly",
  "domain": "storage",
  "report_markdown": "...",
  "expectations": {
    "required_phrases": [],
    "required_sources": [],
    "traceability_terms": [],
    "citation_markers": [],
    "judgment_signals": [],
    "executive_implications": [],
    "confidence_terms": [],
    "prohibited_phrases": [],
    "min_score": 1.0
  }
}
```

`EvaluationSummary` contains total case counts, pass/fail counts, average
score, check-level metric averages, and per-case check details.

Add new checks as deterministic functions first. LLM or human-review scoring
should be an additional layer, not a replacement for this deterministic
baseline.

## Testing

Use targeted tests:

```bash
.venv/bin/python -m pytest tests/test_evaluation.py -q
```
