"""Source Recorder — Articles → SourceRecords.

Deterministic: reads articles.jsonl + clusters.json, writes source-records.jsonl.
One record per (source_domain, cluster_id) pair.
"""

import json
import os
from urllib.parse import urlparse

SIGNAL_MAP = {
    "news_article": "text_news",
    "product_announcement": "text_news",
    "patent": "structured_data",
    "paper": "structured_data",
    "conference_abstract": "structured_data",
    "hiring": "structured_data",
    "financial_transcript": "cross_domain",
}

ROLE_MAP = {
    "first_disclosure": "first_disclosure",
    "confirmation": "confirmation",
    "update": "update",
    "rehash": "rehash",
    "contradiction": "disputed",
}


def extract_domain(url: str) -> str:
    """Extract netloc from URL, stripping www."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return domain[4:] if domain.startswith("www.") else domain
    except Exception:
        return ""


def build_article_cluster_map(clusters: list[dict]) -> dict:
    """Build article_id → cluster_id + novelty lookup."""
    article_cluster = {}
    for c in clusters:
        cid = c.get("id", "")
        novelty = c.get("novelty", "update")
        for aid in c.get("article_ids", []):
            article_cluster[aid] = (cid, novelty)
    return article_cluster


def generate_records(
    articles: list[dict],
    clusters: list[dict],
    run_date: str,
    trial_sources: set = None,
) -> list[dict]:
    """Generate SourceRecords from articles and clusters.

    Deduplicates: one record per (source_domain, cluster_id).
    """
    article_cluster = build_article_cluster_map(clusters)
    trial_sources = trial_sources or set()

    records = []
    seen_pairs = set()

    for i, a in enumerate(articles):
        domain = a.get("source", "") or extract_domain(a.get("url", ""))
        cid, novelty = article_cluster.get(a.get("id", ""), (None, ""))
        role = ROLE_MAP.get(novelty, "unclustered") if cid else "unclustered"

        pair = (domain, cid)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        records.append({
            "id": f"sr-{run_date}-{i+1:03d}",
            "source": domain,
            "source_domain": domain,
            "source_type": a.get("source_type", "unknown"),
            "source_locale": a.get("source_locale", "en"),
            "signal_type": SIGNAL_MAP.get(a.get("artifact_type", ""), "text_news"),
            "article_id": a.get("id", ""),
            "cluster_id": cid,
            "date": run_date,
            "role": role,
            "trial": domain in trial_sources,
        })

    return records


def write_records(records: list[dict], output_dir: str):
    """Write source-records.jsonl."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "source-records.jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path
