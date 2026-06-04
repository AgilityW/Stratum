"""Tests for DB-native multi-scale synthesis."""

from __future__ import annotations

import json


def _seed_daily_inputs(domain: str) -> None:
    from stratum.db.connection import get_db
    from stratum.db.persistence import upsert_articles, upsert_report_bundle

    conn = get_db(domain)
    conn.executemany(
        "INSERT OR REPLACE INTO entities (id, type, name_en, status) VALUES (?, 'COMPANY', ?, 'active')",
        [("samsung", "Samsung"), ("sk-hynix", "SK hynix")],
    )
    conn.execute(
        "INSERT OR REPLACE INTO terms (id, type, name_en, trend) VALUES ('hbm', 'TECHNOLOGY', 'HBM', 'rising')"
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO threads (
            id, label, description, status, priority, first_event_date,
            last_event_date, event_count_daily, event_count_weekly
        )
        VALUES ('et-hbm-race', 'HBM qualification race', '', 'active', 1, '2026-05-25', '2026-05-26', 2, 0)
        """
    )
    for day, title, article_id, entity_id in [
        ("2026-05-25", "Samsung starts HBM qualification", "a-20260525-hbm", "samsung"),
        ("2026-05-26", "SK hynix expands HBM output", "a-20260526-hbm", "sk-hynix"),
    ]:
        conn.execute(
            """
            INSERT OR REPLACE INTO events (
                id, thread_id, scale, date, title, article_ids, entity_ids,
                term_ids, source_domains, confidence, briefing_id, created_at,
                status, priority
            )
            VALUES (?, 'et-hbm-race', 'daily', ?, ?, ?, ?, '["hbm"]',
                    '["example.com"]', 'B', ?, ?, 'active', 1)
            """,
            (
                f"ev-{day}-et-hbm-race",
                day,
                title,
                json.dumps([article_id]),
                json.dumps([entity_id]),
                f"daily-{day}",
                f"{day}T08:00:00+08:00",
            ),
        )
    conn.commit()
    conn.close()

    upsert_articles(domain, [
        {"id": "a-20260525-hbm", "title": "Samsung HBM", "url": "https://example.com/samsung", "source": "Example", "published_at": "2026-05-25", "entity_ids": ["samsung"], "term_ids": ["hbm"]},
        {"id": "a-20260526-hbm", "title": "SK hynix HBM", "url": "https://example.com/sk-hynix", "source": "Example", "published_at": "2026-05-26", "entity_ids": ["sk-hynix"], "term_ids": ["hbm"]},
    ], "2026-05-26")
    for day, article_id in [("2026-05-25", "a-20260525-hbm"), ("2026-05-26", "a-20260526-hbm")]:
        report_id = f"report-storage-daily-{day}"
        item_id = f"item-daily-{day}"
        upsert_report_bundle(
            domain,
            {"id": report_id, "scale": "daily", "period": day},
            sections=[{"section_key": "today", "title": "今日要点", "position": 1}],
            items=[{"id": item_id, "section_key": "today", "position": 1, "title": f"HBM daily {day}", "body": "", "signal_type": "main", "importance": 1}],
            item_events=[{"report_item_id": item_id, "event_id": f"ev-{day}-et-hbm-race"}],
            item_threads=[{"report_item_id": item_id, "thread_id": "et-hbm-race"}],
            item_articles=[{"report_item_id": item_id, "article_id": article_id}],
        )


def test_synthesize_cascade_report_writes_weekly_to_yearly_chain(tmp_path, monkeypatch):
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration
    from stratum.db.service import get_cascade_inputs, get_report_context, trace_report_lineage
    from stratum.db.synthesis import synthesize_cascade_report

    monkeypatch.setenv("STRATUM_DB_DIR", str(tmp_path))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()
    _seed_daily_inputs("storage")
    from stratum.db.persistence import upsert_articles

    upsert_articles("storage", [{
        "id": "fresh-weekly-hbm",
        "title": "Fresh weekly HBM explore",
        "url": "https://example.com/fresh-weekly-hbm",
        "source": "Example",
        "published_at": "2026-05-31",
        "entity_ids": ["samsung"],
        "term_ids": ["hbm"],
    }], "2026-W22", scale="weekly")

    weekly = synthesize_cascade_report("storage", "weekly", "2026-W22")
    monthly = synthesize_cascade_report("storage", "monthly", "2026-05")
    quarterly = synthesize_cascade_report("storage", "quarterly", "2026-Q2")
    yearly = synthesize_cascade_report("storage", "yearly", "2026")

    weekly_context = get_report_context("storage", "weekly", "2026-W22")
    monthly_inputs = get_cascade_inputs("storage", "monthly", "2026-05")
    yearly_lineage = trace_report_lineage("storage", "report-storage-yearly-2026")

    assert weekly["source_reports"] == 2
    assert weekly["source_scales"] == ["daily"]
    assert weekly["fresh_evidence"] == 1
    assert weekly["synthesized_events"] == 1
    assert monthly["source_scales"] == ["daily", "weekly"]
    assert monthly["source_reports"] == 3
    assert quarterly["source_scales"] == ["daily", "weekly", "monthly"]
    assert quarterly["source_reports"] == 4
    assert yearly["source_scales"] == ["daily", "weekly", "monthly", "quarterly"]
    assert yearly["source_reports"] == 5
    assert weekly_context["report"]["runtime_mode"] == "db_native_synthesis"
    assert [section["section_key"] for section in weekly_context["sections"]] == [
        "executive_summary",
        "core_themes",
        "signal_noise",
        "judgment_tracker",
        "fresh_coverage",
        "watchlist",
        "source_boundary",
    ]
    assert any(item["signal_type"] == "trend" for item in weekly_context["items"])
    trend_items = [item for item in weekly_context["items"] if item["signal_type"] == "trend"]
    assert trend_items[0]["policy_decision"]["decision"]["role"] in {
        "baseline_confirmed_by_fresh",
        "baseline_supplemented_by_fresh",
    }
    assert trend_items[0]["policy_decision"]["baseline"]["event_count"] == 2
    assert trend_items[0]["policy_decision"]["fresh"]["evidence_count"] == 1
    assert trend_items and "**A. 来自日报数据库沉淀的信号**" in trend_items[0]["body"]
    assert "**B. 来自周度新增探索的证据**" in trend_items[0]["body"]
    assert "**D. Executive Implications**" in trend_items[0]["body"]
    assert "2026-05-25：Samsung starts HBM qualification" in trend_items[0]["body"]
    assert "**B2. 新信息整合判断**" in trend_items[0]["body"]
    summary_items = [item for item in weekly_context["items"] if item["section_key"] == "executive_summary"]
    assert summary_items and "本周报不是日报合订本" not in summary_items[0]["body"]
    assert "议价权" in summary_items[0]["body"]
    assert [report["id"] for report in monthly_inputs["direct_reports"]] == ["report-storage-weekly-2026-W22"]
    fresh_items = [item for item in weekly_context["items"] if item["signal_type"] == "fresh_evidence_coverage"]
    assert fresh_items and "HBM 认证与产能相关证据" in fresh_items[0]["body"]
    assert fresh_items[0]["title"] == "本周新增探索覆盖 1 条证据"
    assert any(item["signal_type"] == "signal_noise" for item in weekly_context["items"])
    assert any(item["signal_type"] == "watchlist" for item in weekly_context["items"])
    assert "report-storage-quarterly-2026-Q2" in {
        entry["source_report_id"] for entry in yearly_lineage["lineage"] if entry.get("source_report_id")
    }


def test_synthesize_cascade_report_supports_custom_window(tmp_path, monkeypatch):
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration
    from stratum.db.service import get_report_context
    from stratum.db.synthesis import synthesize_cascade_report

    monkeypatch.setenv("STRATUM_DB_DIR", str(tmp_path))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()
    _seed_daily_inputs("storage")

    result = synthesize_cascade_report(
        "storage",
        "monthly",
        None,
        window_start="2026-05-25",
        window_end="2026-05-31",
    )

    assert result["period"] == "custom-2026-05-25_to_2026-05-31"
    assert result["window"]["period_kind"] == "custom_range"
    assert result["source_scales"] == ["daily", "weekly"]
    context = get_report_context("storage", "monthly", result["period"])
    assert context["report"]["id"] == "report-storage-monthly-custom-2026-05-25_to_2026-05-31"
    assert context["report_window"]["start"] == "2026-05-25"


def test_synthesize_report_manage_command(tmp_path, monkeypatch, capsys):
    from stratum.db.connection import get_db
    from stratum.db.manage import main
    from stratum.db.migration import apply_foundation_migration

    monkeypatch.setenv("STRATUM_DB_DIR", str(tmp_path / "db"))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()
    _seed_daily_inputs("storage")
    capsys.readouterr()

    assert main([
        "synthesize-report",
        "--domain",
        "storage",
        "--scale",
        "weekly",
        "--period",
        "2026-W22",
        "--db-dir",
        str(tmp_path / "db"),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_id"] == "report-storage-weekly-2026-W22"
    assert payload["source_scale"] == "daily"
    assert payload["stats"]["items"] >= 3


def test_synthesis_package_exposes_public_algorithm_components():
    from stratum.db.synthesis import (
        CitationRanker,
        IntegrationDecision,
        JudgmentFeedbackScorer,
        SynthesisPolicy,
        SynthesisTextBuilder,
        SynthesizedEventBuilder,
        ThemeRanker,
        build_report_payload,
        evaluate_theme,
        get_synthesis_policy_config,
        synthesize_cascade_report,
    )

    assert callable(synthesize_cascade_report)
    assert callable(build_report_payload)
    assert callable(evaluate_theme)
    assert get_synthesis_policy_config("weekly").strong_event_count <= get_synthesis_policy_config("yearly").strong_event_count
    assert SynthesisPolicy().__class__.__name__ == "SynthesisPolicy"
    assert ThemeRanker().__class__.__name__ == "ThemeRanker"
    assert CitationRanker().__class__.__name__ == "CitationRanker"
    assert JudgmentFeedbackScorer().__class__.__name__ == "JudgmentFeedbackScorer"
    assert SynthesizedEventBuilder().__class__.__name__ == "SynthesizedEventBuilder"
    assert SynthesisTextBuilder().__class__.__name__ == "SynthesisTextBuilder"
    assert IntegrationDecision("baseline_only", "no_fresh_lift").direction == "mixed_or_unknown"


def test_trend_body_expands_counted_signals_as_numbered_items():
    from stratum.db.synthesis import _trend_body

    body = _trend_body("weekly", "daily", [
        {"date": "2026-05-30", "title": "SK 海力士 HBM4 进入实质性量产", "priority": 1},
        {"date": "2026-05-30", "title": "三星 HBM4E 样品出货", "priority": 1},
        {"date": "2026-05-30", "title": "三巨头 HBM4E 竞赛加速", "priority": 1},
    ], [])

    assert "出现 3 个相关信号" in body
    assert "1. 2026-05-30：SK 海力士 HBM4 进入实质性量产" in body
    assert "2. 2026-05-30：三星 HBM4E 样品出货" in body
    assert "3. 2026-05-30：三巨头 HBM4E 竞赛加速" in body
    assert "\n\n读者不需要先看过日报" in body


def test_weekly_theme_body_keeps_daily_and_fresh_inputs_separate():
    from stratum.db.synthesis import _theme_body

    body = _theme_body("weekly", "daily", [
        {"date": "2026-05-30", "title": "SK 海力士 HBM4 进入实质性量产", "priority": 1},
        {"date": "2026-05-30", "title": "三星 HBM4E 样品出货", "priority": 1},
    ], [
        {"title": "客户认证补充验证"},
    ])

    assert "**本周判断**" in body
    assert "**A. 来自日报数据库沉淀的信号**" in body
    assert "1. 2026-05-30：SK 海力士 HBM4 进入实质性量产" in body
    assert "**B. 来自周度新增探索的证据**" in body
    assert "1. 客户认证补充验证" in body
    assert "**B2. 新信息整合判断**" in body
    assert "**D. Executive Implications**" in body
    assert "**F. 下周观察点**" in body


def test_synthesis_text_builder_owns_report_facing_copy_policy():
    from stratum.db.synthesis import SynthesisTextBuilder

    builder = SynthesisTextBuilder()
    body = builder.theme_body("weekly", "daily", [
        {"date": "2026-05-30", "title": "SK 海力士 HBM4 进入实质性量产", "priority": 1},
        {"date": "2026-05-30", "title": "三星 HBM4E 样品出货", "priority": 1},
    ], [
        {"title": "顧客認証に関する更新", "source": "Example JP", "term_ids": ["hbm"]},
        {"title": "Customer qualification update", "source": "Example Official", "term_ids": ["hbm"]},
    ])

    assert "**本周判断**" in body
    assert "**A. 来自日报数据库沉淀的信号**" in body
    assert "**B2. 新信息整合判断**" in body
    assert "Example JP" in body
    assert "顧客認証" not in body


def test_theme_ranker_prioritizes_priority_then_persistence():
    from stratum.db.synthesis import ThemeRanker

    groups = {
        "low-priority-many": {
            "thread_id": "low-priority-many",
            "events": [
                {"priority": 2, "date": "2026-05-28"},
                {"priority": 2, "date": "2026-05-29"},
                {"priority": 2, "date": "2026-05-30"},
            ],
        },
        "high-priority-one": {
            "thread_id": "high-priority-one",
            "events": [{"priority": 1, "date": "2026-05-27"}],
        },
        "high-priority-two": {
            "thread_id": "high-priority-two",
            "events": [
                {"priority": 1, "date": "2026-05-26"},
                {"priority": 1, "date": "2026-05-30"},
            ],
        },
    }

    ranked = ThemeRanker().rank_thread_groups(groups)

    assert [group["thread_id"] for group in ranked] == [
        "high-priority-two",
        "high-priority-one",
        "low-priority-many",
    ]
    assert ranked[0]["event_count"] == 2
    assert ranked[0]["latest"] == "2026-05-30"


def test_theme_ranker_uses_impact_evidence_and_uncertainty_features():
    from stratum.db.synthesis import ThemeRanker

    groups = {
        "generic-many": {
            "thread_id": "generic-many",
            "events": [
                {"priority": 1, "date": "2026-05-27", "title": "General memory update", "confidence": "B"},
                {"priority": 1, "date": "2026-05-28", "title": "General storage update", "confidence": "B"},
                {"priority": 1, "date": "2026-05-29", "title": "General semiconductor update", "confidence": "B"},
            ],
        },
        "impact-supported": {
            "thread_id": "impact-supported",
            "events": [
                {
                    "priority": 1,
                    "date": "2026-05-28",
                    "title": "NVIDIA customer qualification increases HBM supply impact",
                    "confidence": "A",
                    "article_ids": ["a-1", "a-2"],
                    "source_domains": ["official.example", "analyst.example"],
                    "term_ids": ["hbm"],
                    "entity_ids": ["nvidia"],
                },
                {
                    "priority": 1,
                    "date": "2026-05-30",
                    "title": "HBM capacity and yield expansion supports AI data center revenue",
                    "confidence": "A",
                    "article_ids": ["a-3"],
                    "source_domains": ["media.example"],
                    "term_ids": ["hbm"],
                    "entity_ids": ["sk-hynix"],
                },
            ],
        },
        "speculative": {
            "thread_id": "speculative",
            "events": [
                {"priority": 1, "date": "2026-05-30", "title": "Rumor says HBM could increase", "confidence": "C"},
                {"priority": 1, "date": "2026-05-31", "title": "Unconfirmed HBM report", "confidence": "D"},
            ],
        },
    }

    ranked = ThemeRanker().rank_thread_groups(groups)

    assert [group["thread_id"] for group in ranked] == [
        "impact-supported",
        "generic-many",
        "speculative",
    ]
    assert ranked[0]["impact_score"] > ranked[1]["impact_score"]
    assert ranked[0]["evidence_quality"] > ranked[1]["evidence_quality"]
    assert ranked[2]["uncertainty_score"] > ranked[1]["uncertainty_score"]


def test_theme_ranker_uses_thread_lifecycle_score_for_higher_scale_priority():
    from stratum.db.synthesis import ThemeRanker
    from stratum.subsystems.event_thread import ThreadLifecycleScorer

    groups = {
        "cooling-story": {
            "thread_id": "cooling-story",
            "events": [
                {"priority": 1, "date": "2026-05-30", "status": "cooling", "title": "Cooling HBM follow-up"},
            ],
        },
        "active-story": {
            "thread_id": "active-story",
            "events": [
                {"priority": 1, "date": "2026-05-29", "status": "active", "title": "Active HBM qualification"},
            ],
        },
    }

    ranked = ThemeRanker().rank_thread_groups(groups)

    assert ThreadLifecycleScorer().score_status(status="active") > ThreadLifecycleScorer().score_status(status="cooling")
    assert [group["thread_id"] for group in ranked] == ["active-story", "cooling-story"]
    assert ranked[0]["lifecycle_score"] > ranked[1]["lifecycle_score"]
    assert ranked[1]["lifecycle_momentum"] == "cooling"


def test_judgment_feedback_scorer_matches_threads_and_entities():
    from stratum.db.synthesis import JudgmentFeedbackScorer

    group = {
        "thread_id": "et-hbm",
        "events": [
            {
                "thread_id": "et-hbm",
                "entity_ids": ["samsung"],
                "date": "2026-05-30",
            }
        ],
    }
    feedback = JudgmentFeedbackScorer().score_group(group, [
        {"id": "jd-thread", "target_thread_ids": ["et-hbm"], "result": "supported"},
        {"id": "jd-entity", "target_entity_ids": ["samsung"], "result": "challenged"},
        {"id": "jd-other", "target_thread_ids": ["et-nand"], "result": "supported"},
    ])

    assert feedback.status == "mixed"
    assert feedback.supported_count == 1
    assert feedback.challenged_count == 1
    assert feedback.score < 0
    assert feedback.matched_judgment_ids == ["jd-thread", "jd-entity"]


def test_theme_ranker_uses_judgment_feedback_to_adjust_importance():
    from stratum.db.synthesis import ThemeRanker

    groups = {
        "supported-story": {
            "thread_id": "supported-story",
            "events": [
                {"thread_id": "supported-story", "priority": 1, "date": "2026-05-30", "title": "HBM qualification"},
            ],
        },
        "challenged-story": {
            "thread_id": "challenged-story",
            "events": [
                {"thread_id": "challenged-story", "priority": 1, "date": "2026-05-30", "title": "HBM qualification"},
            ],
        },
    }
    judgments = [
        {"id": "jd-supported", "target_thread_ids": ["supported-story"], "result": "supported"},
        {"id": "jd-challenged", "target_thread_ids": ["challenged-story"], "result": "invalidated"},
    ]

    ranked = ThemeRanker().rank_thread_groups(groups, judgments=judgments)

    assert [group["thread_id"] for group in ranked] == ["supported-story", "challenged-story"]
    assert ranked[0]["judgment_feedback_status"] == "supported"
    assert ranked[1]["judgment_feedback_status"] == "challenged"
    assert ranked[0]["importance_score"] > ranked[1]["importance_score"]


def test_judgment_feedback_scorer_uses_richer_review_state_effects():
    from stratum.db.synthesis import JudgmentFeedbackScorer

    group = {
        "thread_id": "et-hbm",
        "events": [{"thread_id": "et-hbm", "entity_ids": ["samsung"]}],
    }

    feedback = JudgmentFeedbackScorer().score_group(group, [
        {"id": "jd-expired", "target_thread_ids": ["et-hbm"], "result": "expired"},
        {"id": "jd-deferred", "target_entity_ids": ["samsung"], "result": "deferred"},
    ])

    assert feedback.status == "challenged"
    assert feedback.challenged_count == 1
    assert feedback.pending_count == 1
    assert feedback.score == -4


def test_synthesized_event_builder_owns_title_confidence_and_limits():
    from stratum.db.synthesis import SynthesizedEventBuilder

    builder = SynthesizedEventBuilder()
    events = builder.build(
        report_id="report-storage-weekly-2026-W22",
        target_scale="weekly",
        target_period="2026-W22",
        event_date="2026-05-31",
        thread_groups=[{
            "thread_id": "et-hbm-race",
            "events": [
                {
                    "id": "ev-1",
                    "thread_id": "et-hbm-race",
                    "date": "2026-05-30",
                    "title": "SK 海力士 HBM4 进入实质性量产",
                    "priority": 1,
                    "confidence": "A",
                    "article_ids": [f"a-{i}" for i in range(25)],
                    "entity_ids": ["sk-hynix"],
                    "term_ids": ["hbm"],
                    "source_domains": ["example.com"],
                },
                {
                    "id": "ev-2",
                    "thread_id": "et-hbm-race",
                    "date": "2026-05-31",
                    "title": "Samsung HBM4 customer qualification update",
                    "priority": 2,
                    "confidence": "C",
                    "article_ids": ["a-extra"],
                    "entity_ids": ["samsung"],
                    "term_ids": ["hbm4"],
                    "source_domains": ["samsung.com"],
                },
            ],
        }],
    )

    assert events[0]["id"] == "ev-2026-W22-et-hbm-race"
    assert events[0]["title"].startswith("HBM 认证与产能：")
    assert events[0]["confidence"] == "C"
    assert events[0]["priority"] == 1
    assert len(events[0]["article_ids"]) == 20
    assert events[0]["source_event_ids"] == ["ev-1", "ev-2"]


def test_citation_ranker_prefers_official_relevant_fresh_evidence():
    from stratum.db.synthesis import CitationRanker

    articles = [
        {
            "id": "media",
            "title": "HBM market roundup",
            "source_type": "media",
            "term_ids": ["hbm"],
        },
        {
            "id": "official",
            "title": "Samsung HBM4 customer qualification update",
            "source_type": "official",
            "term_ids": ["hbm"],
            "entity_ids": ["samsung"],
            "query_dimension": "thread_watch",
        },
    ]

    ranked = CitationRanker().rank_articles_for_theme("HBM 认证与产能", articles)

    assert [article["id"] for article in ranked] == ["official", "media"]


def test_synthesis_policy_classifies_domain_specific_fresh_evidence():
    from stratum.db.synthesis import SynthesisPolicy, classify_evidence_class

    articles = [
        {
            "id": "customer",
            "title": "NVIDIA selected Samsung HBM4 for next platform",
            "source_type": "official",
        },
        {
            "id": "financial",
            "title": "Micron earnings release reports revenue increased",
            "source_type": "financial",
        },
        {
            "id": "validation",
            "title": "HBM4 customer qualification validation advances",
            "source_type": "media",
        },
    ]

    assessment = SynthesisPolicy().assess_fresh_evidence(articles)

    assert classify_evidence_class(articles[0]) == "customer_commitment"
    assert assessment.high_quality_count == 3
    assert assessment.evidence_class_counts == {
        "customer_commitment": 1,
        "financial_outcome": 1,
        "technical_validation": 1,
    }
    assert assessment.dominant_evidence_class == "customer_commitment"


def test_citation_ranker_prefers_customer_commitment_evidence_for_ties():
    from stratum.db.synthesis import CitationRanker

    articles = [
        {
            "id": "validation",
            "title": "Samsung HBM4 qualification update",
            "source_type": "official",
            "term_ids": ["hbm"],
            "entity_ids": ["samsung"],
        },
        {
            "id": "customer",
            "title": "NVIDIA selected Samsung HBM4",
            "source_type": "official",
            "term_ids": ["hbm"],
            "entity_ids": ["samsung", "nvidia"],
        },
    ]

    ranked = CitationRanker().rank_articles_for_theme("HBM 认证与产能", articles)

    assert [article["id"] for article in ranked] == ["customer", "validation"]


def test_citation_ranker_selects_diverse_counter_evidence_representatives():
    from stratum.db.synthesis import CitationRanker

    articles = [
        {
            "id": "media-a",
            "title": "HBM market roundup",
            "source": "media-a.example",
            "source_type": "media",
            "term_ids": ["hbm"],
        },
        {
            "id": "media-b",
            "title": "HBM4 ramp increase",
            "source": "media-b.example",
            "source_type": "media",
            "term_ids": ["hbm"],
        },
        {
            "id": "official",
            "title": "Samsung HBM4 customer qualification approved",
            "source": "samsung.com",
            "source_type": "official",
            "term_ids": ["hbm"],
            "entity_ids": ["samsung"],
            "query_dimension": "thread_watch",
        },
        {
            "id": "counter",
            "title": "NVIDIA HBM qualification delayed",
            "source": "analyst.example",
            "source_type": "analyst",
            "term_ids": ["hbm"],
            "entity_ids": ["nvidia"],
        },
    ]

    selected = CitationRanker(max_per_theme=3).representative_articles_for_theme(
        "HBM 认证与产能",
        articles,
    )

    assert [article["id"] for article in selected] == ["official", "counter", "media-b"]


def test_synthesis_policy_handles_scale_independent_integration():
    from stratum.db.synthesis import assess_baseline, assess_fresh_evidence, decide_integration

    baseline = assess_baseline([
        {"date": "2026-05-01", "title": "HBM qualification advances"},
        {"date": "2026-05-08", "title": "HBM supply expansion"},
        {"date": "2026-05-15", "title": "HBM validation progresses"},
    ])
    fresh = assess_fresh_evidence([
        {"source": "Example Official", "source_type": "official", "title": "Customer qualification approved"},
        {"source": "Example Analyst", "source_type": "analyst", "title": "HBM ramp increase"},
        {"source": "Example Media", "source_type": "media", "title": "Supply growth continues"},
    ])
    decision = decide_integration(target_scale="monthly", baseline=baseline, fresh=fresh)

    assert baseline.strength == "strong"
    assert baseline.direction == "positive_momentum"
    assert fresh.quality == "strong"
    assert fresh.direction == "positive_momentum"
    assert decision.role == "baseline_confirmed_by_fresh"
    assert decision.confidence_effect == "raise"
    assert decision.direction == "positive_momentum"


def test_synthesis_policy_keeps_fresh_only_signal_as_watch_item():
    from stratum.db.synthesis import assess_baseline, assess_fresh_evidence, decide_integration

    decision = decide_integration(
        target_scale="quarterly",
        baseline=assess_baseline([{"date": "2026-05-01", "title": "单点信号"}]),
        fresh=assess_fresh_evidence([
            {"source": "Official", "source_type": "official"},
            {"source": "Analyst", "source_type": "analyst"},
            {"source": "Media", "source_type": "media"},
        ]),
    )

    assert decision.role == "fresh_leads_watch"
    assert decision.confidence_effect == "watch_only"


def test_synthesis_policy_supports_configurable_thresholds():
    from stratum.db.synthesis import SynthesisPolicy, SynthesisPolicyConfig

    policy = SynthesisPolicy(SynthesisPolicyConfig(strong_event_count=2))
    evaluation = policy.evaluate(
        target_scale="yearly",
        events=[
            {"date": "2026-01-01", "title": "信号 A"},
            {"date": "2026-01-02", "title": "信号 B"},
        ],
        fresh_articles=[],
    )

    assert evaluation.baseline.strength == "strong"
    assert evaluation.fresh.quality == "absent"
    assert evaluation.decision.role == "baseline_only"


def test_synthesis_policy_uses_scale_specific_threshold_profiles():
    from stratum.db.synthesis import evaluate_theme, get_synthesis_policy_config

    events = [
        {"date": "2026-05-01", "title": "HBM qualification advances"},
        {"date": "2026-05-08", "title": "HBM supply expansion"},
        {"date": "2026-05-15", "title": "HBM validation progresses"},
    ]

    weekly = evaluate_theme(target_scale="weekly", events=events, fresh_articles=[])
    yearly = evaluate_theme(target_scale="yearly", events=events, fresh_articles=[])

    assert get_synthesis_policy_config("weekly").strong_event_count == 3
    assert get_synthesis_policy_config("yearly").strong_event_count == 6
    assert weekly.baseline.strength == "strong"
    assert yearly.baseline.strength == "weak"
    assert weekly.decision.role == "baseline_only"
    assert yearly.decision.role == "baseline_only"


def test_runtime_profiles_declare_synthesis_policy_profile_without_algorithm_logic():
    from stratum.temporal.profiles import get_timescale_profile

    assert get_timescale_profile("daily").synthesis_policy_profile is None
    assert get_timescale_profile("weekly").synthesis_policy_profile == "weekly"
    assert get_timescale_profile("monthly").synthesis_policy_profile == "monthly"
    assert get_timescale_profile("quarterly").synthesis_policy_profile == "quarterly"
    assert get_timescale_profile("yearly").synthesis_policy_profile == "yearly"


def test_synthesis_policy_detects_fresh_evidence_challenge_direction():
    from stratum.db.synthesis import SynthesisPolicy, SynthesisPolicyConfig

    policy = SynthesisPolicy(SynthesisPolicyConfig(strong_fresh_count=4))
    evaluation = policy.evaluate(
        target_scale="weekly",
        events=[
            {"date": "2026-05-29", "title": "HBM qualification advances"},
            {"date": "2026-05-30", "title": "HBM supply expansion"},
        ],
        fresh_articles=[
            {"source": "Analyst", "source_type": "analyst", "title": "Customer validation delayed"},
            {"source": "Media", "source_type": "media", "title": "HBM ramp pushed back"},
        ],
    )

    assert evaluation.baseline.direction == "positive_momentum"
    assert evaluation.fresh.direction == "negative_momentum"
    assert evaluation.decision.role == "fresh_challenges_baseline"
    assert evaluation.decision.conflict_level == "medium"
    assert evaluation.decision.confidence_effect == "hold"


def test_synthesis_policy_detects_strong_fresh_contradiction():
    from stratum.db.synthesis import SynthesisPolicy

    evaluation = SynthesisPolicy().evaluate(
        target_scale="monthly",
        events=[
            {"date": "2026-05-01", "title": "HBM certification advances"},
            {"date": "2026-05-08", "title": "HBM validation passes"},
            {"date": "2026-05-15", "title": "HBM supply expansion"},
        ],
        fresh_articles=[
            {"source": "Official", "source_type": "official", "title": "HBM qualification failed"},
            {"source": "Analyst", "source_type": "analyst", "title": "Customer validation delayed"},
            {"source": "Media", "source_type": "media", "title": "HBM ramp cut"},
        ],
    )

    assert evaluation.baseline.strength == "strong"
    assert evaluation.fresh.quality == "strong"
    assert evaluation.decision.role == "fresh_contradicts_baseline"
    assert evaluation.decision.conflict_level == "high"
    assert evaluation.decision.confidence_effect == "lower_or_split"


def test_integration_text_renders_fresh_contradiction_as_split_judgment():
    from stratum.db.synthesis.evidence import integration_decision_text

    body = integration_decision_text(
        target_scale="monthly",
        scale_label="月度",
        events=[
            {"date": "2026-05-01", "title": "HBM certification advances"},
            {"date": "2026-05-08", "title": "HBM validation passes"},
            {"date": "2026-05-15", "title": "HBM supply expansion"},
        ],
        fresh_evidence=[
            {"source": "Official", "source_type": "official", "title": "HBM qualification failed"},
            {"source": "Analyst", "source_type": "analyst", "title": "Customer validation delayed"},
            {"source": "Media", "source_type": "media", "title": "HBM ramp cut"},
        ],
    )

    assert "方向相反" in body
    assert "不应把两类证据合并成单一月度确认结论" in body
    assert "降低或拆分当前置信度" in body


def test_judgment_body_expands_reviewed_and_pending_as_numbered_items():
    from stratum.db.synthesis import _judgment_body

    body = _judgment_body(
        [
            {"hypothesis": "判断 A"},
            {"hypothesis": "判断 B"},
        ],
        [
            {"hypothesis": "待验证 A"},
            {"hypothesis": "待验证 B"},
        ],
    )

    assert "已复核：\n\n1. 判断 A\n2. 判断 B" in body
    assert "待验证：\n\n1. 待验证 A\n2. 待验证 B" in body


def test_judgment_body_marks_no_completed_reviews_without_duplication():
    from stratum.db.synthesis import _judgment_body

    body = _judgment_body([], [
        {"hypothesis": "待验证 A"},
        {"hypothesis": "待验证 A"},
    ])

    assert "已复核：本期没有完成状态更新的判断。" in body
    assert body.count("待验证 A") == 1
    assert "1. 待验证 A" in body
    assert "2. 待验证 A" not in body
