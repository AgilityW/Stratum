"""Trial Source Manager — Discover → trial → evaluate → promote lifecycle.

Deterministic core: trial pool schema, sample tracking, 5-dim evaluation scoring.
Human approval required for promotion. Auto-archive for below-threshold sources.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

EVAL_WEIGHTS = {
    "novelty": 0.30,
    "verifiability": 0.25,
    "exclusivity": 0.20,
    "signal_noise": 0.15,
    "depth": 0.10,
}
PROMOTE_THRESHOLD = 0.60
DEFAULT_TRIAL_DAYS = 14
DEFAULT_MIN_SAMPLES = 20


def init_trial_pool() -> dict:
    return {"version": "2.0", "updated": "", "entries": [], "paused": [], "archived": []}


def load_trial_pool(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return init_trial_pool()


def save_trial_pool(pool: dict, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pool["updated"] = datetime.now(CST).isoformat()
    with open(path, "w") as f:
        json.dump(pool, f, indent=2, ensure_ascii=False)


def add_candidate(
    pool: dict,
    source: str,
    source_type: str,
    source_locale: str,
    discovered_at: str,
    discovery_context: str = "",
    query: str = "",
    trial_days: int = DEFAULT_TRIAL_DAYS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    discovery_layer: str = None,
) -> dict:
    """Add a new candidate to the trial pool. Skips if already present."""
    existing = {e["source"] for e in pool.get("entries", [])}
    if source in existing:
        return pool

    entry = {
        "source": source,
        "source_type": source_type,
        "source_locale": source_locale,
        "discovered_at": discovered_at,
        "discovery_context": discovery_context,
        "discovery_layer": discovery_layer,
        "signals": {
            "cited_by_trusted": False,
            "social_mention": False,
            "fills_coverage_gap": False,
            "fills_signal_type_gap": False,
        },
        "trial_start": discovered_at,
        "trial_duration_days": trial_days,
        "min_samples": min_samples,
        "sample_count": 0,
        "query": query,
        "status": "collecting",
    }
    pool.setdefault("entries", []).append(entry)
    return pool


def track_samples(pool: dict, today_records: list[dict]) -> tuple[dict, list[dict]]:
    """Update sample counts from today's SourceRecords. Returns (pool, triggered_entries)."""
    trial_counts = defaultdict(int)
    for r in today_records:
        if r.get("trial"):
            trial_counts[r.get("source", "")] += 1

    triggered = []
    for entry in pool.get("entries", []):
        if entry.get("status") != "collecting":
            continue
        src = entry["source"]
        new_count = trial_counts.get(src, 0)
        entry["sample_count"] = entry.get("sample_count", 0) + new_count
        if entry["sample_count"] >= entry.get("min_samples", DEFAULT_MIN_SAMPLES):
            entry["status"] = "evaluating"
            triggered.append(entry)

    return pool, triggered


def evaluate_source(entry: dict, src_records: list[dict], all_records: list[dict]) -> dict:
    """Compute 5-dimension score for a trial source. Returns updated entry."""
    if not src_records:
        entry["eval_score"] = 0.0
        entry["recommendation"] = "insufficient_data"
        return entry

    n = len(src_records)
    if n == 0:
        return entry

    # 1. Novelty
    novelty = sum(1 for r in src_records if r.get("role") == "first_disclosure") / n

    # 2. Verifiability
    verif = sum(1 for r in src_records if r.get("verified_by")) / n

    # 3. Exclusivity
    all_claims = set()
    for r in all_records:
        for c in r.get("claims_contributed", []):
            all_claims.add(c)
    src_claims = set()
    for r in src_records:
        for c in r.get("claims_contributed", []):
            src_claims.add(c)
    shared = len(src_claims & all_claims)
    exclusivity = 1 - (shared / len(src_claims)) if src_claims else 0

    # 4. Signal-noise
    noise_count = sum(1 for r in src_records if r.get("role") == "rehash")
    signal_noise = 1 - (noise_count / n)

    # 5. Depth
    avg_claims = sum(len(r.get("claims_contributed", [])) for r in src_records) / n
    depth = min(avg_claims / 3.0, 1.0)

    score = (
        EVAL_WEIGHTS["novelty"] * novelty +
        EVAL_WEIGHTS["verifiability"] * verif +
        EVAL_WEIGHTS["exclusivity"] * exclusivity +
        EVAL_WEIGHTS["signal_noise"] * signal_noise +
        EVAL_WEIGHTS["depth"] * depth
    )

    entry["eval_score"] = round(score, 3)
    entry["eval_dimensions"] = {
        "novelty": round(novelty, 3),
        "verifiability": round(verif, 3),
        "exclusivity": round(exclusivity, 3),
        "signal_noise": round(signal_noise, 3),
        "depth": round(depth, 3),
    }
    entry["eval_date"] = datetime.now(CST).strftime("%Y-%m-%d")
    entry["recommendation"] = "promote" if score >= PROMOTE_THRESHOLD else "archive"

    return entry


def process_evaluations(
    pool: dict,
    today_records: list[dict],
) -> dict:
    """Evaluate all triggered trial sources."""
    triggered = [e for e in pool.get("entries", []) if e.get("status") == "evaluating"]
    for entry in triggered:
        src = entry["source"]
        src_records = [r for r in today_records if r.get("source") == src and r.get("trial")]
        entry = evaluate_source(entry, src_records, today_records)
    return pool
