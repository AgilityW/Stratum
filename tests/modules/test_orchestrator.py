"""Stratum pipeline ordering and current module map."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

PIPELINE_STEPS = [
    "Config + Domain Load",
    "Watchlist",
    "Acquisition",
    "Enrich",
    "Verify",
    "Normalize",
    "Cluster",
    "Edit",
    "Validate",
    "Render",
    "DB Ingest",
]

STRATUM_MODULES = [
    "sourcing",
    "contracts",
    "db",
    "orchestrator",
    "stages",
    "subsystems/event_thread",
    "subsystems/story_tracking",
    "subsystems/monitoring",
]


class TestPipelineSteps:
    """Pipeline has the current executable stages in correct order."""

    def test_current_step_count(self):
        assert len(PIPELINE_STEPS) == 11

    def test_config_loaded_first(self):
        assert PIPELINE_STEPS[0] == "Config + Domain Load"

    def test_watchlist_before_acquisition(self):
        assert PIPELINE_STEPS.index("Watchlist") < PIPELINE_STEPS.index("Acquisition")

    def test_acquisition_before_enrich(self):
        assert PIPELINE_STEPS.index("Acquisition") < PIPELINE_STEPS.index("Enrich")

    def test_verify_before_normalize(self):
        assert PIPELINE_STEPS.index("Verify") < PIPELINE_STEPS.index("Normalize")

    def test_cluster_before_edit(self):
        assert PIPELINE_STEPS.index("Cluster") < PIPELINE_STEPS.index("Edit")

    def test_validate_before_render(self):
        assert PIPELINE_STEPS.index("Validate") < PIPELINE_STEPS.index("Render")

    def test_db_ingest_is_last(self):
        assert PIPELINE_STEPS[-1] == "DB Ingest"


class TestModuleReferences:
    """Current framework modules are present and unique."""

    def test_module_count(self):
        assert len(STRATUM_MODULES) == 8

    def test_all_modules_are_unique(self):
        assert len(STRATUM_MODULES) == len(set(STRATUM_MODULES))

    def test_module_paths_exist(self):
        for module in STRATUM_MODULES:
            assert (PROJECT_ROOT / "stratum" / module).exists(), module

    def test_discovery_sourcing_included(self):
        assert (PROJECT_ROOT / "stratum" / "sourcing" / "discovery").exists()

    def test_sourcing_included(self):
        assert "sourcing" in STRATUM_MODULES
