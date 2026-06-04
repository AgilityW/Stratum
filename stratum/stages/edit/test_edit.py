"""Tests for edit-stage output parsing and block editing."""
import json

from stratum.stages.edit.boilerplate import artifact_boilerplate_violations, build_boilerplate_rules
from stratum.stages.edit.block_policy import BlockOutputPolicy
from stratum.stages.edit.edit import (
    apply_evidence_window_budget,
    item_count_within_budget,
    markdown_news_titles,
    normalize_structured_data,
    normalize_edge_signal_headings,
    resolve_domain_title,
    run_block_edit,
    should_write_event_threads,
    split_llm_output,
    structured_event_counts,
    strip_source_locale_tags,
)
from stratum.stages.edit.output_policy import EditOutputPolicy
from stratum.stages.edit.validate_repair import repair_briefing_from_validate_report
from stratum.stages.edit.planner import ReportPlanner, build_block_plan, clean_evidence_text, item_topic_key
from stratum.stages.edit.planning_policy import (
    CategoryCandidatePolicy,
    CategoryGroupingPolicy,
    EditorialEvidenceScorer,
    ItemBudgetPolicy,
    PlanReconciliationPolicy,
)
from stratum.stages.edit.profile_policy import ProfilePolishPolicy
from stratum.stages.edit.renderer import EditRenderer
from stratum.stages.edit.source_alignment import SourceAlignmentMatcher
from stratum.stages.edit.source_repair import (
    _article_source_label,
    prune_unsupported_edge_items,
    repair_validate_failures,
    repair_missing_source_lines,
    repair_source_line_dates,
    stabilize_generated_items,
    soften_overclaim_language,
)
from stratum.stages.edit.structured_output import DeterministicStructuredOutputBuilder


def _fake_article(article_id, title, source="example.com", source_type="media", snippet=None):
    return {
        "id": article_id,
        "title": title,
        "source": source,
        "published_at": "2026-05-30",
        "snippet": snippet or title,
        "source_type": source_type,
        "url": f"https://{source}/{article_id}",
        "entities": ["Samsung"],
        "terms": ["HBM4"],
    }


def test_source_labels_strip_only_known_presentation_prefixes():
    article = {"url": "https://ww2.example.com/news"}
    assert _article_source_label(article) == "ww2.example.com"

    mobile_article = {"url": "https://m.reuters.com/technology"}
    assert _article_source_label(mobile_article) == "reuters.com"


def test_soften_overclaim_language_dampens_strong_causal_phrases():
    markdown = (
        "### Foo\n\n"
        "这标志着行业转折，企业双双推动IPO，并由需求激增推动股价。\n\n"
        "*example.com · 2026年6月1日*\n"
    )

    softened = soften_overclaim_language(markdown)

    assert "这反映出行业转折" in softened
    assert "推进IPO" in softened
    assert "带动股价" in softened


def test_prune_unsupported_edge_items_drops_unaligned_edge_signal():
    markdown = """## 产业信号

### 【边缘信号】不匹配的条目

这条正文和引用来源完全对不上。

*markets.chroniclejournal.com · 2026年6月1日*
"""
    articles = [
        {
            "title": "Another topic entirely",
            "snippet": "No overlap here",
            "source": "markets.chroniclejournal.com",
            "url": "https://markets.chroniclejournal.com/story",
        }
    ]

    repaired = prune_unsupported_edge_items(markdown, articles)

    assert "【边缘信号】不匹配的条目" not in repaired
    assert "markets.chroniclejournal.com" not in repaired


def test_block_fallback_paragraphs_do_not_embed_raw_markdown_snippets():
    policy = BlockOutputPolicy()

    paragraphs = policy.fallback_paragraphs({
        "kind": "main",
        "title_hint": "国产存储双雄长鑫存储和长江存储冲刺上市",
        "evidence": [
            {"snippet": "## CFM闪存市场\n\n# 超长原文\n\n这段原文不应该直接进入 fallback。"}
        ],
    })

    assert paragraphs[0] == "该来源围绕“国产存储双雄长鑫存储和长江存储冲刺上市”提供了当日增量信息。"
    assert "##" not in paragraphs[0]


def test_stabilize_generated_items_rewrites_edge_and_risky_bodies():
    markdown = """## 行业要点

### AI驱动的存储供给危机

由于AI需求激增，供应协议锁定产能并导致供给危机升级。

*example.com · 2026年6月1日*

## 产业信号

### 【边缘信号】西部数据深潜

营收增长与投资价值分歧正在扩大。

*markets.example.com · 2026年6月1日*
"""

    repaired = stabilize_generated_items(markdown)

    assert "当前证据更适合支持趋势跟踪，而不是直接下单一结论" in repaired
    assert "这个信号值得观察，但目前仍以单点证据为主" in repaired
    assert "营收增长与投资价值分歧正在扩大。" not in repaired


def test_repair_validate_failures_rewrites_overclaim_to_article_title():
    markdown = """## 行业要点

### 三星、SK海力士将内存价格上调30%，长期供应协议锁定高利润

长期供应协议的盛行表明大客户对供应安全的担忧，也锁定了未来的价格上涨期望。

*trendforce.com · 2026年6月1日*
"""
    articles = [
        {
            "title": "[News] Samsung, SK hynix Reportedly Lift Memory Prices Up to 30%; Long-Term Supply Deals in Play",
            "snippet": "TrendForce news roundup on reported pricing moves.",
            "source": "trendforce.com",
            "source_domain": "trendforce.com",
            "published_at": "2026-06-01",
            "quality_flags": [],
        }
    ]

    repaired = repair_validate_failures(markdown, articles, "2026-06-01", {})

    assert "三星、SK海力士将内存价格上调30%" not in repaired
    assert "[News] Samsung, SK hynix Reportedly Lift Memory Prices Up to 30%; Long-Term Supply Deals in Play" in repaired
    assert "当前证据更适合支持趋势跟踪，而不是直接下单一结论" in repaired


def test_repair_validate_failures_drops_unsupported_edge_item_without_fresh_support():
    markdown = """## 产业信号

### 【边缘信号】AI存储超级周期研报梳理西部数据受益逻辑与贸易法风险

该条目存在来源不对齐问题。

*markets.chroniclejournal.com · 2026年6月1日*
"""
    articles = [
        {
            "title": "User | chroniclejournal.com - The AI Storage Supercycle",
            "snippet": "Background-style research note.",
            "source": "markets.chroniclejournal.com",
            "source_domain": "markets.chroniclejournal.com",
            "published_at": "2026-06-01",
            "quality_flags": ["BACKGROUND_NO_DATE"],
        }
    ]

    repaired = repair_validate_failures(markdown, articles, "2026-06-01", {})

    assert "AI存储超级周期研报梳理西部数据受益逻辑与贸易法风险" not in repaired


