"""Deterministic planning helpers for Edit.

``build_block_plan`` creates dynamic evidence-derived categories that can be
rendered through different timescale templates.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

try:
    from .boilerplate import clean_evidence_text
    from .planning_policy import (
        CategoryGroupingPolicy,
        CategoryCandidatePolicy,
        ItemBudgetPolicy,
        PlanReconciliationPolicy,
        article_rank,
        article_source,
        article_text,
        cluster_score,
        editorial_score_article,
        is_background_article,
        is_edge_signal_text,
        is_storage_relevant,
    )
except ImportError:  # pragma: no cover - script/test fallback
    from boilerplate import clean_evidence_text
    from planning_policy import (
        CategoryGroupingPolicy,
        CategoryCandidatePolicy,
        ItemBudgetPolicy,
        PlanReconciliationPolicy,
        article_rank,
        article_source,
        article_text,
        cluster_score,
        editorial_score_article,
        is_background_article,
        is_edge_signal_text,
        is_storage_relevant,
    )


def article_date(article: dict, fallback: str) -> str:
    raw = str(article.get("published_at") or article.get("date") or fallback)
    match = re.match(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else fallback


def article_dimension(article: dict) -> str:
    return str(
        article.get("query_dimension")
        or article.get("raw_metadata", {}).get("query_dimension")
        or "general"
    )


def make_item_id(kind: str, seed: str, index: int) -> str:
    digest = hashlib.sha1(f"{kind}|{seed}|{index}".encode("utf-8")).hexdigest()[:10]
    return f"{kind}-{index:02d}-{digest}"


def make_category_id(seed: str, index: int) -> str:
    digest = hashlib.sha1(f"category|{seed}|{index}".encode("utf-8")).hexdigest()[:10]
    return f"cat-{index:02d}-{digest}"


def clean_title(title: str, fallback: str = "Untitled item") -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    title = title.replace("...", "").strip(" -")
    return title[:110] or fallback


def category_label_from_cluster(cluster: dict, fallback: str) -> str:
    label = cluster.get("thread_label") or cluster.get("canonical_title") or fallback
    return clean_title(label, fallback)


def item_topic_key(item: dict) -> str:
    title = clean_title(item.get("title_hint", ""), "item").lower()
    title = re.sub(r"^\[news\]\s*", "", title)
    title = re.sub(r"^【边缘信号】", "", title)
    title = re.sub(r"reportedly|sources said|消息称|据悉", " ", title)
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", title)
    if tokens:
        return "-".join(tokens[:6])
    article_ids = item.get("article_ids") or []
    if article_ids:
        return str(article_ids[0])
    return item.get("item_id", "")


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


def item_dimension(item: dict) -> str:
    return CategoryGroupingPolicy().item_dimension(item)


def group_selected_categories(items: list[dict], max_categories: int) -> list[dict]:
    return CategoryGroupingPolicy().group_selected(items, max_categories)


class ReportPlanner:
    """Build deterministic report plans from evidence, clusters, and budgets."""

    def __init__(
        self,
        budget_policy: ItemBudgetPolicy | None = None,
        candidate_policy: CategoryCandidatePolicy | None = None,
        reconcile_policy: PlanReconciliationPolicy | None = None,
        grouping_policy: CategoryGroupingPolicy | None = None,
    ):
        self.budget_policy = budget_policy or ItemBudgetPolicy()
        self.candidate_policy = candidate_policy or CategoryCandidatePolicy()
        self.reconcile_policy = reconcile_policy or PlanReconciliationPolicy()
        self.grouping_policy = grouping_policy or CategoryGroupingPolicy()

    def build_block_plan(
        self,
        articles: list[dict],
        clusters: dict,
        context: dict,
        run_date: str,
        budget: dict,
    ) -> dict:
        return _build_block_plan_impl(
            articles,
            clusters,
            context,
            run_date,
            self.budget_policy.resolve(budget),
            self.candidate_policy,
            self.reconcile_policy,
            self.grouping_policy,
        )


def build_block_plan(
    articles: list[dict],
    clusters: dict,
    context: dict,
    run_date: str,
    budget: dict,
) -> dict:
    """Compatibility entry point for Edit callers."""
    return ReportPlanner().build_block_plan(articles, clusters, context, run_date, budget)


def _build_block_plan_impl(
    articles: list[dict],
    clusters: dict,
    context: dict,
    run_date: str,
    budget,
    candidate_policy: CategoryCandidatePolicy,
    reconcile_policy: PlanReconciliationPolicy,
    grouping_policy: CategoryGroupingPolicy,
) -> dict:
    """Build a dynamic category/block plan shared by report timescales.

    Categories are discovered from clusters/threads and unclustered evidence. They are
    content-derived labels, not fixed domain topic buckets.
    """
    article_by_id = {str(article.get("id")): article for article in articles if article.get("id")}
    main_target = budget.main_target
    edge_target = budget.edge_target
    evidence_limit = budget.evidence_limit
    max_categories = budget.max_categories

    categories: list[dict] = []
    selected_article_ids: set[str] = set()
    omitted_candidates: list[dict] = []

    for cluster in candidate_policy.sorted_clusters(clusters):
        kind = candidate_policy.cluster_kind(cluster)
        evidence = candidate_policy.evidence_articles(
            cluster.get("article_ids", []),
            article_by_id,
            evidence_limit,
            allow_edge_only=(kind == "edge"),
        )
        if not evidence:
            continue
        cat_index = len(categories) + 1
        category_id = make_category_id(cluster.get("id") or cluster.get("canonical_title") or str(cat_index), cat_index)
        category_label = category_label_from_cluster(cluster, f"动态主题 {cat_index}")
        category_items = []
        item_evidence_sets = [[evidence[0]]] if kind == "edge" else [evidence]
        for evidence_set in item_evidence_sets:
            for article in evidence_set:
                if article.get("id"):
                    selected_article_ids.add(str(article["id"]))
            category_items.append(planned_item(
                kind=kind,
                index=len(category_items) + 1,
                title_hint=clean_title(
                    evidence_set[0].get("title") if kind == "edge" else cluster.get("canonical_title"),
                    "Cluster update",
                ),
                run_date=run_date,
                cluster=cluster,
                evidence=evidence_set,
                reason=(
                    f"category evidence from cluster {cluster.get('id')}: "
                    f"{cluster.get('article_count', len(cluster.get('article_ids', [])))} articles, "
                    f"confidence={cluster.get('confidence', '?')}"
                ),
                category_id=category_id,
                category_label=category_label,
            ))
        categories.append({
            "category_id": category_id,
            "label": category_label,
            "role": "dynamic_content_category",
            "source": "cluster",
            "cluster_id": cluster.get("id"),
            "thread_id": cluster.get("thread_id"),
            "why_created": "由同一 cluster/thread 的当日证据动态归并生成。",
            "index": cat_index,
            "items": category_items,
            "dropped": [],
        })

    for article in candidate_policy.unclustered_candidates(articles, selected_article_ids, budget):
        kind = candidate_policy.article_kind(article)
        cat_index = len(categories) + 1
        category_id = make_category_id(article.get("id") or article.get("title") or str(cat_index), cat_index)
        category_label = clean_title(article.get("title"), f"动态主题 {cat_index}")
        categories.append({
            "category_id": category_id,
            "label": category_label,
            "role": "dynamic_content_category",
            "source": "unclustered",
            "cluster_id": None,
            "thread_id": article.get("event_thread_id"),
            "why_created": "由未聚类但具备增量价值的当日证据生成。",
            "index": cat_index,
            "items": [planned_item(
                kind=kind,
                index=1,
                title_hint=category_label,
                run_date=run_date,
                cluster=None,
                evidence=[article],
                reason="unclustered article with incremental value",
                category_id=category_id,
                category_label=category_label,
            )],
            "dropped": [],
        })

    reconciled = reconcile_policy.reconcile(categories, budget)
    omitted_candidates.extend(reconciled.omitted_candidates)

    items = renumber_items(reconciled.selected_items)
    categories = grouping_policy.group_selected(items, max_categories=max_categories)

    return {
        "version": 3,
        "mode": "block_edit",
        "date": run_date,
        "budgets": budget.to_plan_dict(),
        "counts": {
            "raw_articles": len(articles),
            "clusters": len(clusters.get("clusters", [])),
            "categories": len(categories),
            "main_items": sum(1 for item in items if item["kind"] == "main"),
            "edge_items": sum(1 for item in items if item["kind"] == "edge"),
            "total_items": len(items),
            "omitted_candidates": len(omitted_candidates),
        },
        "categories": categories,
        "items": items,
        "omitted_candidates": omitted_candidates[:300],
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
    category_id: str | None = None,
    category_label: str | None = None,
) -> dict:
    seed = cluster.get("id") if cluster else evidence[0].get("id", title_hint)
    primary_evidence = evidence[:1]
    score = sum(editorial_score_article(article) for article in evidence)
    item = {
        "item_id": make_item_id(kind, str(seed), index),
        "kind": kind,
        "title_hint": title_hint,
        "category_id": category_id,
        "category_label": category_label,
        "cluster_id": cluster.get("id") if cluster else None,
        "thread_id": cluster.get("thread_id") if cluster else None,
        "thread_label": cluster.get("thread_label") if cluster else None,
        "article_ids": [str(article.get("id")) for article in evidence if article.get("id")],
        "sources": list(dict.fromkeys(
            article_source(article) for article in primary_evidence if article_source(article)
        )),
        "dates": sorted(set(article_date(article, run_date) for article in primary_evidence)),
        "reason": reason,
        "topic_key": "",
        "editorial_score": score,
        "priority_score": list(cluster_score(cluster)) if cluster else list(article_rank(evidence[0])[:3]),
        "evidence": [
            {
                "id": article.get("id"),
                "title": article.get("title", ""),
                "source": article_source(article),
                "date": article_date(article, run_date),
                "url": article.get("url", ""),
                "snippet": clean_evidence_text(article.get("snippet") or article.get("extracted_summary") or "")[:600],
                "quality_flags": article.get("quality_flags") or [],
                "query_dimension": article_dimension(article),
                "entities": article.get("entities") or [],
                "terms": article.get("terms") or [],
                "source_type": article.get("source_type") or article.get("source_type_hint"),
            }
            for article in evidence
        ],
    }
    item["topic_key"] = item_topic_key(item)
    return item


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
