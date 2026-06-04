"""Tests for validate stage — briefing factuality gate."""
import pytest
import json
import os
import tempfile

from stratum.stages.validate import (
    ClaimValidator,
    SourceDatePolicy,
    SourceSupportMatcher,
    parse_markdown, validate_item, load_domain_config, _parse_source_line,
    validate_structured_output,
    validate_boilerplate, validate_briefing, validate_overclaims, resolve_date_window,
)


MOCK_SOURCE_ALIASES = {
    "reuters": "reuters.com",
    "bloomberg": "bloomberg.com",
    "trendforce": "trendforce.com",
    "digitimes": ["digitimes.com", "digitimes.com.tw"],
    "新浪财经": "finance.sina.com.cn",
    "财新": "caixin.com",
}


def test_domain_from_url_strips_only_known_presentation_prefixes():
    matcher = SourceSupportMatcher()
    assert matcher.domain_from_url("https://www.reuters.com/technology") == "reuters.com"
    assert matcher.domain_from_url("https://m.reuters.com/technology") == "reuters.com"
    assert matcher.domain_from_url("https://ww2.example.com/news") == "ww2.example.com"


def test_package_exports_stable_validate_surface():
    from stratum.stages import validate as validate_pkg

    assert validate_pkg.parse_markdown is parse_markdown
    assert validate_pkg.validate_item is validate_item
    assert validate_pkg.validate_briefing is validate_briefing
    assert validate_pkg.ClaimValidator is ClaimValidator
    assert validate_pkg.SourceSupportMatcher is SourceSupportMatcher


def test_validate_briefing_returns_structured_report():
    items = [{
        "title": "Samsung HBM4 confirmed by Reuters",
        "body": ["消息称三星已经确认大规模供货。"],
        "sources": ["Reuters"],
        "date": "2026年5月30日",
    }]
    articles = [{
        "id": "a1",
        "title": "Reuters says Samsung reportedly samples HBM4",
        "source": "reuters.com",
        "source_domain": "reuters.com",
        "published_at": "2026-05-30",
        "snippet": "Reuters reported Samsung reportedly sampled HBM4 to customers.",
        "quality_flags": [],
        "source_type": "media",
    }]

    report = validate_briefing(
        "dummy markdown",
        items,
        articles,
        "2026-05-30",
        MOCK_SOURCE_ALIASES,
    )

    assert report["status"] == "violations"
    assert report["summary"]["invalid_items"] == 1
    assert report["details"][0]["kind"] == "item"
    assert report["details"][0]["title"] == "Samsung HBM4 confirmed by Reuters"


SAMPLE_BRIEFING = """# 存储早报
## 2026年5月28日 · 周四

今日存储产业动态...

---

### Samsung ships HBM4 to NVIDIA
Samsung Electronics announced HBM4 mass production.

*Reuters · 2026年5月28日*

### Memory prices rise in Q2
DRAM and NAND prices continue upward trend.

*Trendforce, Bloomberg · 2026年5月28日*

---

## 特别关注
- Watch HBM4 validation

## 反向信号
- If hyperscaler capex drops sharply

---

*由 AI Agent 自动生成 · 2026年5月28日*
"""