def test_validate_repair_returns_structured_repair_report():
    markdown = """## 行业要点

### 三星、SK海力士将内存价格上调30%

长期供应协议意味着价格已经确认进入上行通道。

*trendforce.com · 2026年6月1日*
"""
    articles = [
        {
            "id": "a1",
            "title": "[News] Samsung, SK hynix Reportedly Lift Memory Prices Up to 30%; Long-Term Supply Deals in Play",
            "snippet": "TrendForce reported pricing moves and long-term supply deals.",
            "source": "trendforce.com",
            "source_domain": "trendforce.com",
            "published_at": "2026-06-01",
            "quality_flags": [],
            "source_type": "media",
        }
    ]
    validate_report = {
        "status": "violations",
        "violations": 1,
        "details": [{
            "item": 1,
            "kind": "item",
            "title": "三星、SK海力士将内存价格上调30%",
            "sources": ["trendforce.com"],
            "date": "2026年6月1日",
            "violations": ["OVERCLAIM: reported_signal_overstated_as_confirmed"],
        }],
    }

    repaired, repair_report = repair_briefing_from_validate_report(
        markdown,
        articles,
        validate_report,
        "2026-06-01",
        {},
    )

    assert "Reportedly Lift Memory Prices Up to 30%" in repaired
    assert repair_report["rewritten_items"] == 1
    assert repair_report["dropped_items"] == 0
    assert repair_report["item_actions"][0]["action"] == "rewrite"


def test_split_llm_output_accepts_valid_structured_data():
    response = """# Briefing

Body

---DATA---
{"causal_edges": [], "judgments": [{"id": "j1"}]}
"""
    briefing, data = split_llm_output(response)
    assert briefing == "# Briefing\n\nBody"
    assert data == {"causal_edges": [], "judgments": [{"id": "j1"}]}


def test_split_llm_output_ignores_invalid_structured_data():
    response = """# Briefing

Body

---DATA---
```json
{"causal_edges": [
```
"""
    briefing, data = split_llm_output(response)
    assert briefing == "# Briefing\n\nBody"
    assert data is None


def test_build_block_plan_creates_dynamic_categories():
    articles = [
        _fake_article("a1", "Samsung HBM4 sample shipment with customer certification", "samsung.com", "official"),
        _fake_article("a2", "DRAM price shortage extends into 2027", "market.example", "analyst"),
        _fake_article("a3", "WD appoints Manuvir Das to board", "westerndigital.com", "official"),
    ]
    articles[0]["query_dimension"] = "technology"
    articles[1]["query_dimension"] = "market_pricing"
    articles[2]["query_dimension"] = "company_strategy"
    clusters = {
        "clusters": [
            {
                "id": "c1",
                "canonical_title": "Samsung HBM4 sample shipment with customer certification",
                "confidence": "high",
                "article_ids": ["a1"],
                "article_count": 1,
                "source_types": ["official"],
            },
            {
                "id": "c2",
                "canonical_title": "DRAM price shortage extends into 2027",
                "confidence": "high",
                "article_ids": ["a2"],
                "article_count": 1,
                "source_types": ["analyst"],
            },
        ]
    }

    plan = build_block_plan(
        articles,
        clusters,
        {},
        "2026-05-30",
        {"target_main_items": 2, "target_edge_items": 1, "evidence_articles_per_item": 2, "max_categories": 4},
    )

    assert plan["mode"] == "block_edit"
    assert plan["counts"]["categories"] >= 2
    assert all(category["role"] == "dynamic_content_category" for category in plan["categories"])
    assert plan["counts"]["main_items"] == 2
    assert plan["counts"]["edge_items"] == 1
    assert plan["items"][0]["category_id"].startswith("cat-")


def test_report_planner_and_budget_policy_own_plan_entrypoint():
    budget = ItemBudgetPolicy().resolve({"main_max_items": 3, "edge_min_items": 2})

    assert budget.main_target == 3
    assert budget.edge_target == 5
    assert budget.total_target == 8
    assert budget.max_categories == 12

    article = _fake_article(
        "a1",
        "Samsung HBM4 customer certification and production capacity",
        "samsung.com",
        "official",
    )
    article["query_dimension"] = "technology"
    plan = ReportPlanner().build_block_plan(
        [article],
        {"clusters": []},
        {},
        "2026-05-30",
        {"target_main_items": 1, "target_edge_items": 0, "max_categories": 2},
    )

    assert plan["budgets"]["main_target"] == 1
    assert plan["counts"]["main_items"] == 1
    assert plan["categories"][0]["dimension"] == "technology"


def test_editorial_evidence_scorer_owns_planning_scores():
    scorer = EditorialEvidenceScorer()
    official = _fake_article(
        "a1",
        "Samsung HBM4 certification and production capacity",
        "samsung.com",
        "official",
        snippet="Customer qualification, shipment, and yield signals.",
    )
    low_signal = _fake_article(
        "a2",
        "HBM glossary and history",
        "example.com",
        "blog",
        snippet="A basic definition timeline video.",
    )

    assert scorer.editorial_score_article(official) > scorer.editorial_score_article(low_signal)
    assert scorer.article_rank(official) < scorer.article_rank(low_signal)
    assert scorer.cluster_score({"confidence": "high", "source_types": ["official"], "article_count": 3}) > (
        scorer.cluster_score({"confidence": "low", "source_types": ["media"], "article_count": 1})
    )


