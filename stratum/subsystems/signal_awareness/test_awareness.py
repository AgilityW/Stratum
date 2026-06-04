"""Signal-awareness subsystem tests."""

from __future__ import annotations

import json

from stratum.subsystems.signal_awareness import (
    build_activation_plan,
    detect_signal_awareness,
    normalize_anchor_registry,
    normalize_topic_rules,
    summarize_anchor_mentions,
    write_signal_awareness,
)


def test_normalizers_accept_topic_and_anchor_shapes():
    topics = normalize_topic_rules([
        "Semiconductor",
        {"id": "memory", "keywords": ["HBM", "DDR5"]},
    ])
    anchors = normalize_anchor_registry([
        {"name": "Computex 2026", "aliases": ["COMPUTEX"], "locations": ["Taipei"]},
    ])

    assert topics[0]["id"] == "semiconductor"
    assert "hbm" in topics[1]["keywords"]
    assert anchors[0]["id"] == "computex_2026"
    assert "computex" in anchors[0]["aliases"]


def test_detect_signal_awareness_activates_confirmed_anchor(tmp_path):
    payload = detect_signal_awareness(
        domain="storage",
        run_date="2026-05-20",
        records=[
            {
                "source": "tomshardware",
                "source_type_hint": "media",
                "title": "Computex 2026 preview: HBM and SSD vendors head to Taipei",
                "snippet": "Micron, Samsung, and SK hynix prepare booth demos in Taipei.",
                "entities": ["Micron", "Samsung", "SK hynix"],
            },
            {
                "source": "company-news",
                "source_type_hint": "official",
                "title": "Phison joins Computex 2026 with PCIe Gen6 SSD keynote",
                "snippet": "The company will present at its Taipei booth during the show.",
                "entities": ["Phison"],
            },
            {
                "source": "blocksandfiles",
                "source_type_hint": "media",
                "title": "Computex 2026 expected to spotlight storage controllers",
                "snippet": "Analysts preview keynote and exhibitor agenda.",
                "entities": ["Silicon Motion"],
            },
        ],
        topic_rules=[
            {"id": "semiconductor", "keywords": ["hbm", "ssd", "controller", "storage"]},
        ],
        historical_snapshots=[
            {"date": "2026-05-17", "topic_counts": {"semiconductor": 2}, "anchor_counts": {"computex_2026": 0}},
            {"date": "2026-05-18", "topic_counts": {"semiconductor": 1}, "anchor_counts": {"computex_2026": 0}},
            {"date": "2026-05-19", "topic_counts": {"semiconductor": 2}, "anchor_counts": {"computex_2026": 1}},
        ],
        anchor_registry=[
            {
                "name": "Computex 2026",
                "aliases": ["COMPUTEX"],
                "topics": ["semiconductor"],
                "locations": ["Taipei"],
                "start_date": "2026-06-02",
                "end_date": "2026-06-05",
                "lead_days": 21,
                "query_terms": ["computex 2026 storage", "computex 2026 ssd"],
                "temporary_sources": ["computex-rss"],
                "direct_fetch_targets": ["https://www.computexonline.com.tw/"],
            }
        ],
    )

    assert payload["diagnostics"]["anomalous_topics"] == 1
    assert payload["diagnostics"]["detected_anchors"] == 1
    assert payload["anchor_signals"][0]["window_status"] == "lead_window"
    assert payload["activation_plan"]["actions"][0]["action"] == "activate"
    assert payload["activation_plan"]["actions"][0]["query_injections"]

    paths = write_signal_awareness(str(tmp_path), payload)
    awareness = json.loads((tmp_path / "signal_awareness.json").read_text())
    plan = json.loads((tmp_path / "signal_plan.json").read_text())
    assert paths["signal_awareness"].endswith("signal_awareness.json")
    assert awareness["domain"] == "storage"
    assert plan["summary"]["activate"] == 1


def test_anchor_lead_window_forces_activation_without_zscore():
    topic_signals = [{
        "topic_id": "memory",
        "current_count": 1,
        "baseline_mean": 1.0,
        "baseline_std": 0.0,
        "z_score": None,
        "anomalous": False,
        "history_points": 3,
    }]
    anchor_signals = summarize_anchor_mentions(
        [
            {
                "source": "vendor-blog",
                "source_type_hint": "official",
                "title": "Join us at FMS 2026 booth 101",
                "snippet": "Flash Memory Summit returns to Santa Clara.",
                "entities": ["Kioxia"],
            }
        ],
        normalize_anchor_registry([
            {
                "name": "Flash Memory Summit 2026",
                "aliases": ["FMS 2026", "Flash Memory Summit"],
                "topics": ["memory"],
                "locations": ["Santa Clara"],
                "start_date": "2026-08-04",
                "lead_days": 45,
                "query_terms": ["fms 2026 flash memory"],
            }
        ]),
        run_date="2026-07-01",
    )

    plan = build_activation_plan(
        run_date="2026-07-01",
        topic_signals=topic_signals,
        anchor_signals=anchor_signals,
        default_daily_target=8,
    )

    assert plan["actions"][0]["action"] == "activate"
    assert plan["actions"][0]["reason"] == "lead_window_or_confirmed_burst"


def test_active_signal_archives_after_decay_streak():
    payload = detect_signal_awareness(
        domain="storage",
        run_date="2026-06-10",
        records=[],
        topic_rules=[{"id": "memory", "keywords": ["hbm"]}],
        historical_snapshots=[
            {"date": "2026-06-07", "topic_counts": {"memory": 4}, "anchor_counts": {"computex_2026": 0}},
            {"date": "2026-06-08", "topic_counts": {"memory": 3}, "anchor_counts": {"computex_2026": 0}},
            {"date": "2026-06-09", "topic_counts": {"memory": 2}, "anchor_counts": {"computex_2026": 0}},
        ],
        active_signals=[{"anchor_id": "computex_2026"}],
        anchor_registry=[
            {
                "name": "Computex 2026",
                "aliases": ["COMPUTEX"],
                "topics": ["memory"],
                "locations": ["Taipei"],
                "start_date": "2026-06-02",
                "end_date": "2026-06-05",
                "teardown_days": 5,
            }
        ],
    )

    assert payload["activation_plan"]["actions"][0]["action"] == "archive"


def test_unanchored_event_clusters_surface_repeated_unmatched_event_heat():
    payload = detect_signal_awareness(
        domain="storage",
        run_date="2026-05-20",
        records=[
            {"source": "feed-a", "title": "Taipei summit preview highlights SSD vendors", "snippet": "A storage summit preview"},
            {"source": "feed-b", "title": "Analysts expect Taipei summit coverage for controller makers", "snippet": "Summit coverage grows"},
            {"source": "feed-c", "title": "Another unrelated note", "snippet": "No event clue"},
        ],
        topic_rules=[],
        anchor_registry=[],
    )

    assert payload["unanchored_clusters"]