class TestParseMarkdown:
    def test_parses_items(self):
        items = parse_markdown_from_str(SAMPLE_BRIEFING)
        assert len(items) == 2
        assert items[0]["title"] == "Samsung ships HBM4 to NVIDIA"
        assert "Reuters" in items[0]["sources"]
        assert "2026年5月28日" in items[0]["date"]

    def test_skips_section_headers(self):
        items = parse_markdown_from_str(SAMPLE_BRIEFING)
        titles = [i["title"] for i in items]
        assert "特别关注" not in titles
        assert "反向信号" not in titles

    def test_boilerplate_validation_uses_domain_rules(self):
        pipeline_config = {
            "boilerplate": {
                "source_rules": [{
                    "domains": ["chinaflashmarket.com"],
                    "cut_markers": ["#### 报价中心"],
                }]
            }
        }

        violations = validate_boilerplate("正文\n\n#### 报价中心", pipeline_config)

        assert any("BOILERPLATE" in violation for violation in violations)

    def test_date_window_accepts_search_window_override(self):
        pipeline_config = {"date_window": {"stale_days": 2, "max_future_days": 1}}

        assert resolve_date_window(pipeline_config) == (1, 2)
        assert resolve_date_window(pipeline_config, stale_days_override=3) == (1, 3)

    def test_keeps_news_titles_that_contain_section_words(self):
        content = """# 存储早报

### HBM 供应受关注
HBM supply is a valid news item.

*Trendforce · 2026年5月28日*

## 特别关注
- Follow price checks

## 反向信号
- Watch demand risk
"""
        items = parse_markdown_from_str(content)
        assert len(items) == 1
        assert items[0]["title"] == "HBM 供应受关注"
        assert "Watch demand risk" not in items[0]["body"]

    def test_source_alignment_accepts_core_storage_term_translation(self):
        item = {
            "title": "存储供应链逆季节性而行，2026年第一季度合约价格上涨",
            "body": ["合约价逆季节性上涨表明供需紧张超出预期。"],
            "sources": ["digitimes.com"],
            "date": "2026年5月30日",
        }
        articles = [{
            "title": "Memory supply chain defies seasonality with contract price hikes in 1Q26",
            "snippet": "The memory sector saw contract price increases significantly reflected in first quarter 2026 results.",
            "source": "digitimes.com",
            "published_at": "2026-05-30T08:00:00+08:00",
            "quality_flags": [],
        }]

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert violations == []

    def test_source_line_keeps_full_date_with_weekday(self):
        parsed = _parse_source_line("*news.qq.com [zh-CN] · 2026年5月30日 · 周六*")
        assert parsed == (["news.qq.com"], "2026年5月30日 · 周六")

    def test_source_line_strips_multiple_locale_tags(self):
        parsed = _parse_source_line("*Digitimes [en], cnstock.com [zh-CN] · 2026年5月30日*")
        assert parsed == (["Digitimes", "cnstock.com"], "2026年5月30日")

    def test_source_line_strips_case_variant_locale_tags(self):
        parsed = _parse_source_line("*Digitimes [EN], cnstock.com [zh-cn], example.jp [zh-Hans-CN] · 2026年5月30日*")
        assert parsed == (["Digitimes", "cnstock.com", "example.jp"], "2026年5月30日")

    def test_footer_line_is_not_source(self):
        assert _parse_source_line("*本简报由 AI Agent 自动生成 · 2026年5月30日 · 周六*") is None