def test_plan_reconciliation_policy_selects_budgeted_unique_items():
    budget = ItemBudgetPolicy().resolve({
        "target_main_items": 1,
        "target_edge_items": 1,
        "max_main_per_category": 1,
    })
    categories = [{
        "index": 1,
        "items": [
            {
                "item_id": "main-1",
                "kind": "main",
                "title_hint": "Samsung HBM4 certification",
                "sources": ["samsung.com"],
                "dates": ["2026-05-30"],
                "article_ids": ["a1"],
                "topic_key": "samsung-hbm4",
                "editorial_score": 10,
                "evidence": [],
            },
            {
                "item_id": "main-2",
                "kind": "main",
                "title_hint": "Samsung HBM4 second item",
                "sources": ["example.com"],
                "dates": ["2026-05-30"],
                "article_ids": ["a2"],
                "topic_key": "samsung-hbm4",
                "editorial_score": 9,
                "evidence": [],
            },
            {
                "item_id": "edge-1",
                "kind": "edge",
                "title_hint": "Western Digital board signal",
                "sources": ["wd.com"],
                "dates": ["2026-05-30"],
                "article_ids": ["a3"],
                "topic_key": "wd-board",
                "editorial_score": 1,
                "evidence": [{
                    "title": "Western Digital board signal",
                    "snippet": "Board appointment may influence storage strategy.",
                    "source_type": "media",
                    "quality_flags": [],
                }],
            },
        ],
        "dropped": [],
    }]

    result = PlanReconciliationPolicy().reconcile(categories, budget)

    assert [item["item_id"] for item in result.selected_main] == ["main-1"]
    assert [item["item_id"] for item in result.selected_edges] == ["edge-1"]
    assert any(item["reason"] == "category main item cap" for item in result.omitted_candidates)
    assert categories[0]["dropped"]


def test_item_topic_key_dedupes_same_title_across_articles():
    item_a = {"item_id": "main-1", "title_hint": "[News] Samsung, SK hynix Reportedly Lift Memory Prices Up to 30%", "article_ids": ["a1"]}
    item_b = {"item_id": "main-2", "title_hint": "Samsung, SK hynix Lift Memory Prices Up to 30%", "article_ids": ["a2"]}

    assert item_topic_key(item_a) == item_topic_key(item_b)


def test_plan_reconciliation_policy_drops_weak_edge_items():
    budget = ItemBudgetPolicy().resolve({
        "target_main_items": 0,
        "target_edge_items": 1,
    })
    categories = [{
        "index": 1,
        "items": [
            {
                "item_id": "edge-weak",
                "kind": "edge",
                "title_hint": "Western Digital rumor thread",
                "sources": ["rumor.example"],
                "dates": ["2026-05-30"],
                "article_ids": ["a1"],
                "topic_key": "wd-rumor",
                "editorial_score": 2,
                "evidence": [{
                    "title": "Western Digital rumor thread",
                    "snippet": "A speculative blog post.",
                    "source_type": "blog",
                    "quality_flags": [],
                }],
            },
        ],
        "dropped": [],
    }]

    result = PlanReconciliationPolicy().reconcile(categories, budget)

    assert result.selected_edges == []
    assert any(item["reason"] == "weak edge evidence" for item in result.omitted_candidates)


def test_category_grouping_policy_owns_selected_item_grouping():
    items = [
        {
            "item_id": "item-tech",
            "kind": "main",
            "title_hint": "Samsung HBM4 certification",
            "editorial_score": 12,
            "evidence": [{"query_dimension": "technology", "title": "Samsung HBM4 certification"}],
        },
        {
            "item_id": "item-market",
            "kind": "main",
            "title_hint": "DRAM pricing",
            "editorial_score": 4,
            "evidence": [{"query_dimension": "market_pricing", "title": "DRAM pricing"}],
        },
    ]

    categories = CategoryGroupingPolicy().group_selected(items, max_categories=1)

    assert len(categories) == 1
    assert categories[0]["dimension"] == "technology"
    assert categories[0]["label"] == "技术路线与产品节点"
    assert items[0]["category_id"] == categories[0]["category_id"]
    assert items[0]["category_label"] == categories[0]["label"]


def test_category_candidate_policy_selects_clusters_and_unclustered_articles():
    policy = CategoryCandidatePolicy()
    articles = [
        _fake_article(
            "a1",
            "Samsung HBM4 production capacity",
            "samsung.com",
            "official",
            snippet="Production capacity and customer certification.",
        ),
        _fake_article(
            "a2",
            "Western Digital board signal",
            "wd.com",
            "official",
            snippet="Board appointment signal.",
        ),
        _fake_article(
            "a3",
            "HBM glossary history",
            "example.com",
            "blog",
            snippet="Definition timeline video.",
        ),
    ]
    article_by_id = {article["id"]: article for article in articles}
    clusters = {
        "clusters": [
            {"id": "c-low", "canonical_title": "HBM glossary", "confidence": "low", "article_ids": ["a3"]},
            {
                "id": "c-high",
                "canonical_title": "Samsung HBM4 production capacity",
                "confidence": "high",
                "source_types": ["official"],
                "article_ids": ["a1"],
                "article_count": 1,
            },
        ]
    }
    budget = ItemBudgetPolicy().resolve({"target_main_items": 1, "target_edge_items": 1})

    assert policy.sorted_clusters(clusters)[0]["id"] == "c-high"
    assert [article["id"] for article in policy.evidence_articles(["a1", "a3"], article_by_id, limit=2)] == ["a1", "a3"]
    assert policy.article_kind(articles[1]) == "edge"
    assert [article["id"] for article in policy.unclustered_candidates(articles, {"a1"}, budget)] == ["a2"]


def test_block_output_policy_normalizes_block_response_and_missing_items():
    policy = BlockOutputPolicy()
    category = {
        "category_id": "cat-technology",
        "label": "技术路线与产品节点",
        "why_created": "selected technology stories",
        "dropped": [{"item_id": "dropped-1", "reason": "budget"}],
        "items": [
            {
                "item_id": "main-1",
                "kind": "main",
                "title_hint": "Samsung HBM4 certification",
                "reason": "official sample signal",
                "evidence": [{"title": "Samsung HBM4", "snippet": "Samsung HBM4 certification progress."}],
            },
            {
                "item_id": "edge-1",
                "kind": "edge",
                "title_hint": "WD board signal",
                "reason": "edge signal",
                "evidence": [{"title": "WD board", "snippet": "董事会任命信号。"}],
            },
        ],
    }

    payload = policy.category_payload(category, {"main-1"})
    block = policy.normalize_response(
        {
            "label": "技术节点",
            "items": [
                {
                    "item_id": "main-1",
                    "title": "Samsung HBM4 qualification",
                    "paragraphs": "正文。\n\n扫码关注我们\n\n#### 报价中心",
                },
                {"item_id": "unknown", "title": "ignore", "paragraphs": ["ignore"]},
            ],
        },
        category,
        category["items"],
    )

    assert [item["item_id"] for item in payload["items"]] == ["main-1"]
    assert block["status"] == "ok"
    assert block["items"][0]["paragraphs"] == ["正文。"]
    assert block["items"][1]["item_id"] == "edge-1"
    assert block["items"][1]["_fallback"] == "missing_from_llm"


