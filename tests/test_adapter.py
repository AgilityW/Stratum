"""MCP adapter regression tests."""

from __future__ import annotations

import json


def test_mcp_adapter_package_exports_stable_surfaces():
    import stratum.mcp_adapter as mcp_adapter

    assert "list_tools" in mcp_adapter.__all__
    assert "get_tool" in mcp_adapter.__all__
    assert "call_tool" in mcp_adapter.__all__


def test_mcp_adapter_lists_analysis_and_context_tools():
    from stratum.mcp_adapter import get_tool, list_tools

    names = {tool["name"] for tool in list_tools()}
    assert "source_trace_run" in names
    assert "signal_bursts_run" in names
    assert "signal_awareness_run" in names
    assert "discovery_diagnostics_build" in names
    assert "source_expansion_evaluate" in names
    assert "report_context_get" in names
    assert "story_context_get" in names
    assert "signal_awareness_config_get" in names
    assert "report_evaluation_run" in names
    assert "watch_queries_generate" in names
    assert "signal_aware_daily_attach" in names
    assert "thread_timeline_get" in names
    assert "thread_keyword_events_get" in names
    assert "entity_timeline_get" in names
    assert "technology_progress_get" in names
    assert "trend_summary_get" in names
    assert "key_events_get" in names
    assert "key_timeline_get" in names
    assert "judgment_status_get" in names
    assert "due_judgments_get" in names
    assert "active_search_queries_load" in names
    assert "search_engine_health_load" in names
    assert "search_engine_health_get" in names
    assert "report_item_evidence_get" in names
    assert "report_lineage_trace" in names
    assert "cascade_inputs_get" in names
    assert "briefing_context_generate" in names
    assert "thread_lifecycle_diagnostics" in names
    assert "synthesis_policy_config_get" in names

    tool = get_tool("signal_awareness_run")
    assert tool["capability"] == "signal_awareness.run"
    assert tool["input_schema"]["required"] == ["domain", "records"]

    discovery_tool = get_tool("discovery_diagnostics_build")
    assert discovery_tool["capability"] == "discovery_diagnostics.build"

    watch_tool = get_tool("watch_queries_generate")
    assert watch_tool["capability"] == "watch_queries.generate"

    timeline_tool = get_tool("thread_timeline_get")
    assert timeline_tool["capability"] == "thread_timeline.get"

    synthesis_tool = get_tool("synthesis_policy_config_get")
    assert synthesis_tool["capability"] == "synthesis_policy_config.get"

    evidence_tool = get_tool("report_item_evidence_get")
    assert evidence_tool["capability"] == "report_item_evidence.get"

    health_tool = get_tool("search_engine_health_load")
    assert health_tool["capability"] == "search_engine_health.load"


def test_mcp_adapter_calls_capability_layer(tmp_path):
    from stratum.mcp_adapter import call_tool

    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4","status":"accept","accepted":true}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "HBM4"}
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "HBM4"}
    ]))

    result = call_tool("source_trace_run", {
        "input_dir": str(tmp_path),
    })

    assert result["status"] == "ok"
    assert result["capability_result"]["capability"] == "source_trace.run"
    assert result["capability_result"]["payload"]["source_trace_summary"]["status"] == "ok"


def test_mcp_adapter_reports_unknown_tool():
    from stratum.mcp_adapter import call_tool

    result = call_tool("unknown_tool", {})

    assert result["status"] == "error"
    assert result["error"]["type"] == "UnknownMcpTool"
