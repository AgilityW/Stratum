"""End-to-end tests for replayable multi-scale database cascade behavior."""

from __future__ import annotations


def _build_fixture(tmp_path, monkeypatch):
    from stratum.db.cascade_fixture import build_constructed_cascade

    monkeypatch.setenv("STRATUM_DB_DIR", str(tmp_path))
    return build_constructed_cascade("storage")


def test_constructed_cascade_replays_daily_to_yearly_through_one_database(tmp_path, monkeypatch):
    snapshot = _build_fixture(tmp_path, monkeypatch)

    assert [(run["scale"], run["source_reports"], run["fresh_evidence"]) for run in snapshot["synthesis_runs"]] == [
        ("weekly", 4, 1),
        ("monthly", 5, 1),
        ("quarterly", 6, 1),
        ("yearly", 7, 1),
    ]
    assert snapshot["weekly_inputs"]["source_scales"] == ["daily"]
    assert snapshot["monthly_inputs"]["source_scales"] == ["daily", "weekly"]
    assert snapshot["quarterly_inputs"]["source_scales"] == ["daily", "weekly", "monthly"]
    assert snapshot["yearly_inputs"]["source_scales"] == ["daily", "weekly", "monthly", "quarterly"]

    assert [report["id"] for report in snapshot["weekly_inputs"]["reports"]] == [
        "report-storage-daily-2026-05-25",
        "report-storage-daily-2026-05-27",
        "report-storage-daily-2026-05-29",
        "report-storage-daily-2026-05-31",
    ]
    assert [report["id"] for report in snapshot["yearly_inputs"]["reports"]] == [
        "report-storage-daily-2026-05-25",
        "report-storage-daily-2026-05-27",
        "report-storage-daily-2026-05-29",
        "report-storage-daily-2026-05-31",
        "report-storage-weekly-2026-W22",
        "report-storage-monthly-2026-05",
        "report-storage-quarterly-2026-Q2",
    ]


def test_constructed_cascade_preserves_trends_judgments_evidence_and_lineage(tmp_path, monkeypatch):
    snapshot = _build_fixture(tmp_path, monkeypatch)

    assert snapshot["daily_trend"]["event_count"] == 4
    assert snapshot["daily_trend"]["top_threads"][0] == {"id": "et-hbm-race", "count": 3}
    assert snapshot["daily_trend"]["top_terms"][0] == {"id": "hbm", "count": 3}
    assert snapshot["judgment_status"]["counts"] == {"supported": 1, "pending": 1}
    assert [event["id"] for event in snapshot["key_events"][:2]] == [
        "ev-2026-05-25-hbm",
        "ev-2026-05-27-hbm",
    ]
    assert [entry["period"] for entry in snapshot["key_timeline"]] == [
        "2026-05-25",
        "2026-05-27",
        "2026-05-29",
        "2026-05-31",
    ]
    assert set(snapshot["technology_progress"]) == {"samsung", "sk-hynix", "micron"}

    weekly_article_ids = [article["id"] for article in snapshot["weekly_item_evidence"]["articles"]]
    assert weekly_article_ids == [
        "a-20260525-hbm",
        "a-20260527-hbm",
        "a-20260531-hbm",
        "a-weekly-2026-W22-official-hbm",
    ]

    yearly_report = snapshot["yearly_context"]["report"]
    yearly_items = {item["id"]: item for item in snapshot["yearly_context"]["items"]}
    assert yearly_report["id"] == "report-storage-yearly-2026"
    assert yearly_items["report-storage-yearly-2026-summary"]["title"] == "年度结论"
    assert yearly_items["report-storage-yearly-2026-fresh-evidence"]["title"] == "新增验证：本年补充信号"
    assert yearly_items["report-storage-yearly-2026-lineage"]["title"] == "本周期参考 7 份下级报告"
    assert "来源 ID 保存在数据库 lineage 中" in yearly_items["report-storage-yearly-2026-lineage"]["body"]

    lineage = snapshot["yearly_lineage"]["lineage"]
    consumed_reports = {
        entry["source_report_id"]
        for entry in lineage
        if entry.get("relation") == "consumes" and entry.get("source_report_id")
    }
    assert consumed_reports == {
        "report-storage-daily-2026-05-25",
        "report-storage-daily-2026-05-27",
        "report-storage-daily-2026-05-29",
        "report-storage-daily-2026-05-31",
        "report-storage-weekly-2026-W22",
        "report-storage-monthly-2026-05",
        "report-storage-quarterly-2026-Q2",
    }
    assert any(entry.get("relation") == "fresh_evidence" for entry in lineage)
