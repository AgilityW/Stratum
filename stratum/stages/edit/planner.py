"""Deterministic planning helpers for Edit.

The legacy ``build_plan`` function supports the previous daily V2 item plan.
The active V3 path uses ``build_block_plan`` to create dynamic categories that
can be rendered through different timescale templates.
"""

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

EDITORIAL_SIGNAL_TERMS = (
    "asp",
    "price",
    "pricing",
    "contract",
    "spot",
    "shortage",
    "supply",
    "demand",
    "capacity",
    "inventory",
    "market share",
    "share",
    "margin",
    "revenue",
    "profit",
    "earnings",
    "capex",
    "investment",
    "customer",
    "qualification",
    "certification",
    "sample",
    "shipment",
    "production",
    "yield",
    "价格",
    "涨价",
    "供需",
    "缺口",
    "短缺",
    "缺货",
    "产能",
    "库存",
    "份额",
    "市占",
    "利润",
    "营收",
    "投资",
    "扩产",
    "认证",
    "客户",
    "样品",
    "量产",
    "良率",
)

LOW_SIGNAL_TERMS = (
    "video",
    "history",
    "timeline",
    "definition",
    "glossary",
    "basic",
    "目录",
    "历史",
    "回顾",
    "科普",
    "定义",
    "视频",
)

DIMENSION_LABELS = {
    "market_pricing": "价格与市场信号",
    "supply_chain": "供应链与产能信号",
    "technology": "技术路线与产品节点",
    "platform_demand": "平台需求与客户拉动",
    "financial": "财务表现与资本市场",
    "product": "产品发布与规格变化",
    "company_strategy": "公司战略与产业动作",
    "thread_watch": "持续跟踪事件",
    "general": "综合信号",
}