def test_block_output_policy_invalid_json_uses_fallback_block():
    policy = BlockOutputPolicy()
    category = {
        "category_id": "cat-market",
        "label": "市场价格与供需",
        "items": [{
            "item_id": "main-1",
            "kind": "main",
            "title_hint": "DRAM pricing",
            "evidence": [{"snippet": "DRAM pricing signal."}],
        }],
        "dropped": [],
    }

    block = policy.normalize_response(None, category, category["items"])

    assert block["status"] == "fallback"
    assert block["detail"] == "invalid_json"
    assert block["items"][0]["_fallback"] == "invalid_json"


def test_profile_polish_policy_normalizes_sections_and_payload():
    policy = ProfilePolishPolicy()
    titles = ["Samsung HBM4 certification", "【边缘信号】WD board signal"]

    payload = policy.user_payload(titles)
    sections = policy.normalize_sections(
        {
            "summary": "HBM remains the main thread.",
            "focus": ["Certification", "", "Supply"],
            "contrarian": None,
        },
        titles,
    )

    assert payload["items"][0]["kind"] == "main"
    assert payload["items"][1]["kind"] == "edge"
    assert sections["summary"] == ["HBM remains the main thread.", policy.fallback_summary(titles)[0]]
    assert sections["focus"] == ["Certification", "Supply", policy.fallback_focus(titles)[0]]
    assert sections["contrarian"] == policy.fallback_contrarian(titles)


def test_profile_polish_policy_builds_deterministic_sections_from_items():
    policy = ProfilePolishPolicy()
    sections = policy.deterministic_sections(
        [
            {"kind": "main", "title_hint": "HBM4成本激增，溢价超30%"},
            {"kind": "main", "title_hint": "AI数据中心吞噬全球存储产能"},
            {"kind": "edge", "title_hint": "【边缘信号】Western Digital股价走势映射存储行业宏观敏感度"},
        ],
        [{"title": "市场评论站个股解读", "reason": "weak edge evidence"}],
    )

    assert sections["summary"][0] == "今日主线集中在 HBM4成本激增，溢价超30%。"
    assert sections["focus"][0] == "HBM4成本激增，溢价超30%"
    assert "Western Digital股价走势映射存储行业宏观敏感度" in sections["contrarian"][0]


def test_edit_renderer_owns_block_and_profile_markdown(tmp_path):
    (tmp_path / "daily.md").write_text(
        "# {{ title }}\n\n{{ date_label }}\n\n{{ summary }}\n\n{{ main_categories }}\n\n{{ edge_items }}\n\n{{ focus }}\n\n{{ contrarian }}\n",
        encoding="utf-8",
    )
    renderer = EditRenderer(str(tmp_path), BlockOutputPolicy())
    plan = {
        "categories": [{
            "category_id": "cat-technology",
            "label": "技术路线与产品节点",
            "items": [{"item_id": "main-1"}, {"item_id": "edge-1"}],
        }],
        "items": [
            {
                "item_id": "main-1",
                "kind": "main",
                "title_hint": "Samsung HBM4 certification",
                "sources": ["samsung.com"],
                "dates": ["2026-05-30"],
                "evidence": [_fake_article("a1", "Samsung HBM4 certification", "samsung.com", "official")],
            },
            {
                "item_id": "edge-1",
                "kind": "edge",
                "title_hint": "WD board signal",
                "sources": ["westerndigital.com"],
                "dates": ["2026-05-30"],
                "evidence": [_fake_article("a2", "WD board signal", "westerndigital.com", "official")],
            },
        ],
    }
    blocks = [{
        "category_id": "cat-technology",
        "label": "技术节点",
        "items": [
            {"item_id": "main-1", "title": "Samsung HBM4 certification", "paragraphs": ["客户认证进展。"]},
            {"item_id": "edge-1", "title": "WD board signal", "paragraphs": ["董事会任命。"]},
        ],
    }]

    main_markdown, edge_markdown = renderer.assemble_block_markdown(plan, blocks, "2026-05-30")
    briefing = renderer.assemble_profile_markdown(
        "存储早报",
        "2026-05-30",
        "daily.md",
        {
            "summary": ["主线判断。"],
            "focus": ["认证节奏"],
            "contrarian": ["需求转弱"],
        },
        main_markdown,
        edge_markdown,
    )

    assert "## 技术节点" in main_markdown
    assert "### Samsung HBM4 certification" in main_markdown
    assert "*samsung.com · 2026年5月30日*" in main_markdown
    assert "### 【边缘信号】WD board signal" in edge_markdown
    assert "2026年5月30日 · 周六" in briefing
    assert "- 认证节奏" in briefing


def test_run_block_edit_uses_template_and_category_blocks(monkeypatch, tmp_path):
    articles = [
        _fake_article("a1", "Samsung HBM4 sample shipment with customer certification", "samsung.com", "official"),
        _fake_article("a2", "DRAM price shortage extends into 2027", "market.example", "analyst"),
        _fake_article("a3", "WD appoints Manuvir Das to board", "westerndigital.com", "official"),
    ]
    articles[0]["query_dimension"] = "technology"
    articles[1]["query_dimension"] = "market_pricing"
    articles[2]["query_dimension"] = "company_strategy"
    clusters = {
        "clusters": [
            {
                "id": "c1",
                "canonical_title": "Samsung HBM4 sample shipment with customer certification",
                "confidence": "high",
                "article_ids": ["a1"],
                "article_count": 1,
                "source_types": ["official"],
            },
            {
                "id": "c2",
                "canonical_title": "DRAM price shortage extends into 2027",
                "confidence": "high",
                "article_ids": ["a2"],
                "article_count": 1,
                "source_types": ["analyst"],
            },
        ]
    }

    def fake_call_llm(system_prompt, user_prompt, llm_cfg):
        if "summary" in system_prompt:
            return json.dumps({
                "summary": ["HBM and pricing are both active."],
                "focus": ["HBM certification", "DRAM supply", "Edge validation"],
                "contrarian": ["Demand may weaken", "Certification may slip", "Evidence may be early"],
            })
        payload = json.loads(user_prompt)
        return json.dumps({
            "category_id": payload["category_id"],
            "label": payload["label"],
            "items": [
                {
                    "item_id": item["item_id"],
                    "title": item["title_hint"],
                    "paragraphs": [item["evidence"][0]["snippet"], "This matters for storage market structure."],
                }
                for item in payload["items"]
            ],
            "dropped": [],
        })

    monkeypatch.setattr("stratum.stages.edit.edit.call_llm", fake_call_llm)
    args = type("Args", (), {
        "date": "2026-05-30",
        "domain": "storage",
        "timescale": "daily",
        "output": str(tmp_path / "briefing.md"),
    })()

    briefing, structured, artifacts = run_block_edit(
        args,
        "存储早报",
        articles,
        clusters,
        {},
        {"api_key": "fake"},
        {"_budget": {
            "target_main_items": 2,
            "target_edge_items": 1,
            "min_items": 3,
            "max_items": 3,
            "main_min_items": 2,
            "main_max_items": 2,
            "edge_min_items": 1,
            "edge_max_items": 1,
            "block_parallelism": 1,
            "max_categories": 4,
        }},
        {"system": {"template": "daily.md"}},
    )

    assert "## 行业要点" in briefing
    assert "## 产业信号" in briefing
    assert "## 特别关注" in briefing
    assert "### Samsung HBM4 sample shipment" in briefing
    assert "### 【边缘信号】WD appoints Manuvir Das to board" in briefing
    assert artifacts["plan"]["version"] == 3
    assert artifacts["trace"]["mode"] == "block_edit"
    assert structured["threads"]


