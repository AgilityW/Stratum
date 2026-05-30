"""Deterministic planning helpers for daily edit V2."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urlparse


SOURCE_TYPE_PRIORITY = {
    "official": 0,
    "analyst": 1,
    "media": 2,
    "blog": 3,
}

EDGE_TERMS = (
    "anthropic",
    "board",
    "director",
    "appoint",
    "glass",
    "x-dram",
    "doB".lower(),
    "122tb",
    "marvell",
    "neo semiconductor",
    "western digital",
    "威刚",
    "创见",
    "模组",
    "董事会",
    "任命",
    "玻璃",
    "光盘",
    "华为自研",
    "个股",
)

STORAGE_RELEVANCE_TERMS = (
    "memory",
    "storage",
    "dram",
    "nand",
    "hbm",
    "ssd",
    "flash",
    "kioxia",
    "sandisk",
    "western digital",
    "micron",
    "sk hynix",
    "cxmt",
    "ymtc",
    "marvell",
    "adata",
    "存储",
    "記憶",
    "内存",
    "記憶體",
    "闪存",
    "內存",
    "长鑫",
    "长江存储",
    "威刚",
)


def article_source(article: dict) -> str:
    """Return a stable display source label."""
    source = article.get("source") or article.get("source_domain") or ""
    if source:
        return str(source).strip()
    url = str(article.get("url") or "")
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def article_date(article: dict, fallback: str) -> str:
    raw = str(article.get("published_at") or article.get("date") or fallback)
    match = re.match(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else fallback


def article_text(article: dict) -> str:
    return " ".join(
        str(article.get(key) or "")
        for key in ("title", "snippet", "extracted_summary")
    )


def is_background_article(article: dict) -> bool:
    flags = article.get("quality_flags") or []
    return any(str(flag).startswith("BACKGROUND_") for flag in flags)


def is_storage_relevant(article: dict) -> bool:
    lower = article_text(article).lower()
    terms = " ".join(str(term).lower() for term in article.get("terms") or [])
    haystack = f"{lower} {terms}"
    return any(term in haystack for term in STORAGE_RELEVANCE_TERMS)


def is_edge_signal_text(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in EDGE_TERMS)


def article_rank(article: dict) -> tuple:
    source_type = article.get("source_type") or article.get("source_type_hint") or "media"
    source_rank = SOURCE_TYPE_PRIORITY.get(str(source_type), 9)
    has_numeric = bool(article.get("numeric_claims"))
    snippet_len = len(str(article.get("snippet") or article.get("extracted_summary") or ""))
    return (
        is_background_article(article),
        not is_storage_relevant(article),
        source_rank,
        not has_numeric,
        -snippet_len,
        article_source(article),
        article.get("title", ""),
    )


def make_item_id(kind: str, seed: str, index: int) -> str:
    digest = hashlib.sha1(f"{kind}|{seed}|{index}".encode("utf-8")).hexdigest()[:10]
    return f"{kind}-{index:02d}-{digest}"


def clean_title(title: str, fallback: str = "Untitled item") -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    title = title.replace("...", "").strip(" -")
    return title[:110] or fallback


def evidence_articles(
    article_ids: list[str],
    article_by_id: dict[str, dict],
    limit: int,
    allow_edge_only: bool = False,
) -> list[dict]:
    articles = [article_by_id.get(article_id) for article_id in article_ids]
    articles = [article for article in articles if article]
    fresh = [
        article for article in articles
        if not is_background_article(article)
        and (is_storage_relevant(article) or (allow_edge_only and is_edge_signal_text(article_text(article))))
    ]
    if allow_edge_only:
        return fresh[:limit]
    return sorted(fresh, key=article_rank)[:limit]


def cluster_score(cluster: dict) -> tuple:
    confidence = str(cluster.get("confidence") or "").lower()
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)
    source_types = set(cluster.get("source_types") or [])
    has_official = "official" in source_types
    has_analyst = "analyst" in source_types
    count = int(cluster.get("article_count") or len(cluster.get("article_ids") or []))
    return (confidence_score, has_official, has_analyst, count)


def build_plan(
    articles: list[dict],
    clusters: dict,
    context: dict,
    run_date: str,
    budget: dict,
) -> dict:
    """Build deterministic item plan from normalized articles and clusters."""
    article_by_id = {str(article.get("id")): article for article in articles if article.get("id")}
    main_target = int(budget.get("target_main_items") or budget.get("main_max_items") or 18)
    edge_target = int(budget.get("target_edge_items") or max(5, budget.get("edge_min_items", 5)))
    evidence_limit = int(budget.get("evidence_articles_per_item") or 4)

    selected_article_ids: set[str] = set()
    main_candidates: list[dict] = []
    edge_candidates: list[dict] = []
    omitted_candidates: list[dict] = []

    sorted_clusters = sorted(
        clusters.get("clusters", []),
        key=cluster_score,
        reverse=True,
    )
    for cluster in sorted_clusters:
        c_text = f"{cluster.get('canonical_title', '')} {cluster.get('canonical_summary', '')}"
        kind = "edge" if is_edge_signal_text(c_text) else "main"
        evidence = evidence_articles(
            cluster.get("article_ids", []),
            article_by_id,
            evidence_limit,
            allow_edge_only=(kind == "edge"),
        )
        if not evidence:
            continue
        item_evidence_sets = [[evidence[0]]] if kind == "edge" else [evidence]
        for evidence_set in item_evidence_sets:
            for article in evidence_set:
                if article.get("id"):
                    selected_article_ids.add(str(article["id"]))
            candidate = planned_item(
                kind=kind,
                index=len(edge_candidates if kind == "edge" else main_candidates) + 1,
                title_hint=clean_title(
                    evidence_set[0].get("title") if kind == "edge" else cluster.get("canonical_title"),
                    "Cluster update",
                ),
                run_date=run_date,
                cluster=cluster,
                evidence=evidence_set,
                reason=(
                    f"clustered evidence: {cluster.get('article_count', len(cluster.get('article_ids', [])))} articles, "
                    f"confidence={cluster.get('confidence', '?')}"
                ),
            )
            (edge_candidates if kind == "edge" else main_candidates).append(candidate)
        for article in evidence:
            if article.get("id"):
                selected_article_ids.add(str(article["id"]))

    unclustered = [
        article for article in articles
        if str(article.get("id") or "") not in selected_article_ids
        and not is_background_article(article)
        and is_storage_relevant(article)
    ]
    sorted_unclustered = sorted(unclustered, key=article_rank)
    for article in sorted_unclustered:
        text = article_text(article)
        kind = "edge" if is_edge_signal_text(text) else "main"
        target_list = edge_candidates if kind == "edge" else main_candidates
        if kind == "main" and len(main_candidates) >= main_target:
            omitted_candidates.append(omitted_item(article, "main target already filled", run_date))
            continue
        if kind == "edge" and len(edge_candidates) >= edge_target:
            omitted_candidates.append(omitted_item(article, "edge target already filled", run_date))
            continue
        target_list.append(planned_item(
            kind=kind,
            index=len(target_list) + 1,
            title_hint=clean_title(article.get("title"), "Article update"),
            run_date=run_date,
            cluster=None,
            evidence=[article],
            reason="unclustered article with incremental value",
        ))
        if article.get("id"):
            selected_article_ids.add(str(article["id"]))
        if len(main_candidates) >= main_target and len(edge_candidates) >= edge_target:
            break

    items = main_candidates[:main_target] + edge_candidates[:edge_target]
    selected_plan_ids = {item["item_id"] for item in items}
    omitted_candidates.extend(
        candidate_summary(candidate, "outside final item budget")
        for candidate in main_candidates[main_target:] + edge_candidates[edge_target:]
        if candidate["item_id"] not in selected_plan_ids
    )

    return {
        "version": 2,
        "date": run_date,
        "budgets": {
            "main_target": main_target,
            "edge_target": edge_target,
            "total_target": main_target + edge_target,
        },
        "counts": {
            "raw_articles": len(articles),
            "clusters": len(clusters.get("clusters", [])),
            "main_items": sum(1 for item in items if item["kind"] == "main"),
            "edge_items": sum(1 for item in items if item["kind"] == "edge"),
            "total_items": len(items),
            "omitted_candidates": len(omitted_candidates),
        },
        "items": renumber_items(items),
        "omitted_candidates": omitted_candidates[:200],
        "context_summary": {
            "carried_forward": len(context.get("carried_forward", [])) if isinstance(context, dict) else 0,
            "coverage_gaps": len(context.get("coverage_gaps", [])) if isinstance(context, dict) else 0,
        },
    }


def planned_item(
    kind: str,
    index: int,
    title_hint: str,
    run_date: str,
    cluster: dict | None,
    evidence: list[dict],
    reason: str,
) -> dict:
    seed = cluster.get("id") if cluster else evidence[0].get("id", title_hint)
    primary_evidence = evidence[:1]
    return {
        "item_id": make_item_id(kind, str(seed), index),
        "kind": kind,
        "title_hint": title_hint,
        "cluster_id": cluster.get("id") if cluster else None,
        "thread_id": cluster.get("thread_id") if cluster else None,
        "thread_label": cluster.get("thread_label") if cluster else None,
        "article_ids": [str(article.get("id")) for article in evidence if article.get("id")],
        "sources": list(dict.fromkeys(
            article_source(article) for article in primary_evidence if article_source(article)
        )),
        "dates": sorted(set(article_date(article, run_date) for article in primary_evidence)),
        "reason": reason,
        "priority_score": list(cluster_score(cluster)) if cluster else list(article_rank(evidence[0])[:3]),
        "evidence": [
            {
                "id": article.get("id"),
                "title": article.get("title", ""),
                "source": article_source(article),
                "date": article_date(article, run_date),
                "url": article.get("url", ""),
                "snippet": (article.get("snippet") or article.get("extracted_summary") or "")[:600],
                "quality_flags": article.get("quality_flags") or [],
            }
            for article in evidence
        ],
    }


def renumber_items(items: list[dict]) -> list[dict]:
    renumbered = []
    main_index = 0
    edge_index = 0
    for item in items:
        item = dict(item)
        if item["kind"] == "edge":
            edge_index += 1
            item["sequence"] = edge_index
        else:
            main_index += 1
            item["sequence"] = main_index
        renumbered.append(item)
    return renumbered


def omitted_item(article: dict, reason: str, run_date: str) -> dict:
    return {
        "title": article.get("title", ""),
        "source": article_source(article),
        "date": article_date(article, run_date),
        "article_id": article.get("id"),
        "reason": reason,
    }


def candidate_summary(candidate: dict, reason: str) -> dict:
    return {
        "title": candidate.get("title_hint", ""),
        "source": ", ".join(candidate.get("sources", [])),
        "date": ", ".join(candidate.get("dates", [])),
        "article_id": (candidate.get("article_ids") or [None])[0],
        "cluster_id": candidate.get("cluster_id"),
        "reason": reason,
    }
