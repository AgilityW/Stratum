"""Editorial evidence scoring and planning policy for Edit."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from urllib.parse import urlparse

try:
    from .boilerplate import clean_evidence_text
except ImportError:  # pragma: no cover - script/test fallback
    from boilerplate import clean_evidence_text


SOURCE_TYPE_PRIORITY = {
    "official": 0,
    "analyst": 1,
    "media": 2,
    "blog": 3,
    "social": 4,
}

WEAK_SOURCE_TYPES = {"blog", "social"}

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
    "dob",
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


@dataclass(frozen=True)
class ItemBudget:
    """Resolved item and category budget for report planning."""

    main_target: int
    edge_target: int
    evidence_limit: int
    max_categories: int
    max_main_per_category: int

    @property
    def total_target(self) -> int:
        return self.main_target + self.edge_target

    def to_plan_dict(self) -> dict:
        return {
            "main_target": self.main_target,
            "edge_target": self.edge_target,
            "total_target": self.total_target,
            "max_categories": self.max_categories,
            "max_main_per_category": self.max_main_per_category,
        }


class ItemBudgetPolicy:
    """Resolve report planning budgets from runtime profile settings."""

    def resolve(self, budget: dict) -> ItemBudget:
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
        return ItemBudget(
            main_target=main_target,
            edge_target=edge_target,
            evidence_limit=evidence_limit,
            max_categories=max_categories,
            max_main_per_category=max_main_per_category,
        )


@dataclass
class ReconciledPlanItems:
    """Selected report items and omitted candidate diagnostics."""

    selected_main: list[dict]
    selected_edges: list[dict]
    omitted_candidates: list[dict]

    @property
    def selected_items(self) -> list[dict]:
        return self.selected_main + self.selected_edges


class EditorialEvidenceScorer:
    """Score evidence, clusters, and dynamic categories for report planning."""

    def article_source(self, article: dict) -> str:
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

    def article_text(self, article: dict) -> str:
        return " ".join(
            clean_evidence_text(str(article.get(key) or ""))
            for key in ("title", "snippet", "extracted_summary")
        )

    def is_background_article(self, article: dict) -> bool:
        flags = article.get("quality_flags") or []
        return any(str(flag).startswith("BACKGROUND_") for flag in flags)

    def is_storage_relevant(self, article: dict) -> bool:
        lower = self.article_text(article).lower()
        terms = " ".join(str(term).lower() for term in article.get("terms") or [])
        haystack = f"{lower} {terms}"
        return any(term in haystack for term in STORAGE_RELEVANCE_TERMS)

    def is_edge_signal_text(self, text: str) -> bool:
        lower = text.lower()
        return any(term in lower for term in EDGE_TERMS)

    def article_rank(self, article: dict) -> tuple:
        source_type = article.get("source_type") or article.get("source_type_hint") or "media"
        source_rank = SOURCE_TYPE_PRIORITY.get(str(source_type), 9)
        has_numeric = bool(article.get("numeric_claims"))
        snippet_len = len(str(article.get("snippet") or article.get("extracted_summary") or ""))
        return (
            self.is_background_article(article),
            not self.is_storage_relevant(article),
            source_rank,
            not has_numeric,
            -snippet_len,
            self.article_source(article),
            article.get("title", ""),
        )

    def editorial_score_text(self, text: str) -> int:
        lower = text.lower()
        score = sum(2 for term in EDITORIAL_SIGNAL_TERMS if term in lower)
        score -= sum(2 for term in LOW_SIGNAL_TERMS if term in lower)
        return score

    def editorial_score_article(self, article: dict) -> int:
        score = self.editorial_score_text(self.article_text(article))
        if article.get("numeric_claims"):
            score += 3
        source_type = article.get("source_type") or article.get("source_type_hint") or "media"
        if source_type == "official":
            score += 2
        if source_type == "analyst":
            score += 2
        return score

    def editorial_score_item(self, item: dict) -> int:
        evidence = item.get("evidence") or []
        evidence_score = sum(
            self.editorial_score_text(f"{article.get('title', '')} {article.get('snippet', '')}")
            for article in evidence
        )
        source_types = {
            str(article.get("source_type") or article.get("source_type_hint") or "media")
            for article in evidence
        }
        diversity_bonus = 2 if len(source_types - WEAK_SOURCE_TYPES) >= 2 else 0
        freshness_penalty = 2 if evidence and all(self.is_background_article(article) for article in evidence) else 0
        weak_penalty = 2 if source_types and source_types.issubset(WEAK_SOURCE_TYPES) else 0
        return int(item.get("editorial_score") or 0) + evidence_score + diversity_bonus - freshness_penalty - weak_penalty

    def item_source_types(self, item: dict) -> set[str]:
        return {
            str(article.get("source_type") or article.get("source_type_hint") or "media")
            for article in item.get("evidence") or []
        }

    def item_has_fresh_evidence(self, item: dict) -> bool:
        evidence = item.get("evidence") or []
        return any(not self.is_background_article(article) for article in evidence)

    def should_keep_edge_item(self, item: dict) -> bool:
        source_types = self.item_source_types(item)
        if source_types and source_types.issubset(WEAK_SOURCE_TYPES):
            return False
        if not self.item_has_fresh_evidence(item):
            return False
        return self.editorial_score_item(item) > 0

    def cluster_score(self, cluster: dict) -> tuple:
        confidence = str(cluster.get("confidence") or "").lower()
        confidence_score = {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)
        source_types = set(cluster.get("source_types") or [])
        has_official = "official" in source_types
        has_analyst = "analyst" in source_types
        count = int(cluster.get("article_count") or len(cluster.get("article_ids") or []))
        return (confidence_score, has_official, has_analyst, count)

    def category_score(self, category: dict) -> tuple:
        items = category.get("items", [])
        best_item_score = max((self.editorial_score_item(item) for item in items), default=0)
        total_evidence = sum(len(item.get("evidence") or []) for item in items)
        return (best_item_score, total_evidence, -category.get("index", 0))


class CategoryCandidatePolicy:
    """Select cluster and unclustered evidence candidates for report planning."""

    def __init__(self, scorer: EditorialEvidenceScorer | None = None):
        self.scorer = scorer or EditorialEvidenceScorer()

    def sorted_clusters(self, clusters: dict) -> list[dict]:
        return sorted(
            clusters.get("clusters", []),
            key=lambda cluster: (
                self.scorer.cluster_score(cluster),
                self.scorer.editorial_score_text(
                    f"{cluster.get('canonical_title', '')} {cluster.get('canonical_summary', '')}"
                ),
            ),
            reverse=True,
        )

    def cluster_kind(self, cluster: dict) -> str:
        text = f"{cluster.get('canonical_title', '')} {cluster.get('canonical_summary', '')}"
        return "edge" if self.scorer.is_edge_signal_text(text) else "main"

    def evidence_articles(
        self,
        article_ids: list[str],
        article_by_id: dict[str, dict],
        limit: int,
        allow_edge_only: bool = False,
    ) -> list[dict]:
        articles = [article_by_id.get(article_id) for article_id in article_ids]
        articles = [article for article in articles if article]
        fresh = [
            article for article in articles
            if not self.scorer.is_background_article(article)
            and (
                self.scorer.is_storage_relevant(article)
                or (allow_edge_only and self.scorer.is_edge_signal_text(self.scorer.article_text(article)))
            )
        ]
        if allow_edge_only:
            return fresh[:limit]
        return sorted(fresh, key=self.scorer.article_rank)[:limit]

    def unclustered_candidates(
        self,
        articles: list[dict],
        selected_article_ids: set[str],
        budget: ItemBudget,
    ) -> list[dict]:
        unclustered = [
            article for article in articles
            if str(article.get("id") or "") not in selected_article_ids
            and not self.scorer.is_background_article(article)
            and (
                self.scorer.is_storage_relevant(article)
                or self.scorer.is_edge_signal_text(self.scorer.article_text(article))
            )
        ]
        sorted_unclustered = sorted(
            unclustered,
            key=lambda article: (self.scorer.editorial_score_article(article), self.scorer.article_rank(article)),
            reverse=True,
        )
        unclustered_main = [
            article for article in sorted_unclustered
            if not self.scorer.is_edge_signal_text(str(article.get("title") or ""))
            and self.scorer.editorial_score_article(article) > 0
        ]
        unclustered_edge = [
            article for article in sorted_unclustered
            if self.scorer.is_edge_signal_text(str(article.get("title") or ""))
        ]
        return unclustered_main[:budget.main_target] + unclustered_edge[:budget.edge_target * 2]

    def article_kind(self, article: dict) -> str:
        return "edge" if self.scorer.is_edge_signal_text(str(article.get("title") or "")) else "main"


class PlanReconciliationPolicy:
    """Select final report items from candidate categories under item budgets."""

    def __init__(self, scorer: EditorialEvidenceScorer | None = None):
        self.scorer = scorer or EditorialEvidenceScorer()

    def reconcile(self, categories: list[dict], budget: ItemBudget) -> ReconciledPlanItems:
        omitted_candidates: list[dict] = []
        main_pool: list[dict] = []
        edge_pool: list[dict] = []

        for category in sorted(categories, key=self.scorer.category_score, reverse=True):
            main_count = 0
            for item in sorted(category.get("items", []), key=self.scorer.editorial_score_item, reverse=True):
                if item["kind"] == "edge":
                    if not self.scorer.should_keep_edge_item(item):
                        summary = self.candidate_summary(item, "weak edge evidence")
                        category["dropped"].append(summary)
                        omitted_candidates.append(summary)
                        continue
                    edge_pool.append(item)
                    continue
                if self.scorer.editorial_score_item(item) <= 0:
                    summary = self.candidate_summary(item, "low editorial score")
                    category["dropped"].append(summary)
                    omitted_candidates.append(summary)
                    continue
                if main_count >= budget.max_main_per_category:
                    summary = self.candidate_summary(item, "category main item cap")
                    category["dropped"].append(summary)
                    omitted_candidates.append(summary)
                    continue
                main_count += 1
                main_pool.append(item)

        selected_main, duplicate_main = self._dedupe_and_limit(
            sorted(main_pool, key=self.scorer.editorial_score_item, reverse=True),
            budget.main_target,
            "duplicate topic",
        )
        selected_edges, duplicate_edges = self._dedupe_and_limit(
            sorted(edge_pool, key=self.scorer.editorial_score_item, reverse=True),
            budget.edge_target,
            "duplicate edge topic",
        )
        omitted_candidates.extend(duplicate_main)
        omitted_candidates.extend(duplicate_edges)

        selected_ids = {item["item_id"] for item in selected_main + selected_edges}
        for category in categories:
            for item in category.get("items", []):
                if item["item_id"] not in selected_ids:
                    summary = self.candidate_summary(item, "outside final reconcile budget")
                    category["dropped"].append(summary)
                    omitted_candidates.append(summary)

        return ReconciledPlanItems(
            selected_main=selected_main[:budget.main_target],
            selected_edges=selected_edges[:budget.edge_target],
            omitted_candidates=omitted_candidates,
        )

    def _dedupe_and_limit(
        self,
        items: list[dict],
        limit: int,
        duplicate_reason: str,
    ) -> tuple[list[dict], list[dict]]:
        selected: list[dict] = []
        selected_topics: set[str] = set()
        dropped_duplicates: list[dict] = []
        for item in items:
            topic = item.get("topic_key") or item["item_id"]
            if topic in selected_topics:
                dropped_duplicates.append(self.candidate_summary(item, duplicate_reason))
                continue
            selected_topics.add(topic)
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected, dropped_duplicates

    def candidate_summary(self, candidate: dict, reason: str) -> dict:
        return {
            "title": candidate.get("title_hint", ""),
            "source": ", ".join(candidate.get("sources", [])),
            "date": ", ".join(candidate.get("dates", [])),
            "article_id": (candidate.get("article_ids") or [None])[0],
            "cluster_id": candidate.get("cluster_id"),
            "reason": reason,
        }


class CategoryGroupingPolicy:
    """Group selected report items into final dynamic categories."""

    def __init__(self, scorer: EditorialEvidenceScorer | None = None):
        self.scorer = scorer or EditorialEvidenceScorer()

    def group_selected(self, items: list[dict], max_categories: int) -> list[dict]:
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for item in items:
            dimension = self.item_dimension(item)
            key = dimension or "general"
            if key not in grouped:
                category_id = _make_category_id(key, len(order) + 1)
                grouped[key] = {
                    "category_id": category_id,
                    "label": DIMENSION_LABELS.get(key, _clean_title(key.replace("_", " "), "综合信号")),
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
        return sorted(categories, key=self.scorer.category_score, reverse=True)[:max_categories]

    def item_dimension(self, item: dict) -> str:
        evidence = item.get("evidence") or []
        if evidence:
            return str(evidence[0].get("query_dimension") or "general")
        return "general"


_DEFAULT_SCORER = EditorialEvidenceScorer()


def article_source(article: dict) -> str:
    return _DEFAULT_SCORER.article_source(article)


def article_text(article: dict) -> str:
    return _DEFAULT_SCORER.article_text(article)


def is_background_article(article: dict) -> bool:
    return _DEFAULT_SCORER.is_background_article(article)


def is_storage_relevant(article: dict) -> bool:
    return _DEFAULT_SCORER.is_storage_relevant(article)


def is_edge_signal_text(text: str) -> bool:
    return _DEFAULT_SCORER.is_edge_signal_text(text)


def article_rank(article: dict) -> tuple:
    return _DEFAULT_SCORER.article_rank(article)


def editorial_score_text(text: str) -> int:
    return _DEFAULT_SCORER.editorial_score_text(text)


def editorial_score_article(article: dict) -> int:
    return _DEFAULT_SCORER.editorial_score_article(article)


def editorial_score_item(item: dict) -> int:
    return _DEFAULT_SCORER.editorial_score_item(item)


def cluster_score(cluster: dict) -> tuple:
    return _DEFAULT_SCORER.cluster_score(cluster)


def category_score(category: dict) -> tuple:
    return _DEFAULT_SCORER.category_score(category)


def _make_category_id(seed: str, index: int) -> str:
    digest = hashlib.sha1(f"category|{seed}|{index}".encode("utf-8")).hexdigest()[:10]
    return f"cat-{index:02d}-{digest}"


def _clean_title(title: str, fallback: str = "Untitled item") -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    title = title.replace("...", "").strip(" -")
    return title[:110] or fallback