def test_clean_evidence_text_removes_site_boilerplate():
    text = """正文第一段。

#### 推荐：电脑用的少，手机扫一扫，资讯快一步！

扫码关注我们

#### 标签:

#### 报价中心

#### 简讯快报

不应进入日报的后续站点内容。
"""

    cleaned = clean_evidence_text(text)

    assert cleaned == "正文第一段。"
    assert "扫码关注我们" not in cleaned
    assert "报价中心" not in cleaned
    assert "简讯快报" not in cleaned


def test_source_specific_boilerplate_rules_are_config_driven():
    rules = build_boilerplate_rules({
        "source_rules": [{
            "domains": ["chinaflashmarket.com"],
            "cut_markers": ["#### 报价中心"],
            "line_patterns": [r"^#{2,6}\s*简讯快报\s*$"],
        }]
    })

    cfm_text = "正文。\n\n#### 报价中心\n\n模板内容"
    other_text = "正文。\n\n#### 报价中心\n\n模板内容"

    assert clean_evidence_text(cfm_text, source="chinaflashmarket.com", rules=rules) == "正文。"
    assert "报价中心" in clean_evidence_text(other_text, source="example.com", rules=rules)
    assert artifact_boilerplate_violations(cfm_text, rules=rules)


def test_run_block_edit_strips_boilerplate_from_generated_paragraphs(monkeypatch, tmp_path):
    articles = [_fake_article(
        "a1",
        "存储现货结构性分化",
        "chinaflashmarket.com",
        "analyst",
        snippet="渠道市场正文。\n\n扫码关注我们\n\n#### 报价中心",
    )]
    articles[0]["query_dimension"] = "market_pricing"
    clusters = {"clusters": [{
        "id": "c1",
        "canonical_title": "存储现货结构性分化",
        "confidence": "high",
        "article_ids": ["a1"],
        "article_count": 1,
        "source_types": ["analyst"],
    }]}

    def fake_call_llm(system_prompt, user_prompt, llm_cfg):
        if "summary" in system_prompt:
            return json.dumps({
                "summary": ["渠道市场正文。"],
                "focus": ["价格验证", "供应验证", "需求验证"],
                "contrarian": ["需求可能转弱", "价格可能回落", "证据仍需确认"],
            })
        payload = json.loads(user_prompt)
        return json.dumps({
            "category_id": payload["category_id"],
            "label": payload["label"],
            "items": [{
                "item_id": payload["items"][0]["item_id"],
                "title": "存储现货结构性分化",
                "paragraphs": [
                    "扫码关注我们\n\n#### 标签:\n\n#### 报价中心\n\n#### 简讯快报",
                    "渠道市场正文。\n\n扫码关注我们",
                ],
            }],
            "dropped": [],
        })

    monkeypatch.setattr("stratum.stages.edit.edit.call_llm", fake_call_llm)
    args = type("Args", (), {
        "date": "2026-05-30",
        "domain": "storage",
        "timescale": "daily",
        "output": str(tmp_path / "briefing.md"),
    })()

    briefing, _structured, artifacts = run_block_edit(
        args,
        "存储早报",
        articles,
        clusters,
        {},
        {"api_key": "fake"},
        {
            "_domain_cfg": {
                "pipeline": {
                    "boilerplate": {
                        "source_rules": [{
                            "domains": ["chinaflashmarket.com"],
                            "cut_markers": ["#### 报价中心", "#### 简讯快报"],
                            "line_patterns": [r"^#{2,6}\s*标签:?\s*$"],
                        }]
                    }
                }
            },
            "_budget": {
                "target_main_items": 1,
                "target_edge_items": 0,
                "min_items": 1,
                "max_items": 1,
                "main_min_items": 1,
                "main_max_items": 1,
                "edge_min_items": 0,
                "edge_max_items": 0,
                "block_parallelism": 1,
                "max_categories": 1,
            },
        },
        {"system": {"template": "daily.md"}},
    )

    assert "渠道市场正文。" in briefing
    assert "扫码关注我们" not in briefing
    assert "#### 标签" not in briefing
    assert "#### 报价中心" not in briefing
    assert "#### 简讯快报" not in briefing
    assert artifacts["trace"]["boilerplate_quality"]["briefing_violations"] == 0


