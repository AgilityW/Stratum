"""Enricher — Augmented evaluation capabilities for trial sources.

Goes beyond the basic 5-dim eval with:
- Acceleration signals: trusted citation bonus, coverage gap fill bonus
- Diversity scoring: topic coverage breadth
- Baseline comparison: source performance vs. historical norms
- Confidence calibration: adjusts recommendation confidence based on sample size
"""

from collections import defaultdict


def compute_acceleration_signals(
    source_records: list[dict],
    all_records: list[dict],
    known_sources: set[str],
) -> dict:
    """Compute acceleration bonuses for a trial source.

    Returns {signal_name: bonus_score} where each signal adds 0.05-0.15 to final score.
    """
    signals = {}

    # Signal 1: Cited by trusted sources (+0.10)
    # A trusted source is one with >50 historical records and hit_rate > 0.5
    citing_sources = set()
    for r in source_records:
        for citer in r.get("verified_by", "").split(","):
            citer = citer.strip()
            if citer and citer in known_sources:
                citing_sources.add(citer)
    if citing_sources:
        signals["cited_by_trusted"] = 0.10

    # Signal 2: Fills a coverage gap (+0.15)
    # If this source covers a topic/cluster that has no other sources
    source_clusters = {r.get("cluster_id") for r in source_records if r.get("cluster_id")}
    all_clusters = defaultdict(set)
    for r in all_records:
        cid = r.get("cluster_id")
        if cid:
            all_clusters[cid].add(r.get("source", ""))
    exclusive_clusters = sum(
        1 for cid in source_clusters
        if len(all_clusters.get(cid, set())) == 1
    )
    if exclusive_clusters >= 3:
        signals["fills_coverage_gap"] = 0.15
    elif exclusive_clusters >= 1:
        signals["fills_coverage_gap"] = 0.05

    # Signal 3: Multi-locale coverage (+0.05)
    locales = {r.get("source_locale", "en") for r in source_records}
    if len(locales) >= 2:
        signals["multi_locale"] = 0.05

    # Signal 4: Consistent output (+0.05)
    # Source has produced records across multiple days
    dates = {r.get("date", "") for r in source_records if r.get("date")}
    if len(dates) >= 5:
        signals["consistent_output"] = 0.05

    return signals


def compute_diversity(source_records: list[dict]) -> float:
    """Compute topic diversity: how many distinct clusters/topics this source covers.

    Returns 0.0-1.0 normalized diversity score.
    """
    if not source_records:
        return 0.0

    clusters = [r.get("cluster_id") for r in source_records if r.get("cluster_id")]
    unique_clusters = len(set(clusters))
    total = len(source_records)

    # Diversity = unique_clusters / total, capped at 1.0
    # A source that reports on 10 different topics in 10 articles = 1.0
    # A source that reports on 1 topic in 10 articles = 0.1
    if total == 0:
        return 0.0
    return min(unique_clusters / total, 1.0)


def compute_baseline_comparison(
    source_stats: dict,
    historical_medians: dict,
) -> dict:
    """Compare source performance against historical medians for its tier.

    Returns {metric: {value, median, percentile}}
    """
    if not historical_medians:
        return {}

    comparison = {}
    metrics = ["novelty_ratio", "signal_noise_ratio", "exclusivity"]

    for metric in metrics:
        value = source_stats.get(metric, 0)
        median = historical_medians.get(metric, 0.5)
        if median > 0:
            ratio = value / median
            comparison[metric] = {
                "value": round(value, 3),
                "median": round(median, 3),
                "ratio": round(ratio, 2),
                "assessment": "above_average" if ratio > 1.1 else
                              "below_average" if ratio < 0.9 else "average",
            }

    return comparison


def calibrate_confidence(
    score: float,
    sample_count: int,
    min_samples: int = 20,
) -> str:
    """Calibrate recommendation confidence based on sample size.

    Returns: high | medium | low
    """
    ratio = sample_count / min_samples if min_samples > 0 else 1.0

    if ratio >= 2.0 and score >= 0.70:
        return "high"
    elif ratio >= 1.0:
        return "medium"
    else:
        return "low"


def compute_enriched_eval(
    source_records: list[dict],
    all_records: list[dict],
    known_sources: set[str],
    historical_medians: dict = None,
    min_samples: int = 20,
) -> dict:
    """Full enriched evaluation for a trial source.

    Returns {
        score, dimensions, acceleration, diversity,
        baseline, confidence, recommendation
    }
    """
    n = len(source_records)
    if n == 0:
        return {"score": 0.0, "recommendation": "insufficient_data",
                "confidence": "low"}

    # Base 5-dim metrics
    novelty = sum(1 for r in source_records if r.get("role") == "first_disclosure") / n
    verif = sum(1 for r in source_records if r.get("verified_by")) / n

    all_claims = set()
    for r in all_records:
        for c in r.get("claims_contributed", []):
            all_claims.add(c)
    src_claims = set()
    for r in source_records:
        for c in r.get("claims_contributed", []):
            src_claims.add(c)
    shared = len(src_claims & all_claims)
    exclusivity = 1 - (shared / len(src_claims)) if src_claims else 0

    noise_count = sum(1 for r in source_records if r.get("role") == "rehash")
    signal_noise = 1 - (noise_count / n) if n > 0 else 1.0

    avg_claims = sum(len(r.get("claims_contributed", [])) for r in source_records) / n
    depth = min(avg_claims / 3.0, 1.0)

    # Acceleration signals
    acceleration_signals = compute_acceleration_signals(source_records, all_records, known_sources)
    acceleration_bonus = sum(acceleration_signals.values())

    # Diversity
    diversity = compute_diversity(source_records)

    # 7-dim weighted score (incorporates acceleration and diversity)
    weights = {
        "novelty": 0.25,
        "verifiability": 0.20,
        "exclusivity": 0.15,
        "signal_noise": 0.12,
        "depth": 0.08,
        "diversity": 0.10,
        "acceleration": 0.10,
    }

    dimensions = {
        "novelty": round(novelty, 3),
        "verifiability": round(verif, 3),
        "exclusivity": round(exclusivity, 3),
        "signal_noise": round(signal_noise, 3),
        "depth": round(depth, 3),
        "diversity": round(diversity, 3),
        "acceleration": round(acceleration_bonus, 3),
    }

    score = sum(weights[k] * dimensions[k] for k in weights)

    # Baseline comparison
    baseline = {}
    if historical_medians:
        baseline = compute_baseline_comparison(
            {"novelty_ratio": novelty, "signal_noise_ratio": signal_noise, "exclusivity": exclusivity},
            historical_medians,
        )

    # Calibrated confidence
    confidence = calibrate_confidence(score, n, min_samples)

    # Recommendation with guardrails
    if score >= 0.70 and confidence in ("high", "medium"):
        recommendation = "promote"
    elif score >= 0.60 and confidence == "high":
        recommendation = "promote"
    elif score < 0.35:
        recommendation = "archive"
    elif score < 0.50 and confidence == "high":
        recommendation = "archive"
    else:
        recommendation = "extend"

    return {
        "score": round(score, 3),
        "dimensions": dimensions,
        "acceleration_signals": acceleration_signals,
        "diversity": diversity,
        "baseline": baseline,
        "confidence": confidence,
        "sample_count": n,
        "recommendation": recommendation,
        "weights": weights,
    }
