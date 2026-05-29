"""Source Profiler — SourceRecords → SourceProfile.

Deterministic: EMA-weighted metrics, degradation detection, incremental update.
"""

import json
import os
from collections import defaultdict


def load_profile(profiles_dir: str, domain: str) -> dict:
    """Load existing profile or return default."""
    safe_name = domain.replace(".", "_").replace("/", "_")
    path = os.path.join(profiles_dir, f"{safe_name}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def init_profile(domain: str, recs: list[dict]) -> dict:
    """Create a new SourceProfile from first batch of records."""
    first = recs[0] if recs else {}
    return {
        "source": domain,
        "source_type": first.get("source_type", "unknown"),
        "source_locale": first.get("source_locale", "en"),
        "signal_type": first.get("signal_type", "text_news"),
        "status": "active",
        "current": {},
        "checkpoints": [],
        "events": [],
    }


def compute_metrics(recs: list[dict]) -> dict:
    """Compute today's metrics from a batch of SourceRecords."""
    total = len(recs)
    if total == 0:
        return {}

    first_disclosure = sum(1 for r in recs if r.get("role") == "first_disclosure")
    rehash = sum(1 for r in recs if r.get("role") == "rehash")
    clusters = len(set(r.get("cluster_id") for r in recs if r.get("cluster_id")))

    return {
        "novelty_ratio": round(first_disclosure / total, 3),
        "exclusivity": round(clusters / total, 3),
        "signal_noise_ratio": round(1 - (rehash / total), 3) if total > 0 else 1.0,
        "total": total,
    }


def update_profile(profile: dict, metrics: dict, run_date: str, alpha: float = 0.3) -> tuple[dict, list[dict]]:
    """Update profile with EMA-weighted metrics. Returns (profile, alerts)."""
    prev = profile.get("current", {})

    profile["current"] = {
        "novelty_ratio": round(
            metrics.get("novelty_ratio", 0) * alpha +
            prev.get("novelty_ratio", metrics.get("novelty_ratio", 0)) * (1 - alpha), 3
        ),
        "verifiability": prev.get("verifiability", 0.5),
        "exclusivity": round(
            metrics.get("exclusivity", 0) * alpha +
            prev.get("exclusivity", 0) * (1 - alpha), 3
        ),
        "signal_noise_ratio": round(
            metrics.get("signal_noise_ratio", 1.0) * alpha +
            prev.get("signal_noise_ratio", 1.0) * (1 - alpha), 3
        ),
        "total_records": prev.get("total_records", 0) + metrics.get("total", 0),
        "coverage_domains": prev.get("coverage_domains", []),
        "coverage_gaps": prev.get("coverage_gaps", []),
    }
    profile["last_updated"] = run_date

    # Degradation detection
    alerts = []
    prev_novelty = prev.get("novelty_ratio", 1.0)
    if metrics.get("novelty_ratio", 0) < prev_novelty * 0.7 and prev_novelty > 0:
        alerts.append({
            "source": profile["source"],
            "type": "novelty_drop",
            "from": prev_novelty,
            "to": metrics["novelty_ratio"],
        })
        profile.setdefault("events", []).append({
            "date": run_date,
            "type": "novelty_drop",
            "detail": f"novelty dropped from {prev_novelty} to {metrics['novelty_ratio']}",
        })

    return profile, alerts


def save_profile(profiles_dir: str, profile: dict):
    """Write profile to disk."""
    os.makedirs(profiles_dir, exist_ok=True)
    safe_name = profile["source"].replace(".", "_").replace("/", "_")
    path = os.path.join(profiles_dir, f"{safe_name}.json")
    with open(path, "w") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def process_records(records: list[dict], profiles_dir: str, run_date: str) -> dict:
    """Process a batch of SourceRecords: update all profiles."""
    by_source = defaultdict(list)
    for r in records:
        by_source[r.get("source_domain", r.get("source", ""))].append(r)

    stats = {"updated": 0, "new": 0, "alerts": []}

    for domain, recs in by_source.items():
        profile = load_profile(profiles_dir, domain)
        is_new = profile is None
        if is_new:
            profile = init_profile(domain, recs)
            stats["new"] += 1

        metrics = compute_metrics(recs)
        if metrics:
            profile, alerts = update_profile(profile, metrics, run_date)
            stats["alerts"].extend(alerts)

        save_profile(profiles_dir, profile)
        stats["updated"] += 1

    return stats