def test_run_block_edit_can_render_weekly_template(monkeypatch, tmp_path):
    articles = [
        _fake_article("a1", "DRAM price shortage extends into 2027", "market.example", "analyst"),
        _fake_article("a2", "Samsung HBM4 sample shipment with customer certification", "samsung.com", "official"),
    ]
    articles[0]["query_dimension"] = "market_pricing"
    articles[1]["query_dimension"] = "technology"
    clusters = {
        "clusters": [
            {
                "id": "c1",
                "canonical_title": "DRAM price shortage extends into 2027",
                "confidence": "high",
                "article_ids": ["a1"],
                "article_count": 1,
                "source_types": ["analyst"],
            },
            {
                "id": "c2",
                "canonical_title": "Samsung HBM4 sample shipment with customer certification",
                "confidence": "high",
                "article_ids": ["a2"],
                "article_count": 1,
                "source_types": ["official"],
            },
        ]
    }

    def fake_call_llm(system_prompt, user_prompt, llm_cfg):
        if "summary" in system_prompt:
            return json.dumps({
                "summary": ["Weekly trend summary."],
                "focus": ["Next week price checks", "HBM certification", "Supply gap"],
                "contrarian": ["Demand risk", "Certification risk", "Supply response"],
            })
        payload = json.loads(user_prompt)
        return json.dumps({
            "category_id": payload["category_id"],
            "label": payload["label"],
            "items": [
                {
                    "item_id": item["item_id"],
                    "title": item["title_hint"],
                    "paragraphs": [item["evidence"][0]["snippet"], "This changes the weekly trend read."],
                }
                for item in payload["items"]
            ],
            "dropped": [],
        })

    monkeypatch.setattr("stratum.stages.edit.edit.call_llm", fake_call_llm)
    args = type("Args", (), {
        "date": "2026-05-30",
        "domain": "storage",
        "timescale": "weekly",
        "output": str(tmp_path / "weekly.md"),
    })()

    briefing, _structured, artifacts = run_block_edit(
        args,
        "存储周报",
        articles,
        clusters,
        {},
        {"api_key": "fake"},
        {"_budget": {
            "target_main_items": 2,
            "target_edge_items": 0,
            "min_items": 2,
            "max_items": 2,
            "main_min_items": 2,
            "main_max_items": 2,
            "edge_min_items": 0,
            "edge_max_items": 0,
            "block_parallelism": 1,
            "max_categories": 4,
        }},
        {"system": {"template": "weekly.md"}},
    )

    assert "### 本周结论" in briefing
    assert "## 趋势变化" in briefing
    assert "## 特别关注" in briefing
    assert "每日 7:30" not in briefing
    assert artifacts["trace"]["timescale"] == "weekly"


def test_strip_source_locale_tags_only_on_source_lines():
    md = """### Item

Body mentions [en] in prose.

*Digitimes [en], cnstock.com [zh-CN] · 2026年5月30日*
"""
    cleaned = strip_source_locale_tags(md)
    assert "*Digitimes, cnstock.com · 2026年5月30日*" in cleaned
    assert "Body mentions [en] in prose." in cleaned


def test_strip_source_locale_tags_handles_case_variants():
    md = "*Digitimes [EN], cnstock.com [zh-cn], example.jp [zh-Hans-CN] · 2026年5月30日*"

    cleaned = strip_source_locale_tags(md)

    assert cleaned == "*Digitimes, cnstock.com, example.jp · 2026年5月30日*"


def test_normalize_structured_data_renames_judgment_mechanism():
    data = {
        "judgments": [
            {
                "target_type": "event_pair",
                "target_thread_ids": ["et-2026-001", "et-2026-002"],
                "mechanism": "HBM demand lifts memory margins.",
                "confidence": "B",
                "expected_verification": "2026-12-31",
            }
        ]
    }
    normalized = normalize_structured_data(data)
    assert normalized["judgments"][0]["hypothesis"] == "HBM demand lifts memory margins."
    assert "mechanism" not in normalized["judgments"][0]


