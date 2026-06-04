"""Signal Bursts module tests."""

from __future__ import annotations

import json
import pytest

from stratum.signal_bursts import detect_signal_bursts, write_signal_bursts
from stratum.signal_bursts.contracts import validate_payload
from stratum.signal_bursts.grouping import group_signal_terms
from stratum.signal_bursts.terms import normalize_terms


def test_normalize_terms_accepts_alias_shapes():
    terms = normalize_terms([
        "HBM4",
        {"id": "nvidia", "aliases": ["NVIDIA", "NVDA"]},
        {"term": "qualification", "aliases": {"en": "qualification", "zh": "认证"}},
    ])

    assert [term["id"] for term in terms] == ["hbm4", "nvidia", "qualification"]
    assert "nvda" in terms[1]["aliases"]


def test_detect_signal_bursts_consumes_source_trace_and_db_context(tmp_path):
    payload = detect_signal_bursts(
        terms=[
            "HBM4",
            "NVIDIA",
            "qualification",
            {"id": "sk_hynix", "aliases": ["SK hynix"]},
        ],
        records_by_layer={
            "watchlist_observations": [
                {
                    "source": "sk-newsroom",
                    "source_type_hint": "official",
                    "url": "https://example.com/hbm4",
                    "title": "SK hynix HBM4 qualification for NVIDIA",
                    "published_at": "2026-05-31",
                }
            ],
            "watchlist_candidates": [
                {
                    "source": "sk-newsroom",
                    "source_type_hint": "official",
                    "url": "https://example.com/hbm4",
                    "title": "SK hynix HBM4 qualification for NVIDIA",
                    "status": "accept",
                    "accepted": True,
                    "published_at": "2026-05-31",
                }
            ],
            "watchlist_results": [
                {
                    "source": "sk-newsroom",
                    "source_type_hint": "official",
                    "url": "https://example.com/hbm4",
                    "title": "SK hynix HBM4 qualification for NVIDIA",
                    "published_at": "2026-05-31",
                }
            ],
            "raw": [
                {
                    "source": "sk-newsroom",
                    "source_type_hint": "official",
                    "url": "https://example.com/hbm4",
                    "title": "SK hynix HBM4 qualification for NVIDIA",
                    "published_at": "2026-05-31",
                }
            ],
        },
        source_trace_outputs={
            "source_quality": [{"source": "sk-newsroom", "quality_score": 0.9}],
            "dedupe_loss": {"totals": {"deduped_paths": 0}},
            "observation_health": {"watchlist": {"sources": [{"source": "sk-newsroom", "health_status": "ok"}]}},
        },
        db_context={
            "threads": [{"id": "thread-hbm", "title": "HBM4 ramp for NVIDIA platforms"}],
            "events": [{"id": "event-hbm", "title": "HBM4 qualification advances"}],
            "report_items": [{"id": "item-hbm", "title": "HBM4 qualification is becoming a core supply signal"}],
        },
        historical_baseline={"terms": {"hbm4": {"average_count": 0}}},
        run_date="2026-05-31",
    )

    assert payload["diagnostics"]["matched_terms"] >= 3
    assert payload["diagnostics"]["telemetry_mode"] == "context_aware"
    assert payload["diagnostics"]["db_context_available"] is True
    hbm4 = next(term for term in payload["terms"] if term["term"] == "hbm4")
    assert hbm4["telemetry_mode"] == "context_aware"
    assert hbm4["db_count"] >= 3
    assert hbm4["thread_count"] == 1
    assert hbm4["event_count"] == 1
    assert hbm4["report_item_count"] == 1
    assert payload["co_occurrence"]["totals"]["edges"] >= 1
    assert payload["bursts"][0]["classification"] == "emerging"
    assert payload["bursts"][0]["recommended_report_treatment"] in {
        "core_judgment_candidate",
        "watch_item",
        "verification_needed",
    }
    assert payload["report_handoff"][0]["linked_threads"][0]["id"] == "thread-hbm"

    path = write_signal_bursts(str(tmp_path), payload)
    written = json.loads((tmp_path / "signal_bursts.json").read_text())
    assert path.endswith("signal_bursts.json")
    assert written["diagnostics"]["burst_count"] == len(payload["bursts"])


def test_detect_signal_bursts_runs_without_db_context():
    payload = detect_signal_bursts(
        terms=["HBM4"],
        records_by_layer={
            "raw": [
                {
                    "source": "feed-a",
                    "url": "https://example.com/hbm4",
                    "title": "HBM4 supply update",
                }
            ]
        },
    )

    assert payload["diagnostics"]["telemetry_mode"] == "acquisition_only"
    assert payload["diagnostics"]["db_context_available"] is False
    assert payload["diagnostics"]["db_records"] == 0
    assert payload["terms"][0]["term"] == "hbm4"
    assert payload["terms"][0]["db_count"] == 0
    assert payload["terms"][0]["event_count"] == 0
    assert payload["terms"][0]["thread_count"] == 0
    assert payload["terms"][0]["report_item_count"] == 0
    assert payload["terms"][0]["judgment_count"] == 0


def test_signal_bursts_payload_contract_rejects_missing_top_level_fields():
    with pytest.raises(TypeError):
        validate_payload({
            "version": "0.1",
            "terms": [],
            "co_occurrence": {},
        })


def test_write_signal_bursts_rejects_invalid_payload(tmp_path):
    with pytest.raises(TypeError):
        write_signal_bursts(str(tmp_path), {"version": "0.1"})


def test_grouping_does_not_merge_bridge_terms_into_one_component():
    telemetry = {
        "terms": [
            {"term": "a", "label": "A", "total_count": 10, "weighted_count": 10, "sources": ["s1"]},
            {"term": "b", "label": "B", "total_count": 10, "weighted_count": 10, "sources": ["s1"]},
            {"term": "c", "label": "C", "total_count": 10, "weighted_count": 10, "sources": ["s2"]},
            {"term": "d", "label": "D", "total_count": 10, "weighted_count": 10, "sources": ["s2"]},
        ]
    }
    co_occurrence = {
        "edges": [
            {"terms": ["a", "b"], "count": 4, "representative_titles": ["A with B"]},
            {"terms": ["b", "c"], "count": 1, "representative_titles": ["B weakly bridges C"]},
            {"terms": ["c", "d"], "count": 4, "representative_titles": ["C with D"]},
        ]
    }

    candidates = group_signal_terms(
        telemetry,
        co_occurrence,
        min_pair_count=1,
        max_terms_per_burst=3,
    )
    grouped_terms = {tuple(candidate["terms"]) for candidate in candidates}

    assert ("a", "b", "c", "d") not in grouped_terms
    assert ("a", "b") in grouped_terms
    assert ("c", "d") in grouped_terms
    assert all(candidate["term_count"] <= 3 for candidate in candidates)
    pair = next(candidate for candidate in candidates if tuple(candidate["terms"]) == ("a", "b"))
    assert pair["grouping_strategy"] == "pair_seed_limited_expansion"
    assert pair["co_occurrence_count"] == 4
    assert pair["co_occurrence_density"] == 1.0