class TestValidateItem:
    def test_valid_source(self):
        articles = [
            {"source": "reuters.com", "id": "a1", "title": "Samsung HBM4"},
            {"source": "trendforce.com", "id": "a2", "title": "Memory prices"},
            {"source": "bloomberg.com", "id": "a3", "title": "DRAM prices"},
        ]
        item = {
            "title": "Samsung HBM4",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert len(violations) == 0

    def test_valid_source_domain_field(self):
        articles = [
            {
                "source_domain": "reuters.com",
                "url": "https://www.reuters.com/technology/test",
                "id": "a1",
                "title": "Samsung HBM4",
            },
        ]
        item = {
            "title": "Samsung HBM4",
            "sources": ["Reuters"],
            "date": "2026-05-28",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert violations == []

    def test_missing_source(self):
        articles = [
            {"source": "reuters.com", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["UnknownSource"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE" in v for v in violations)

    def test_brand_source_not_accepted_by_domain_token_fallback(self):
        articles = [
            {"source": "notreuters.example.com", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", {})
        assert any("SOURCE:" in v for v in violations)

    def test_source_alias_uses_domain_boundary_matching(self):
        articles = [
            {"source": "notreuters.com", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE:" in v for v in violations)

    def test_source_alias_accepts_multiple_domain_patterns(self):
        articles = [
            {"source": "digitimes.com.tw", "id": "a1", "title": "HBM supply"},
        ]
        item = {
            "title": "HBM supply",
            "sources": ["Digitimes"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert violations == []

    def test_domain_like_source_uses_domain_boundary_matching(self):
        articles = [
            {"source": "notreuters.com", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["reuters.com"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE:" in v for v in violations)

    def test_domain_like_source_can_use_token_fallback(self):
        articles = [
            {"source": "finance.sina.com.cn", "id": "a1", "title": "Test"},
        ]
        item = {
            "title": "Test",
            "sources": ["sina.com.cn"],
            "date": "2026年5月28日",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", {})
        assert violations == []

    def test_source_must_support_item_content(self):
        articles = [
            {
                "source": "reuters.com",
                "id": "a1",
                "title": "Samsung HBM4 qualification advances",
                "snippet": "NVIDIA memory qualification update",
            },
        ]
        item = {
            "title": "Kioxia NAND fab resumes production",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": ["Factory utilization recovered after outage."],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE_CONTEXT" in v for v in violations)

    def test_source_with_no_comparable_article_text_cannot_support_item(self):
        articles = [
            {
                "source": "reuters.com",
                "id": "a1",
                "title": "",
                "snippet": "",
            },
        ]
        item = {
            "title": "Samsung HBM4 qualification advances",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": ["NVIDIA memory qualification update."],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE_CONTEXT" in v for v in violations)

    def test_single_strong_product_token_can_align_cross_language_item(self):
        articles = [
            {
                "source": "semiconductor.samsung.com",
                "id": "a1",
                "title": "Samsung Electronics Begins Shipment of Industry-First HBM4E Samples",
                "snippet": "Samsung Electronics Begins Shipment of Industry-First HBM4E Samples",
                "published_at": "2026-05-29",
            },
        ]
        item = {
            "title": "三星率先交付HBM4E样品",
            "sources": ["semiconductor.samsung.com"],
            "date": "2026年5月29日",
            "body": ["三星电子宣布已开始向主要客户交付业界首批12层HBM4E样品。"],
        }
        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)
        assert violations == []

    def test_cjk_phrase_variants_can_align_supporting_article(self):
        articles = [
            {
                "source": "ijiwei.com",
                "id": "a1",
                "title": "时代芯存首台光刻机进厂,项目进入设备调试新阶段",
                "snippet": "江苏时代芯存半导体有限公司重整后的首台光刻机正式进厂",
                "published_at": "2026-05-30",
            },
        ]
        item = {
            "title": "长鑫科技科创板 IPO 过会，全球 DRAM 份额升至 7.7%",
            "sources": ["ijiwei.com"],
            "date": "2026年5月30日",
            "body": ["时代芯存重整后首台光刻机已进厂，国内存储厂商扩产继续推进。"],
        }
        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)
        assert violations == []

    def test_cited_source_date_must_match_supporting_article_date(self):
        articles = [
            {
                "source": "reuters.com",
                "id": "a1",
                "title": "Samsung HBM4 qualification advances",
                "snippet": "NVIDIA memory qualification update",
                "published_at": "2026-05-20T09:30:00+08:00",
            },
        ]
        item = {
            "title": "Samsung HBM4 qualification advances",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": ["NVIDIA memory qualification update."],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE_DATE" in v for v in violations)

    def test_background_article_cannot_be_only_support(self):
        articles = [
            {
                "source": "investors.micron.com",
                "id": "a1",
                "title": "Micron HBM capacity update",
                "snippet": "HBM capacity update",
                "published_at": "2026-05-20T09:30:00+08:00",
                "quality_flags": ["BACKGROUND_STALE"],
            },
        ]
        item = {
            "title": "Micron HBM capacity update",
            "sources": ["investors.micron.com"],
            "date": "2026年5月28日",
            "body": ["HBM capacity update."],
        }

        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)

        assert any("only by background evidence" in v for v in violations)

    def test_background_source_can_supplement_fresh_support(self):
        articles = [
            {
                "source": "trendforce.com",
                "id": "a1",
                "title": "HBM capacity update",
                "snippet": "HBM capacity update",
                "published_at": "2026-05-28T09:30:00+08:00",
            },
            {
                "source": "investors.micron.com",
                "id": "a2",
                "title": "Micron HBM capacity update",
                "snippet": "HBM capacity update",
                "published_at": "2026-05-20T09:30:00+08:00",
                "quality_flags": ["BACKGROUND_STALE"],
            },
        ]
        item = {
            "title": "Micron HBM capacity update",
            "sources": ["trendforce.com", "investors.micron.com"],
            "date": "2026年5月28日",
            "body": ["HBM capacity update."],
        }

        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)

        assert violations == []

    def test_source_date_allows_supporting_article_within_stale_window(self):
        articles = [
            {
                "source": "semiconductor.samsung.com",
                "id": "a1",
                "title": "Samsung Electronics Begins Shipment of Industry-First HBM4E Samples",
                "snippet": "Samsung HBM4E samples",
                "published_at": "2026-05-29",
            },
        ]
        item = {
            "title": "三星率先交付HBM4E样品",
            "sources": ["semiconductor.samsung.com"],
            "date": "2026年5月30日",
            "body": ["Samsung HBM4E samples."],
        }
        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)
        assert not any("SOURCE_DATE" in v for v in violations)

    def test_cited_source_date_accepts_matching_article_timestamp(self):
        articles = [
            {
                "source": "reuters.com",
                "id": "a1",
                "title": "Samsung HBM4 qualification advances",
                "snippet": "NVIDIA memory qualification update",
                "published_at": "2026-05-28T23:30:00Z",
            },
        ]
        item = {
            "title": "Samsung HBM4 qualification advances",
            "sources": ["Reuters"],
            "date": "2026年5月29日 · 周五",
            "body": ["NVIDIA memory qualification update."],
        }
        violations = validate_item(item, articles, "2026-05-29", MOCK_SOURCE_ALIASES)
        assert not any("SOURCE_DATE" in v for v in violations)

    def test_missing_article_date_does_not_create_source_date_violation(self):
        articles = [
            {
                "source": "reuters.com",
                "id": "a1",
                "title": "Samsung HBM4 qualification advances",
                "snippet": "NVIDIA memory qualification update",
            },
        ]
        item = {
            "title": "Samsung HBM4 qualification advances",
            "sources": ["Reuters"],
            "date": "2026年5月28日",
            "body": ["NVIDIA memory qualification update."],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert not any("SOURCE_DATE" in v for v in violations)

    def test_invalid_date_format_is_violation(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "May 28",
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("Cannot parse date" in v for v in violations)

    def test_cited_same_month_date_range_is_valid(self):
        articles = [
            {
                "source": "servethehome.com",
                "id": "a1",
                "title": "Silicon Motion AI PC SSD controller",
                "snippet": "SM2524XT PCIe Gen5 DRAM-less SSD controller for AI PC workloads",
                "published_at": "2026-05-29",
            },
        ]
        item = {
            "title": "Silicon Motion AI PC SSD controller",
            "sources": ["servethehome.com"],
            "date": "2026年5月28-30日",
            "body": ["SM2524XT PCIe Gen5 DRAM-less SSD controller for AI PC workloads."],
        }
        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)
        assert violations == []

    def test_parse_cited_date_range_returns_bounds(self):
        parsed = SourceDatePolicy().parse_cited_date_range("2026年5月28-30日")
        assert parsed[0].date().isoformat() == "2026-05-28"
        assert parsed[1].date().isoformat() == "2026-05-30"

    def test_stale_date(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月20日",  # 8 days old
            "body": [],
        }
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("DATE" in v for v in violations)

    def test_stale_date_uses_domain_policy(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月25日",
            "body": [],
        }
        violations = validate_item(
            item,
            articles,
            "2026-05-28",
            MOCK_SOURCE_ALIASES,
            stale_days=3,
        )
        assert not any("days old" in v for v in violations)

        violations = validate_item(
            item,
            articles,
            "2026-05-28",
            MOCK_SOURCE_ALIASES,
            stale_days=2,
        )
        assert any("max 2 days" in v for v in violations)

    def test_future_date_beyond_window(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {
            "title": "Test",
            "sources": ["Reuters"],
            "date": "2026年5月31日",
            "body": [],
        }
        violations = validate_item(
            item,
            articles,
            "2026-05-28",
            MOCK_SOURCE_ALIASES,
            max_future_days=1,
        )
        assert any("future" in v for v in violations)

    def test_no_sources_violation(self):
        articles = [{"source": "reuters.com", "id": "a1", "title": "Test"}]
        item = {"title": "Test", "sources": [], "date": "2026年5月28日", "body": []}
        violations = validate_item(item, articles, "2026-05-28", MOCK_SOURCE_ALIASES)
        assert any("SOURCE" in v for v in violations)

    def test_overclaim_flags_sample_as_mass_production(self):
        articles = [{
            "id": "a1",
            "source": "semiconductor.samsung.com",
            "title": "Samsung begins HBM4E sample shipments for customer qualification",
            "snippet": "The company is shipping samples for customer validation.",
            "published_at": "2026-05-30",
        }]
        item = {
            "title": "Samsung confirmed mass production of HBM4E",
            "sources": ["semiconductor.samsung.com"],
            "date": "2026年5月30日",
            "body": ["The report treats sample shipments as confirmed mass production."],
        }

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert any("OVERCLAIM" in violation for violation in violations)

    def test_overclaim_allows_mass_production_when_article_supports_it(self):
        articles = [{
            "id": "a1",
            "source": "example.com",
            "title": "Supplier starts mass production of HBM4E",
            "snippet": "The supplier said mass production has started.",
        }]
        item = {
            "title": "Supplier starts mass production of HBM4E",
            "body": ["The source says mass production has started."],
        }

        assert validate_overclaims(item, articles) == []

    def test_claim_validator_accepts_custom_rule_set(self):
        validator = ClaimValidator(overclaim_rules=[{
            "name": "custom_rule",
            "claim_patterns": [r"certain"],
            "weak_evidence_patterns": [r"maybe"],
            "support_patterns": [r"certain"],
        }])

        violations = validator.validate_overclaims(
            {"title": "Outcome is certain", "body": []},
            [{"id": "a1", "title": "Outcome maybe changes"}],
        )

        assert any("custom_rule" in violation for violation in violations)

    def test_overclaim_flags_forecast_as_certain_outcome(self):
        articles = [{
            "id": "a1",
            "source": "analyst.example",
            "title": "Analyst expects DRAM prices may rise in Q3",
            "snippet": "The forecast says prices could rise if AI server demand remains strong.",
            "published_at": "2026-05-30",
        }]
        item = {
            "title": "DRAM prices will definitely rise in Q3",
            "sources": ["analyst.example"],
            "date": "2026年5月30日",
            "body": ["The report turns an analyst forecast into a guaranteed outcome."],
        }

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert any("forecast_overstated_as_certain_outcome" in violation for violation in violations)

    def test_overclaim_flags_customer_win_from_qualification_evidence(self):
        articles = [{
            "id": "a1",
            "source": "market.example",
            "source_type": "media",
            "title": "Samsung HBM4 qualification continues at NVIDIA",
            "snippet": "Sources said samples remain in customer validation.",
            "published_at": "2026-05-30",
        }]
        item = {
            "title": "Samsung secured NVIDIA design win for HBM4",
            "sources": ["market.example"],
            "date": "2026年5月30日",
            "body": ["The item turns validation into a confirmed customer order."],
        }

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert any(
            "customer_commitment_requires_confirmed_customer_evidence" in violation
            for violation in violations
        )

    def test_overclaim_allows_customer_claim_when_customer_confirms(self):
        articles = [{
            "id": "a1",
            "source": "nvidia.com",
            "source_type": "official",
            "title": "NVIDIA said it selected Samsung HBM4 for next systems",
            "snippet": "The customer announced a supply agreement.",
        }]
        item = {
            "title": "Samsung selected by NVIDIA for HBM4 supply",
            "body": ["The source says NVIDIA selected Samsung and announced a supply agreement."],
        }

        assert validate_overclaims(item, articles) == []

    def test_overclaim_flags_entity_mismatch_between_claim_and_support(self):
        articles = [{
            "id": "a1",
            "source": "samsung.com",
            "source_type": "official",
            "title": "Samsung said HBM4 qualification is progressing",
            "snippet": "The company described validation work with customers.",
        }]
        item = {
            "title": "Samsung selected by NVIDIA for HBM4 supply",
            "body": ["The article does not contain an NVIDIA customer confirmation."],
        }

        violations = validate_overclaims(item, articles)

        assert any(
            "customer_commitment_requires_confirmed_customer_evidence" in violation
            for violation in violations
        )

    def test_overclaim_flags_financial_outcome_from_analyst_estimate(self):
        articles = [{
            "id": "a1",
            "source": "analyst.example",
            "source_type": "analyst",
            "title": "Analysts expect Micron revenue may rise next quarter",
            "snippet": "The forecast is based on channel checks.",
            "published_at": "2026-05-30",
        }]
        item = {
            "title": "Micron revenue will increase next quarter",
            "sources": ["analyst.example"],
            "date": "2026年5月30日",
            "body": ["The item states a financial outcome as fact."],
        }

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert any(
            "financial_outcome_requires_financial_or_company_evidence" in violation
            for violation in violations
        )

    def test_overclaim_allows_financial_outcome_from_company_filing(self):
        articles = [{
            "id": "a1",
            "source": "investors.micron.com",
            "source_type": "financial",
            "title": "Micron earnings release reports revenue increased",
            "snippet": "The company reported revenue increased in its financial statement.",
        }]
        item = {
            "title": "Micron revenue increased",
            "body": ["The earnings release says revenue increased."],
        }

        assert validate_overclaims(item, articles) == []

    def test_overclaim_flags_correlation_as_causal_language(self):
        articles = [{
            "id": "a1",
            "source": "market.example",
            "source_type": "media",
            "title": "HBM orders linked to DRAM spot price movement",
            "snippet": "Analysts suggest the two signals may be correlated.",
            "published_at": "2026-05-30",
        }]
        item = {
            "title": "HBM demand caused DRAM spot prices to rise",
            "sources": ["market.example"],
            "date": "2026年5月30日",
            "body": ["The item upgrades a correlation into a mechanism."],
        }

        violations = validate_item(item, articles, "2026-05-30", MOCK_SOURCE_ALIASES)

        assert any(
            "causal_language_requires_explicit_mechanism_evidence" in violation
            for violation in violations
        )

    def test_overclaim_allows_causal_language_with_explicit_mechanism(self):
        articles = [{
            "id": "a1",
            "source": "micron.com",
            "source_type": "official",
            "title": "Micron says HBM demand was driven by AI server ramps",
            "snippet": "Management said growth was driven by AI server ramps.",
        }]
        item = {
            "title": "Micron HBM growth was driven by AI server ramps",
            "body": ["Management attributed the growth to AI server ramps."],
        }

        assert validate_overclaims(item, articles) == []


class TestStructuredOutputValidation:
    def test_validates_threads_against_schema(self, tmp_path):
        event_threads = tmp_path / "event-threads.json"
        event_threads.write_text(json.dumps({
            "threads": [
                {
                    "thread_id": "et-storage-20260530-abc123ef",
                    "id": "et-storage-20260530-abc123ef",
                    "title": "Samsung HBM4 qualification",
                    "status": "active",
                    "priority": "high",
                    "entity_ids": ["samsung"],
                    "term_ids": ["hbm4"],
                    "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
                    "close_conditions": ["NVIDIA qualification result disclosed"],
                }
            ],
            "causal_edges": [],
            "judgments": [],
        }))
        schemas_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "edit",
            "prompts",
            "_schemas",
        )

        violations = validate_structured_output(str(event_threads), schemas_dir)

        assert violations == []

    def test_thread_schema_rejects_missing_title(self, tmp_path):
        event_threads = tmp_path / "event-threads.json"
        event_threads.write_text(json.dumps({
            "threads": [
                {
                    "thread_id": "et-storage-20260530-abc123ef",
                    "status": "active",
                    "priority": "high",
                    "watch_signals": ["Samsung HBM4 NVIDIA qualification"],
                }
            ],
        }))
        schemas_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "edit",
            "prompts",
            "_schemas",
        )

        violations = validate_structured_output(str(event_threads), schemas_dir)

        assert any("SCHEMA_THREAD" in violation for violation in violations)

    def test_causal_schema_accepts_current_thread_id_shape(self, tmp_path):
        event_threads = tmp_path / "event-threads.json"
        event_threads.write_text(json.dumps({
            "threads": [],
            "causal_edges": [
                {
                    "cause_thread_id": "et-storage-20260530-abc123ef",
                    "effect_thread_id": "et-storage-0001",
                    "mechanism": "HBM4 qualification progress changes expected supplier allocation timing.",
                    "confidence": "B",
                }
            ],
            "judgments": [
                {
                    "target_type": "event_pair",
                    "target_thread_ids": ["et-storage-20260530-abc123ef", "et-storage-0001"],
                    "hypothesis": "Samsung qualification progress will affect HBM allocation timing.",
                    "confidence": "B",
                    "expected_verification": "2026-06-30",
                }
            ],
        }))
        schemas_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "edit",
            "prompts",
            "_schemas",
        )

        violations = validate_structured_output(str(event_threads), schemas_dir)

        assert violations == []


def parse_markdown_from_str(content: str):
    """Helper: parse markdown from string instead of file."""
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".md") as tmp:
        tmp.write(content)
        tmp.flush()
        return parse_markdown(tmp.name)