def test_normalize_structured_data_assigns_stable_thread_ids():
    data = {
        "threads": [
            {
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
            }
        ]
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    thread = normalized["threads"][0]
    assert thread["thread_id"].startswith("et-storage-20260530-")
    assert thread["id"] == thread["thread_id"]


def test_normalize_structured_data_keeps_existing_thread_id_from_id():
    data = {
        "threads": [
            {
                "id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
            }
        ]
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert normalized["threads"][0]["thread_id"] == "et-storage-0001"
    assert normalized["threads"][0]["id"] == "et-storage-0001"


def test_normalize_structured_data_rewrites_cluster_ids_to_thread_ids():
    data = {
        "threads": [
            {"thread_id": "sc-storage-0001", "title": "Samsung HBM4"},
            {"thread_id": "sc-storage-0002", "title": "DRAM prices"},
        ],
        "causal_edges": [
            {
                "cause_thread_id": "sc-storage-0001",
                "effect_thread_id": "sc-storage-0002",
                "mechanism": "HBM capacity displaces commodity DRAM.",
                "confidence": "B",
            }
        ],
        "judgments": [
            {
                "target_type": "event_pair",
                "target_thread_ids": ["sc-storage-0001", "sc-storage-0002"],
                "hypothesis": "HBM capacity pressure keeps DRAM prices elevated.",
                "confidence": "B",
                "expected_verification": "2026-12-31",
            }
        ],
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    rewritten_ids = [thread["thread_id"] for thread in normalized["threads"]]
    assert all(thread_id.startswith("et-storage-20260530-") for thread_id in rewritten_ids)
    assert normalized["causal_edges"][0]["cause_thread_id"] == rewritten_ids[0]
    assert normalized["causal_edges"][0]["effect_thread_id"] == rewritten_ids[1]
    assert normalized["judgments"][0]["target_thread_ids"] == rewritten_ids


def test_normalize_structured_data_coerces_structured_arrays():
    data = {
        "threads": {"title": "Single thread"},
        "causal_edges": "not-json-array",
        "judgments": {"mechanism": "HBM demand lifts margins."},
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert len(normalized["threads"]) == 1
    assert normalized["causal_edges"] == []
    assert normalized["judgments"] == [{"hypothesis": "HBM demand lifts margins."}]


def test_normalize_structured_data_drops_incomplete_causal_edges():
    data = {
        "threads": [{"thread_id": "et-storage-0001", "title": "DRAM prices"}],
        "causal_edges": [
            {
                "cause_thread_id": "et-storage-0001",
                "effect_thread_id": None,
                "mechanism": "Demand destruction",
                "confidence": "B",
            },
            {
                "cause_thread_id": "et-storage-0001",
                "effect_thread_id": "et-storage-0002",
                "mechanism": "Capacity displacement",
                "confidence": "B",
            },
        ],
    }

    normalized = normalize_structured_data(data, "storage", "2026-05-30")

    assert len(normalized["causal_edges"]) == 1
    assert normalized["causal_edges"][0]["effect_thread_id"] == "et-storage-0002"


def test_threads_only_structured_data_is_written():
    data = {
        "threads": [
            {
                "thread_id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "watch_signals": ["Samsung HBM4 qualification"],
            }
        ],
        "causal_edges": [],
        "judgments": [],
    }

    assert should_write_event_threads(data)
    assert structured_event_counts(data) == {
        "threads": 1,
        "causal_edges": 0,
        "judgments": 0,
    }


def test_empty_structured_data_is_not_written():
    assert not should_write_event_threads({"threads": [], "causal_edges": [], "judgments": []})
    assert not should_write_event_threads(None)


def test_deterministic_structured_output_builder_uses_main_items_only():
    builder = DeterministicStructuredOutputBuilder(max_threads=2)
    plan = {
        "items": [
            {
                "item_id": "main-1",
                "kind": "main",
                "thread_id": "et-storage-existing",
                "title_hint": "Samsung HBM4 qualification",
                "evidence": [{"entities": ["Samsung", "NVIDIA"], "terms": ["HBM4", "qualification"]}],
            },
            {
                "item_id": "edge-1",
                "kind": "edge",
                "title_hint": "WD board signal",
                "evidence": [{"entities": ["Western Digital"], "terms": ["board"]}],
            },
            {
                "item_id": "main-2",
                "kind": "main",
                "title_hint": "DRAM pricing pressure",
                "evidence": [{"entities": ["Micron"], "terms": ["DRAM", "pricing"]}],
            },
        ]
    }

    structured = builder.build(plan, "storage", "2026-05-30")

    assert [thread["title"] for thread in structured["threads"]] == [
        "Samsung HBM4 qualification",
        "DRAM pricing pressure",
    ]
    assert structured["threads"][0]["priority"] == "high"
    assert structured["threads"][0]["entity_ids"] == ["Samsung", "NVIDIA"]
    assert structured["threads"][1]["thread_id"].startswith("et-storage-20260530-")
    assert structured["causal_edges"][0]["cause_thread_id"] == "et-storage-existing"
    assert structured["judgments"][0]["target_thread_ids"] == [
        structured["threads"][0]["thread_id"],
        structured["threads"][1]["thread_id"],
    ]


def test_resolve_domain_title_prefers_config_override():
    title = resolve_domain_title(
        {"channels": {"storage": {"title": "Override Briefing"}}},
        {"domain": {"title": "存储早报"}},
        "storage",
    )
    assert title == "Override Briefing"


def test_resolve_domain_title_falls_back_to_domain_yaml():
    title = resolve_domain_title({}, {"domain": {"title": "存储早报"}}, "storage")
    assert title == "存储早报"


def test_repair_missing_source_lines_adds_clear_article_match():
    md = """# 存储早报

### Samsung HBM4 sample update

Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30T08:00:00+08:00",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert "*reuters.com · 2026年5月30日*" in repaired


def test_repair_missing_source_lines_skips_structural_sections():
    md = """## 今日要点

Samsung HBM4 samples moved forward for Nvidia qualification.

---

## 行业要点

### Samsung HBM4 samples move forward

Samsung HBM4 samples moved forward for Nvidia qualification.

---

## 产业信号

### 【边缘信号】Anthropic investment update

Samsung HBM4 samples moved forward for Nvidia qualification.

---

## 特别关注

- Samsung HBM4 samples moved forward for Nvidia qualification.

---

## 反向信号

- Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30T08:00:00+08:00",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert repaired.count("*reuters.com · 2026年5月30日*") == 2
    assert "## 今日要点\n\nSamsung HBM4 samples moved forward" in repaired
    assert "## 特别关注\n\n- Samsung HBM4 samples moved forward" in repaired


def test_normalize_edge_signal_headings_prefixes_weak_titles():
    md = """### Anthropic investment update

Body.

---

### 三星HBM4E样品出货

Body.
"""

    normalized = normalize_edge_signal_headings(md)

    assert "### 【边缘信号】Anthropic investment update" in normalized
    assert "### 三星HBM4E样品出货" in normalized


def test_edit_output_policy_owns_edge_classification_and_budget_gate():
    policy = EditOutputPolicy()
    md = """## 今日要点

Summary.

## 行业要点

### Anthropic investment update

Body.

### Samsung HBM4 update

Body.
"""

    normalized = policy.normalize_edge_signal_headings(md)
    ok, detail = policy.item_count_within_budget(
        normalized,
        {"_budget": {"main_min_items": 1, "main_max_items": 1, "edge_min_items": 1, "edge_max_items": 1}},
    )

    assert policy.markdown_news_titles(normalized) == [
        "【边缘信号】Anthropic investment update",
        "Samsung HBM4 update",
    ]
    assert ok, detail


def test_item_count_within_budget_checks_min_and_max():
    md = """## 今日要点

Summary.

## 行业要点

### Item 1

Body.

## 产业信号

### 【边缘信号】Item 2

Body.
"""

    assert markdown_news_titles(md) == ["Item 1", "【边缘信号】Item 2"]
    ok, detail = item_count_within_budget(md, {"_budget": {"min_items": 2, "max_items": 3}})
    assert ok, detail
    ok, detail = item_count_within_budget(md, {"_budget": {"min_items": 3, "max_items": 4}})
    assert not ok
    assert "minimum" in detail


def test_multi_day_daily_budget_relaxes_minimums_and_caps_total_at_36():
    budget = apply_evidence_window_budget(
        {
            "min_items": 20,
            "max_items": 30,
            "main_min_items": 16,
            "main_max_items": 18,
            "edge_min_items": 5,
            "edge_max_items": 8,
            "target_main_items": 18,
            "target_edge_items": 6,
        },
        "daily",
        3,
    )

    assert budget["min_items"] == 0
    assert budget["main_min_items"] == 0
    assert budget["edge_min_items"] == 0
    assert budget["max_items"] == 36
    assert budget["target_main_items"] == 28
    assert budget["target_edge_items"] == 8

    md = "\n\n".join(f"### Item {idx}\n\nBody." for idx in range(1, 37))
    ok, detail = item_count_within_budget(md, {"_budget": budget})
    assert ok, detail
    too_many = md + "\n\n### Item 37\n\nBody."
    ok, detail = item_count_within_budget(too_many, {"_budget": budget})
    assert not ok
    assert "total maximum is 36" in detail


def test_one_day_daily_budget_keeps_manifest_limits():
    budget = {
        "min_items": 20,
        "max_items": 30,
        "main_min_items": 16,
        "edge_min_items": 5,
    }

    assert apply_evidence_window_budget(budget, "daily", 1) == budget


def test_item_count_within_budget_uses_plan_counts_for_sparse_evidence():
    md = """## 今日要点

Summary.

## 行业要点

### Item 1

Body.

### Item 2

Body.
"""

    ok, detail = item_count_within_budget(md, {
        "_budget": {"min_items": 20, "main_min_items": 16, "max_items": 30},
        "_plan_counts": {"total_items": 2, "main_items": 2, "edge_items": 0},
    })

    assert ok, detail


def test_item_count_within_budget_checks_main_and_edge_ranges():
    md = """## 今日要点

Summary.

## 行业要点

### Item 1

Body.

### Item 2

Body.

## 产业信号

### 【边缘信号】Item 3

Body.

### 【边缘信号】Item 4

Body.
"""

    budget = {
        "_budget": {
            "min_items": 4,
            "max_items": 6,
            "main_min_items": 2,
            "main_max_items": 3,
            "edge_min_items": 2,
            "edge_max_items": 3,
        },
    }
    ok, detail = item_count_within_budget(md, budget)
    assert ok, detail

    low_edge_budget = {"_budget": dict(budget["_budget"], edge_min_items=3)}
    ok, detail = item_count_within_budget(md, low_edge_budget)
    assert not ok
    assert "edge minimum" in detail

    low_main_budget = {"_budget": dict(budget["_budget"], main_min_items=3)}
    ok, detail = item_count_within_budget(md, low_main_budget)
    assert not ok
    assert "main minimum" in detail


def test_repair_source_line_dates_uses_matching_article_date():
    md = """### SK hynix iHBM update

SK hynix iHBM thermal solution for HBM5.

*trendforce.com · 2026年5月26日*
"""
    articles = [
        {
            "title": "SK hynix iHBM thermal solution",
            "snippet": "SK hynix iHBM thermal solution for HBM5",
            "source": "trendforce.com",
            "published_at": "2026-05-30T00:00:00+08:00",
        }
    ]

    repaired = repair_source_line_dates(md, articles, "2026-05-30")

    assert "*trendforce.com · 2026年5月30日*" in repaired


def test_source_alignment_matcher_owns_item_article_overlap():
    matcher = SourceAlignmentMatcher()
    articles = [
        {
            "id": "a1",
            "title": "Samsung expands memory capacity in Korea",
            "snippet": "Samsung and SK hynix plan additional DRAM cleanroom investments.",
            "source": "v.daum.net",
        },
        {
            "id": "a2",
            "title": "Micron India packaging facility starts volume production",
            "snippet": "Micron said its India memory packaging facility ramped production.",
            "source": "investors.micron.com",
        },
    ]

    alignment = matcher.align_item(
        "Micron India facility ramps production",
        ["Micron's India packaging facility started volume production for memory chips."],
        articles,
    )

    assert alignment.matched
    assert alignment.article["id"] == "a2"
    assert alignment.score >= 0.35
    assert matcher.best_article_for_source_item(
        "investors.micron.com",
        "Micron India facility ramps production",
        ["Micron's India packaging facility started volume production for memory chips."],
        articles,
    )["id"] == "a2"


def test_repair_source_line_dates_filters_unsupported_sources():
    md = """### Micron India facility ramps production

Micron's India packaging facility started volume production for memory chips.

*v.daum.net, investors.micron.com · 2026年5月30日*
"""
    articles = [
        {
            "title": "Samsung expands memory capacity in Korea",
            "snippet": "Samsung and SK hynix plan additional DRAM cleanroom investments.",
            "source": "v.daum.net",
            "published_at": "2026-05-30",
        },
        {
            "title": "Micron India packaging facility starts volume production",
            "snippet": "Micron said its India memory packaging facility ramped production.",
            "source": "investors.micron.com",
            "published_at": "2026-05-30",
        },
    ]

    repaired = repair_source_line_dates(md, articles, "2026-05-30")

    assert "*investors.micron.com · 2026年5月30日*" in repaired
    assert "v.daum.net" not in repaired


def test_repair_missing_source_lines_keeps_existing_source_line():
    md = """### Samsung HBM4 sample update

Body.

*Reuters · 2026年5月30日*
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert repaired.count("Reuters") == 1
    assert "reuters.com" not in repaired


def test_repair_missing_source_lines_ignores_weak_match():
    md = """### Random packaging rumor

This paragraph has no overlap with the article pool.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]

    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    assert "reuters.com" not in repaired


def test_repaired_source_line_passes_validate_item():
    from stratum.stages.validate.validate import parse_markdown, validate_item
    import tempfile

    md = """### Samsung HBM4 sample update

Samsung HBM4 samples moved forward for Nvidia qualification.
"""
    articles = [
        {
            "title": "Samsung HBM4 samples move forward",
            "snippet": "Nvidia qualification update",
            "source_domain": "reuters.com",
            "published_at": "2026-05-30",
        }
    ]
    repaired = repair_missing_source_lines(md, articles, "2026-05-30")

    with tempfile.NamedTemporaryFile("w+", suffix=".md") as f:
        f.write(repaired)
        f.flush()
        items = parse_markdown(f.name)

    assert len(items) == 1
    assert validate_item(items[0], articles, "2026-05-30", {}) == []


def test_call_llm_sends_payload_via_stdin(monkeypatch):
    import json
    import subprocess
    from stratum.stages.edit import llm_client

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"choices": [{"message": {"content": "ok"}}]}),
            stderr="",
        )

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    result = llm_client.call_llm(
        "system prompt",
        "user prompt",
        {"api_key": "key", "model": "model", "endpoint": "https://example.com"},
    )

    assert result == "ok"
    assert "--data-binary" in captured["cmd"]
    assert "@-" in captured["cmd"]
    assert "system prompt" in captured["input"]
    assert "user prompt" in captured["input"]
    assert "system prompt" not in captured["cmd"]
    assert "user prompt" not in captured["cmd"]
    assert "-sS" in captured["cmd"]
    assert "--max-time" in captured["cmd"]


def test_call_llm_reports_curl_failure(monkeypatch):
    import subprocess
    from stratum.stages.edit import llm_client

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 56, stdout="", stderr="connection reset")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    try:
        llm_client.call_llm("system", "user", {"api_key": "key", "endpoint": "https://example.com"})
    except RuntimeError as exc:
        assert "curl exited 56" in str(exc)
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_call_llm_reports_empty_content(monkeypatch):
    import json
    import subprocess
    from stratum.stages.edit import llm_client

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 1},
            }) + "\nHTTP_STATUS:200\n",
            stderr="",
        )

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)

    try:
        llm_client.call_llm("system", "user", {"api_key": "key", "endpoint": "https://example.com"})
    except RuntimeError as exc:
        assert "empty content" in str(exc)
        assert "finish_reason=length" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