EDGE_TERMS = (
    "anthropic",
    "apple",
    "ymtc",
    "hbf",
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
    "资源管控",
    "产能挤压",
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


def article_dimension(article: dict) -> str:
    return str(
        article.get("query_dimension")
        or article.get("raw_metadata", {}).get("query_dimension")
        or "general"
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


def editorial_score_text(text: str) -> int:
    lower = text.lower()
    score = sum(2 for term in EDITORIAL_SIGNAL_TERMS if term in lower)
    score -= sum(2 for term in LOW_SIGNAL_TERMS if term in lower)
    return score


def editorial_score_article(article: dict) -> int:
    score = editorial_score_text(article_text(article))
    if article.get("numeric_claims"):
        score += 3
    source_type = article.get("source_type") or article.get("source_type_hint") or "media"
    if source_type == "official":
        score += 2
    if source_type == "analyst":
        score += 2
    return score


def editorial_score_item(item: dict) -> int:
    evidence = item.get("evidence") or []
    evidence_score = sum(editorial_score_text(
        f"{article.get('title', '')} {article.get('snippet', '')}"
    ) for article in evidence)
    return int(item.get("editorial_score") or 0) + evidence_score


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
    article_ids = item.get("article_ids") or []
    if article_ids:
        return str(article_ids[0])
    title = clean_title(item.get("title_hint", ""), "item").lower()
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", title)
    return "-".join(tokens[:5]) or item.get("item_id", "")


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
    main_target = int(
        budget["target_main_items"] if "target_main_items" in budget
        else budget.get("main_max_items", 18)
    )
    edge_target = int(
        budget["target_edge_items"] if "target_edge_items" in budget
        else max(5, budget.get("edge_min_items", 5))
    )
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


def category_score(category: dict) -> tuple:
    items = category.get("items", [])
    best_item_score = max((editorial_score_item(item) for item in items), default=0)
    total_evidence = sum(len(item.get("evidence") or []) for item in items)
    return (best_item_score, total_evidence, -category.get("index", 0))


def item_dimension(item: dict) -> str:
    evidence = item.get("evidence") or []
    if evidence:
        return str(evidence[0].get("query_dimension") or "general")
    return "general"


def group_selected_categories(items: list[dict], max_categories: int) -> list[dict]:
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        dimension = item_dimension(item)
        key = dimension or "general"
        if key not in grouped:
            category_id = make_category_id(key, len(order) + 1)
            grouped[key] = {
                "category_id": category_id,
                "label": DIMENSION_LABELS.get(key, clean_title(key.replace("_", " "), "综合信号")),
                "role": "dynamic_content_category",
                "source": "search_dimension",
                "dimension": key,
                "why_created": "由当天搜索结果中的 query_dimension 与入选证据动态归并生成。",
                "index": len(order) + 1,
                "items": [],
                "dropped": [],
            }
            order.append(key)
        category = grouped[key]
        item["category_id"] = category["category_id"]
        item["category_label"] = category["label"]
        category["items"].append(item)
    categories = list(grouped.values())
    return sorted(categories, key=category_score, reverse=True)[:max_categories]


def build_block_plan(
    articles: list[dict],
    clusters: dict,
    context: dict,
    run_date: str,
    budget: dict,
) -> dict:
    """Build a dynamic category/block plan shared by report timescales.

    Categories are discovered from clusters/threads and unclustered evidence. They are
    content-derived labels, not fixed domain topic buckets.
    """
    article_by_id = {str(article.get("id")): article for article in articles if article.get("id")}
    main_target = int(
        budget["target_main_items"] if "target_main_items" in budget
        else budget.get("main_max_items", 18)
    )
    edge_target = int(
        budget["target_edge_items"] if "target_edge_items" in budget
        else max(5, budget.get("edge_min_items", 5))
    )
    evidence_limit = int(budget.get("evidence_articles_per_item") or 4)
    max_categories = int(budget.get("max_categories") or max(12, main_target))
    max_main_per_category = int(budget.get("max_main_per_category") or 4)

    categories: list[dict] = []
    selected_article_ids: set[str] = set()
    omitted_candidates: list[dict] = []

    sorted_clusters = sorted(
        clusters.get("clusters", []),
        key=lambda cluster: (
            cluster_score(cluster),
            editorial_score_text(f"{cluster.get('canonical_title', '')} {cluster.get('canonical_summary', '')}"),
        ),
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

    unclustered = [
        article for article in articles
        if str(article.get("id") or "") not in selected_article_ids
        and not is_background_article(article)
        and (is_storage_relevant(article) or is_edge_signal_text(article_text(article)))
    ]
    sorted_unclustered = sorted(
        unclustered,
        key=lambda article: (editorial_score_article(article), article_rank(article)),
        reverse=True,
    )
    unclustered_main = [
        article for article in sorted_unclustered
        if not is_edge_signal_text(str(article.get("title") or "")) and editorial_score_article(article) > 0
    ]
    unclustered_edge = [
        article for article in sorted_unclustered
        if is_edge_signal_text(str(article.get("title") or ""))
    ]
    unclustered_take = unclustered_main[:main_target] + unclustered_edge[:edge_target * 2]
    for article in unclustered_take:
        kind = "edge" if is_edge_signal_text(str(article.get("title") or "")) else "main"
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

    categories = sorted(categories, key=category_score, reverse=True)
    main_pool = []
    edge_pool = []
    for category in categories:
        main_count = 0
        for item in sorted(category.get("items", []), key=editorial_score_item, reverse=True):
            if item["kind"] == "edge":
                edge_pool.append(item)
                continue
            if editorial_score_item(item) <= 0:
                category["dropped"].append(candidate_summary(item, "low editorial score"))
                omitted_candidates.append(candidate_summary(item, "low editorial score"))
                continue
            if main_count >= max_main_per_category:
                category["dropped"].append(candidate_summary(item, "category main item cap"))
                omitted_candidates.append(candidate_summary(item, "category main item cap"))
                continue
            main_count += 1
            main_pool.append(item)

    selected_topics: set[str] = set()
    selected_main: list[dict] = []
    dropped_duplicate: list[dict] = []
    for item in sorted(main_pool, key=editorial_score_item, reverse=True):
        topic = item.get("topic_key") or item["item_id"]
        if topic in selected_topics:
            dropped_duplicate.append(candidate_summary(item, "duplicate topic"))
            continue
        selected_topics.add(topic)
        selected_main.append(item)
        if len(selected_main) >= main_target:
            break

    selected_edges: list[dict] = []
    selected_edge_topics: set[str] = set()
    for item in sorted(edge_pool, key=editorial_score_item, reverse=True):
        topic = item.get("topic_key") or item["item_id"]
        if topic in selected_edge_topics:
            dropped_duplicate.append(candidate_summary(item, "duplicate edge topic"))
            continue
        selected_edge_topics.add(topic)
        selected_edges.append(item)
        if len(selected_edges) >= edge_target:
            break

    omitted_candidates.extend(dropped_duplicate)
    selected_ids = {item["item_id"] for item in selected_main + selected_edges}
    for category in categories:
        for item in category.get("items", []):
            if item["item_id"] not in selected_ids:
                summary = candidate_summary(item, "outside final reconcile budget")
                category["dropped"].append(summary)
                omitted_candidates.append(summary)

    items = renumber_items(selected_main[:main_target] + selected_edges[:edge_target])
    categories = group_selected_categories(items, max_categories=max_categories)

    return {
        "version": 3,
        "mode": "block_edit",
        "date": run_date,
        "budgets": {
            "main_target": main_target,
            "edge_target": edge_target,
            "total_target": main_target + edge_target,
            "max_categories": max_categories,
            "max_main_per_category": max_main_per_category,
        },
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
                "snippet": (article.get("snippet") or article.get("extracted_summary") or "")[:600],
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


def _legacy_planned_item(
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
                "query_dimension": article_dimension(article),
                "entities": article.get("entities") or [],
                "terms": article.get("terms") or [],
                "source_type": article.get("source_type") or article.get("source_type_hint"),
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
