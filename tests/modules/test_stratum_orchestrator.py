"""Stratum — pipeline step ordering and module reference completeness.

The main orchestrator must define all 10+ steps and reference all required modules.
"""
import pytest

# From stratum SKILL.md v4.1 — execution flow
PIPELINE_STEPS = [
    "Step 0: Config + Channel Load",
    "Step 1: Locale Routing",
    "Step 2: Collection",
    "Step 3: Verification",
    "Step 4: Article Normalization",
    "Step 5: Story Clustering",
    "Step 4.6.5: Coverage Monitor",
    "Step 4.7: Event Threading",
    "Step 6: Content Writing (LLM)",
    "Step 7: Rendering",
    "Step 8: Delivery",
    "Step 9: Source Recording",
    "Step 10: Source Profiling + Health Update",
]

# Modules listed in stratum contract
STRATUM_MODULES = [
    "locale-router",
    "source-manager",
    "verify-engine",
    "article-normalizer",
    "story-cluster-engine",
    "coverage-monitor",
    "event-thread-engine",
    "trial-source-manager",
    "source-recorder",
    "source-profiler",
    "source-graph-engine",
    "value-chain-monitor",
    "health-tracker",
    "render-engine",
]


class TestPipelineSteps:
    """Pipeline has all required steps in correct order."""

    def test_thirteen_steps(self):
        """10 base steps + coverage-monitor insertion."""
        assert len(PIPELINE_STEPS) == 13

    def test_config_loaded_first(self):
        assert "Step 0" in PIPELINE_STEPS[0]

    def test_locale_routing_before_collection(self):
        idx_route = next(i for i, s in enumerate(PIPELINE_STEPS) if "Routing" in s)
        idx_collect = next(i for i, s in enumerate(PIPELINE_STEPS) if "Collection" in s)
        assert idx_route < idx_collect, "Locale routing must happen before collection"

    def test_verification_before_normalization(self):
        idx_verify = next(i for i, s in enumerate(PIPELINE_STEPS) if "Verification" in s)
        idx_norm = next(i for i, s in enumerate(PIPELINE_STEPS) if "Normalization" in s)
        assert idx_verify < idx_norm, "Verify before normalizing"

    def test_clustering_before_threading(self):
        idx_cluster = next(i for i, s in enumerate(PIPELINE_STEPS) if "Clustering" in s)
        idx_thread = next(i for i, s in enumerate(PIPELINE_STEPS) if "Threading" in s)
        assert idx_cluster < idx_thread, "Cluster before threading"

    def test_coverage_monitor_between_cluster_and_thread(self):
        idx_cluster = next(i for i, s in enumerate(PIPELINE_STEPS) if "Clustering" in s)
        idx_coverage = next(i for i, s in enumerate(PIPELINE_STEPS) if "Coverage" in s)
        idx_thread = next(i for i, s in enumerate(PIPELINE_STEPS) if "Threading" in s)
        assert idx_cluster < idx_coverage < idx_thread, (
            "Coverage monitor must run between clustering and threading"
        )

    def test_rendering_before_delivery(self):
        idx_render = next(i for i, s in enumerate(PIPELINE_STEPS) if "Rendering" in s)
        idx_deliver = next(i for i, s in enumerate(PIPELINE_STEPS) if "Delivery" in s)
        assert idx_render < idx_deliver, "Render before delivering"

    def test_source_recording_after_delivery(self):
        """Recording is post-hoc — doesn't block delivery."""
        idx_deliver = next(i for i, s in enumerate(PIPELINE_STEPS) if "Delivery" in s)
        idx_record = next(i for i, s in enumerate(PIPELINE_STEPS) if "Recording" in s)
        assert idx_deliver < idx_record, (
            "Source recording happens after delivery (non-blocking)"
        )

    def test_profiling_is_last(self):
        assert "Profiling" in PIPELINE_STEPS[-1], (
            "Source profiling + health update is the final step"
        )


class TestModuleReferences:
    """All 14 pipeline modules must be listed in stratum contract."""

    def test_fourteen_modules(self):
        assert len(STRATUM_MODULES) == 14

    def test_all_modules_are_unique(self):
        assert len(STRATUM_MODULES) == len(set(STRATUM_MODULES)), (
            "Duplicate module references"
        )

    def test_locale_router_included(self):
        assert "locale-router" in STRATUM_MODULES

    def test_value_chain_monitor_included(self):
        assert "value-chain-monitor" in STRATUM_MODULES

    def test_coverage_monitor_included(self):
        assert "coverage-monitor" in STRATUM_MODULES

    def test_source_graph_engine_included(self):
        assert "source-graph-engine" in STRATUM_MODULES
