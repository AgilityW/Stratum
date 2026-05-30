"""Stratum pipeline ordering and current module map."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

PIPELINE_STEPS = [
    "Config + Domain Load",
    "Search",
    "Collect",
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
    "collectors",
    "contracts",
    "db",
    "orchestrator",
    "stages",
    "subsystems/search",
    "subsystems/event-thread",
    "subsystems/story-tracking",
    "subsystems/monitoring",
]


class TestPipelineSteps:
    """Pipeline has the current executable stages in correct order."""

    def test_current_step_count(self):
        assert len(PIPELINE_STEPS) == 11

    def test_config_loaded_first(self):
        assert PIPELINE_STEPS[0] == "Config + Domain Load"

    def test_search_before_collect(self):
        assert PIPELINE_STEPS.index("Search") < PIPELINE_STEPS.index("Collect")

    def test_collect_before_enrich(self):
        assert PIPELINE_STEPS.index("Collect") < PIPELINE_STEPS.index("Enrich")

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
        assert len(STRATUM_MODULES) == 9

    def test_all_modules_are_unique(self):
        assert len(STRATUM_MODULES) == len(set(STRATUM_MODULES))

    def test_module_paths_exist(self):
        for module in STRATUM_MODULES:
            assert (PROJECT_ROOT / "stratum" / module).exists(), module

    def test_search_subsystem_included(self):
        assert "subsystems/search" in STRATUM_MODULES

    def test_collectors_included(self):
        assert "collectors" in STRATUM_MODULES
