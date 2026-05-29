"""Tests for value-chain subsystem."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest
import json
from pathlib import Path
from datetime import date

from value_chain import (
    init_runtime_config, merge_layers, should_probe_layer,
    archive_stale_templates, process_probation, build_state,
    MAX_SEED_SOURCES_PER_LAYER, MAX_TEMPLATES_PER_LAYER,
    PROMOTE_THRESHOLD, DEMOTE_THRESHOLD,
)

SAMPLE_LAYERS = [
    {
        "id": "upstream_equipment",
        "label": "Upstream Equipment",
        "criticality": "high",
        "frequency": "weekly",
        "seed_sources": [
            {"name": "ASML"},
            {"name": "Applied Materials"},
        ],
        "probe_templates": ["{company} equipment order {quarter}"],
    },
    {
        "id": "downstream",
        "label": "Downstream",
        "criticality": "medium",
        "frequency": "monthly",
        "seed_sources": [{"name": "Apple"}],
        "probe_templates": ["{company} storage demand"],
    },
]


class TestInit:
    def test_init_creates_layers(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc123")
        assert rc["base_version"] == "abc123"
        assert "upstream_equipment" in rc["layers"]
        assert rc["layers"]["upstream_equipment"]["promoted_sources"] == []


class TestMerge:
    def test_base_sources_preserved(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        active = merge_layers(SAMPLE_LAYERS, rc)
        assert len(active[0]["_active_seed_sources"]) == 2  # ASML + Applied Materials

    def test_promoted_sources_merged(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        rc["layers"]["upstream_equipment"]["promoted_sources"] = [
            {"name": "Lam Research", "probation_status": "confirmed", "aliases": {}},
        ]
        active = merge_layers(SAMPLE_LAYERS, rc)
        assert len(active[0]["_active_seed_sources"]) == 3

    def test_demoted_sources_excluded(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        rc["layers"]["upstream_equipment"]["promoted_sources"] = [
            {"name": "Lam Research", "probation_status": "demoted", "aliases": {}},
        ]
        active = merge_layers(SAMPLE_LAYERS, rc)
        assert len(active[0]["_active_seed_sources"]) == 2  # only base

    def test_cap_overflow(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        # Add 15 promoted sources (base=2, cap=15, so 13 slots available)
        promoted = []
        for i in range(15):
            promoted.append({"name": f"Source{i}", "probation_status": "confirmed", "aliases": {}})
        rc["layers"]["upstream_equipment"]["promoted_sources"] = promoted
        active = merge_layers(SAMPLE_LAYERS, rc)
        assert len(active[0]["_active_seed_sources"]) == MAX_SEED_SOURCES_PER_LAYER
        assert len(active[0]["_overflow_promoted"]) == 2


class TestProbeSchedule:
    def test_should_probe_never_probed(self):
        assert should_probe_layer(SAMPLE_LAYERS[0], date(2026, 5, 28), []) is True

    def test_should_not_probe_too_soon(self):
        log = [{"layer_id": "upstream_equipment", "type": "probe", "date": "2026-05-27"}]
        assert should_probe_layer(SAMPLE_LAYERS[0], date(2026, 5, 28), log) is False

    def test_should_probe_after_week(self):
        log = [{"layer_id": "upstream_equipment", "type": "probe", "date": "2026-05-20"}]
        assert should_probe_layer(SAMPLE_LAYERS[0], date(2026, 5, 28), log) is True

    def test_daily_never_probes(self):
        layer = dict(SAMPLE_LAYERS[0], frequency="daily")
        assert should_probe_layer(layer, date(2026, 5, 28), []) is False


class TestArchiveTemplates:
    def test_archives_stale_high_tier(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        rc["layers"]["upstream_equipment"]["template_productivity"] = {
            "old template": {"last_output": "2026-01-01", "status": "active"}
        }
        rc = archive_stale_templates(SAMPLE_LAYERS, rc, date(2026, 5, 28))
        archived = rc["layers"]["upstream_equipment"].get("archived_templates", [])
        assert "old template" in archived

    def test_critical_never_archives(self):
        layer = dict(SAMPLE_LAYERS[0], criticality="critical")
        rc = init_runtime_config([layer], "2026-05-28", "abc")
        rc["layers"]["upstream_equipment"]["template_productivity"] = {
            "old template": {"last_output": "2026-01-01", "status": "active"}
        }
        rc = archive_stale_templates([layer], rc, date(2026, 5, 28))
        archived = rc["layers"]["upstream_equipment"].get("archived_templates", [])
        assert "old template" not in archived


class TestProbation:
    def test_promote_above_threshold(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-06-28", "abc")
        rc["layers"]["upstream_equipment"]["promoted_sources"] = [{
            "name": "GoodSource", "probation_status": "active",
            "promote_score": 0.85,
            "probation_start": "2026-05-28",
            "probation_end": "2026-06-28",
            "midterm_eval": None,
        }]
        rc = process_probation(rc, SAMPLE_LAYERS, date(2026, 6, 28))
        src = rc["layers"]["upstream_equipment"]["promoted_sources"][0]
        assert src["probation_status"] == "confirmed"

    def test_demote_below_threshold(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-06-28", "abc")
        rc["layers"]["upstream_equipment"]["promoted_sources"] = [{
            "name": "BadSource", "probation_status": "active",
            "promote_score": 0.25,
            "probation_start": "2026-05-28",
            "probation_end": "2026-06-28",
            "midterm_eval": None,
        }]
        rc = process_probation(rc, SAMPLE_LAYERS, date(2026, 6, 28))
        src = rc["layers"]["upstream_equipment"]["promoted_sources"][0]
        assert src["probation_status"] == "demoted"

    def test_extend_between_thresholds(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-06-28", "abc")
        rc["layers"]["upstream_equipment"]["promoted_sources"] = [{
            "name": "MidSource", "probation_status": "active",
            "promote_score": 0.55,
            "probation_start": "2026-05-28",
            "probation_end": "2026-06-28",
            "midterm_eval": None,
        }]
        rc = process_probation(rc, SAMPLE_LAYERS, date(2026, 6, 28))
        src = rc["layers"]["upstream_equipment"]["promoted_sources"][0]
        assert src["probation_status"] == "active"  # still active, probation extended


class TestBuildState:
    def test_builds_state_summary(self):
        rc = init_runtime_config(SAMPLE_LAYERS, "2026-05-28", "abc")
        state = build_state(SAMPLE_LAYERS, rc, [], "2026-05-28")
        assert "upstream_equipment" in state["layers"]
        assert state["layers"]["upstream_equipment"]["base_sources"] == 2
        assert state["layers"]["upstream_equipment"]["total_sources"] == 2
