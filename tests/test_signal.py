"""Tests for the signal-awareness attach entrypoint."""

from __future__ import annotations

import json
from pathlib import Path


def test_render_review_summarizes_actions():
    from stratum.orchestrator.signal_attach import render_review

    markdown = render_review({
        "domain": "storage",
        "run_date": "2026-06-03",
        "diagnostics": {
            "record_count": 12,
            "anomalous_topics": 1,
            "detected_anchors": 1,
        },
        "topic_signals": [{
            "topic_id": "memory",
            "current_count": 6,
            "baseline_mean": 2.0,
            "z_score": 4.0,
        }],
        "activation_plan": {
            "actions": [{
                "anchor_name": "Computex 2026",
                "action": "activate",
                "reason": "lead_window_or_confirmed_burst",
                "query_injections": ["computex 2026 storage"],
                "temporary_sources": ["computex-rss"],
            }]
        },
        "unanchored_clusters": [{
            "label": "Taipei Ssd",
            "record_count": 2,
            "sources": ["feed-a", "feed-b"],
        }],
    })

    assert "# Signal Review" in markdown
    assert "Computex 2026" in markdown
    assert "Taipei Ssd" in markdown


def test_run_attach_writes_outputs_and_history(tmp_path):
    from stratum.orchestrator.signal_attach import run_attach

    reports_dir = tmp_path / "Reports"
    data_dir = reports_dir / "storage" / "data" / "2026-06-03"
    data_dir.mkdir(parents=True)
    (data_dir / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"Computex 2026 preview for SSD vendors","snippet":"Taipei booth preview"}\n'
    )
    (data_dir / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"Computex 2026 preview for SSD vendors","status":"accept","accepted":true}\n'
    )
    (data_dir / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "Computex 2026 preview for SSD vendors"}
    ]))
    (data_dir / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "Computex 2026 preview for SSD vendors"}
    ]))

    result = run_attach(
        domain_id="storage",
        run_date="2026-06-03",
        reports_dir=str(reports_dir),
        data_dir=str(data_dir),
    )

    assert Path(result["paths"]["signal_awareness"]).exists()
    assert Path(result["paths"]["signal_activation_plan"]).exists()
    assert Path(result["paths"]["signal_review_md"]).exists()
    assert Path(result["paths"]["history"]).exists()
    assert Path(result["paths"]["state"]).exists()
