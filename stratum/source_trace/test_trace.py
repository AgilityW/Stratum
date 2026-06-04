"""SourceTrace module tests."""

from __future__ import annotations

import json

from stratum.source_trace import run_source_trace
from stratum.source_trace.charts import build_charts, charts_markdown
from stratum.source_trace.conversion import build_conversion_trace
from stratum.source_trace.loader import load_inputs


def test_loader_isolates_bad_jsonl_rows(tmp_path):
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4"}\n'
        '{not-json}\n'
    )

    payload = load_inputs(str(tmp_path))

    assert len(payload["watchlist_candidates"]) == 1
    assert payload["watchlist_candidates"][0]["canonical_url"] == "https://example.com/a"
    assert payload["watchlist_candidates_errors"][0]["line"] == 2


def test_runner_surfaces_input_errors_in_summary_and_issues(tmp_path):
    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4"}\n'
        '{not-json}\n'
    )
    outputs = run_source_trace(str(tmp_path))

    assert outputs["source_trace_summary"]["input_errors"]["watchlist_observations"] == 1
    issue_codes = {item["code"] for item in outputs["issues"]["issues"]}
    assert "malformed_input_rows" in issue_codes


def test_conversion_trace_marks_unjudged_and_rejected_misses():
    trace = build_conversion_trace(
        watchlist_observations=[
            {"canonical_url": "https://example.com/unjudged", "title": "Unjudged signal"},
            {"canonical_url": "https://example.com/rejected", "title": "Rejected signal"},
        ],
        discovery_observations=[],
        watchlist_candidates=[
            {"canonical_url": "https://example.com/rejected", "status": "reject"},
        ],
        discovery_candidates=[],
        watchlist_results=[],
        raw_results=[],
        db_context={
            "articles": [
                {"canonical_url": "https://example.com/unjudged"},
                {"canonical_url": "https://example.com/rejected"},
            ],
            "persisted_articles": [],
        },
    )

    by_url = {item["canonical_url"]: item for item in trace["items"]}

    assert by_url["https://example.com/unjudged"]["miss_type"] == "unjudged_miss"
    assert by_url["https://example.com/rejected"]["miss_type"] == "rejected_or_pruned_miss"
    assert trace["totals"]["unjudged_misses"] == 1
    assert trace["totals"]["rejected_or_pruned_misses"] == 1


def test_runner_writes_structured_outputs_and_mermaid_charts(tmp_path):
    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","access":"rss","url":"https://example.com/a","title":"Read More"}\n'
        '{"source":"feed-a","access":"rss","url":"https://example.com/b","title":"HBM4 qualification","published_at":"2026-05-30"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","access":"rss","url":"https://example.com/a","title":"Read More","status":"reject","accepted":false,"score":0.0,"reason":"boilerplate"}\n'
        '{"source":"feed-a","access":"rss","url":"https://example.com/b","title":"HBM4 qualification","status":"accept","accepted":true,"score":1.0,"reason":"domain keyword"}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {
            "source": "feed-a",
            "engine": "rss:feed-a",
            "url": "https://example.com/b",
            "title": "HBM4 qualification",
            "published_at": "2026-05-30",
        }
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {
            "source": "feed-a",
            "engine": "rss:feed-a",
            "url": "https://example.com/b",
            "title": "HBM4 qualification",
            "published_at": "2026-05-30",
        }
    ]))

    outputs = run_source_trace(str(tmp_path), write_csv=True)
    output_dir = tmp_path / "source_trace"

    assert outputs["source_trace_summary"]["observation_totals"]["watchlist_observations"] == 2
    assert outputs["source_trace_summary"]["conversion_totals"]["observed"] == 2
    assert outputs["source_quality"][0]["source"] == "feed-a"
    assert (output_dir / "source_trace_summary.json").exists()
    assert (output_dir / "source_quality.json").exists()
    assert (output_dir / "source_trace_charts.md").read_text().count("```mermaid") == 3
    assert (output_dir / "source_quality.csv").exists()


def test_runner_continues_with_discovery_only_inputs(tmp_path):
    (tmp_path / "discovery_observations.jsonl").write_text(
        '{"source":"tavily","engine":"tavily","url":"https://example.com/c","title":"NAND pricing signal"}\n'
    )
    (tmp_path / "discovery_candidates.jsonl").write_text(
        '{"source":"tavily","engine":"tavily","url":"https://example.com/c","title":"NAND pricing signal","status":"selected","selected":true}\n'
    )

    outputs = run_source_trace(str(tmp_path))

    assert outputs["source_trace_summary"]["status"] == "ok"
    assert outputs["source_trace_summary"]["input_status"]["mode"] == "discovery_only"
    assert outputs["source_trace_summary"]["observation_totals"]["discovery_observations"] == 1


def test_runner_reports_empty_watchlist_and_discovery_as_normal_error(tmp_path):
    outputs = run_source_trace(str(tmp_path))
    summary_path = tmp_path / "source_trace" / "source_trace_summary.json"

    assert outputs["source_trace_summary"]["status"] == "error"
    assert outputs["source_trace_summary"]["input_status"]["mode"] == "no_input"
    assert summary_path.exists()
    assert json.loads(summary_path.read_text())["input_status"]["message"].startswith("no watchlist")


def test_chart_renderer_outputs_mermaid_blocks():
    charts = build_charts(
        summary={"funnel_totals": {"seen": 3, "admitted": 2, "consumed": 1}},
        quality=[{"source": "feed-a", "quality_score": 0.75}],
        observation_health={"watchlist": {"totals": {"observations": 3, "candidates": 2}}},
    )
    markdown = charts_markdown(charts)

    assert "flowchart LR" in charts["funnel"]
    assert "xychart-beta" in charts["quality"]
    assert markdown.count("```mermaid") == 3
