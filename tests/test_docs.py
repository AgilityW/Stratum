"""Documentation coverage for current Stratum modules."""

from pathlib import Path
import re

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SCOPE_FILES = [
    "stratum/SCOPE.md",
    "stratum/capabilities/SCOPE.md",
    "stratum/mcp_adapter/SCOPE.md",
    "stratum/sourcing/SCOPE.md",
    "stratum/sourcing/watchlist/SCOPE.md",
    "stratum/contracts/SCOPE.md",
    "stratum/db/SCOPE.md",
    "stratum/db/synthesis/SCOPE.md",
    "stratum/evaluation/SCOPE.md",
    "stratum/orchestrator/SCOPE.md",
    "stratum/source_trace/SCOPE.md",
    "stratum/signal_bursts/SCOPE.md",
    "stratum/temporal/SCOPE.md",
    "stratum/stages/SCOPE.md",
    "stratum/stages/acquisition/SCOPE.md",
    "stratum/stages/cluster/SCOPE.md",
    "stratum/stages/edit/SCOPE.md",
    "stratum/stages/enrich/SCOPE.md",
    "stratum/stages/normalize/SCOPE.md",
    "stratum/stages/repair/SCOPE.md",
    "stratum/stages/render/SCOPE.md",
    "stratum/stages/search/SCOPE.md",
    "stratum/stages/validate/SCOPE.md",
    "stratum/stages/verify/SCOPE.md",
    "stratum/subsystems/SCOPE.md",
    "stratum/subsystems/event_thread/SCOPE.md",
    "stratum/subsystems/signal_awareness/SCOPE.md",
    "stratum/subsystems/monitoring/SCOPE.md",
    "stratum/sourcing/discovery/SCOPE.md",
    "stratum/subsystems/story_tracking/SCOPE.md",
    "domains/storage/SCOPE.md",
]

ROOT_MARKDOWN_FILES = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
}

TOP_LEVEL_DOC_FILES = [
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "docs/CONTRACT_INVENTORY.yaml",
    "docs/DEPLOYMENT.md",
    "docs/ENGINEERING_RULES.md",
]

ACTIVE_DOC_FILES = [
    "ALGORITHM_ARCHITECTURE.md",
    "CAPABILITY_EVOLUTION.md",
    "CONTRACT_INVENTORY.yaml",
    "DEPLOYMENT.md",
    "ENGINEERING_RULES.md",
    "MCP_ADAPTER.md",
    "STORAGE_BASELINE.md",
    "STORAGE_ARCHITECTURE.md",
    "TODO.md",
]

STAGE_NAMES = [
    "acquisition",
    "enrich",
    "verify",
    "normalize",
    "cluster",
    "edit",
    "validate",
    "repair",
    "render",
]

CONTRACT_SCHEMA_FILES = [
    "agent_task.json",
    "task_result.json",
    "article_record.json",
    "capability_invocation.json",
    "capability_result.json",
    "watchlist_stats.json",
    "search_result.json",
    "search_stats.json",
    "story_cluster.json",
    "validate_report.json",
    "repair_report.json",
    "verified_article.json",
    "signal_awareness.json",
    "signal_plan.json",
]

PYTHON_CONTRACT_FILES = [
    "event_thread.py",
    "pipeline_artifacts.py",
    "report_window.py",
]

STALE_DOC_REFERENCES = [
    "story_bridge.py",
    "source-management",
    "source-intelligence",
    "source-graph",
    "value-chain-monitor",
    "stratum/subsystems/value-chain",
    "weekly.yaml",
    "seed_queries",
    "gap_searches",
]

VERSIONED_MODULES = {
    "sourcing",
    "contracts",
    "orchestrator",
    "temporal",
    "db",
    "evaluation",
    "watchlist",
    "discovery",
    "edit",
    "render",
    "deployment",
}

INVENTORY_REQUIRED_MODULES = {
    "sourcing.watchlist",
    "sourcing.discovery",
    "sourcing.policy",
    "contracts",
    "db",
    "orchestrator",
    "source_trace",
    "signal_bursts",
    "temporal",
    "stages",
    "subsystems.signal_awareness",
    "subsystems.monitoring",
    "subsystems.story_tracking",
}

INVENTORY_REQUIRED_CONTRACT_IDS = {
    "domain-config",
    "domain-queries",
    "watchlist-results",
    "watchlist-observations",
    "watchlist-candidates",
    "watchlist-stats",
    "search-execution",
    "raw-results",
    "discovery-candidates",
    "discovery-observations",
    "raw-stats",
    "enriched-results",
    "verified-articles",
    "verification-stats",
    "normalized-articles",
    "story-clusters",
    "story-context",
    "edit-plan",
    "edit-chunks",
    "edit-trace",
    "briefing-markdown",
    "validate-report",
    "repair-report",
    "event-threads",
    "event-thread-lifecycle-diagnostics",
    "rendered-html-pdf",
    "run-manifest",
    "db-event-store-write",
    "db-foundation-write",
    "exploring",
    "db-semantic-read",
    "evaluation-cases",
    "evaluation-summary",
    "db-synthesis-output",
    "temporal-profile",
    "report-window",
    "thread-keywords",
    "monitoring-health",
    "source-trace-output-bundle",
    "signal-bursts-output",
    "signal-awareness-output",
    "signal-activation-plan",
}

HAN_RE = re.compile(r"[\u4e00-\u9fff]")

HAN_ALLOWED_PATH_PREFIXES = (
    "docs/archive/",
    "domains/",
    "tests/",
    "stratum/stages/edit/",
    "stratum/stages/acquisition/",
    "stratum/stages/render/",
    "stratum/stages/validate/",
    "stratum/stages/enrich/",
    "stratum/stages/normalize/",
    "stratum/temporal/",
)

HAN_ALLOWED_FILES = {
    "config.yaml",
    "config.example.yaml",
    "stratum/sourcing/watchlist/direct_fetch.py",
    "stratum/sourcing/watchlist/keywords.py",
    "stratum/db/cascade_fixture.py",
    "stratum/db/synthesis/engine.py",
    "stratum/db/synthesis/events.py",
    "stratum/db/synthesis/evidence.py",
    "stratum/db/synthesis/payload.py",
    "stratum/db/synthesis/policy.py",
    "stratum/db/synthesis/text.py",
    "stratum/orchestrator/db_foundation.py",
    "stratum/orchestrator/pipeline.py",
    "stratum/signal_bursts/terms.py",
    "stratum/signal_bursts/test_bursts.py",
    "stratum/stages/acquisition/acquisition.py",
    "stratum/subsystems/monitoring/coverage.py",
    "stratum/sourcing/discovery/models.py",
}

HAN_SCANNED_SUFFIXES = {
    ".md",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".sql",
}

HAN_IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data",
    "deployments",
    "health-data",
}


def test_required_scope_files_exist():
    for rel_path in REQUIRED_SCOPE_FILES:
        path = PROJECT_ROOT / rel_path
        assert path.exists(), rel_path
        assert path.read_text().strip(), f"{rel_path} is empty"


def test_production_module_names_do_not_use_test_suffixes():
    for path in (PROJECT_ROOT / "stratum").rglob("*.py"):
        rel = path.relative_to(PROJECT_ROOT)
        parts = rel.parts
        if "tests" in parts:
            continue
        assert not path.name.endswith("_test.py"), f"{rel} uses a test-suffix module name"


def test_repository_does_not_keep_macos_metadata_files():
    for path in PROJECT_ROOT.rglob(".DS_Store"):
        assert False, f"unexpected macOS metadata file in repo: {path.relative_to(PROJECT_ROOT)}"


def test_active_docs_and_examples_do_not_embed_personal_paths():
    tracked = [
        PROJECT_ROOT / ".env.example",
        PROJECT_ROOT / "config.example.yaml",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "DEPLOYMENT.md",
        PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md",
        PROJECT_ROOT / "scripts" / "deploy.sh",
        PROJECT_ROOT / "stratum" / "db" / "SCOPE.md",
    ]
    forbidden = (
        "/Users/",
        "ObsidianSpace",
        "WorkSpace/Stratum",
        "ProjectSpace/Stratum",
    )
    for path in tracked:
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{path.relative_to(PROJECT_ROOT)} embeds local path token {token!r}"


def test_project_file_names_use_at_most_one_underscore():
    skip_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    roots = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "docs",
        PROJECT_ROOT / "domains",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "stratum",
        PROJECT_ROOT / "tests",
    ]
    for root in roots:
        items = [root] if root.is_file() else root.rglob("*")
        for path in items:
            if not path.exists() or path.is_dir():
                continue
            rel = path.relative_to(PROJECT_ROOT)
            if any(part in skip_dirs for part in rel.parts):
                continue
            if path.name == "__init__.py":
                continue
            stem = path.name.rsplit(".", 1)[0]
            assert stem.count("_") <= 1, f"{rel} exceeds underscore naming limit"


def test_db_and_subsystems_packages_export_stable_surfaces():
    import stratum.capabilities as capabilities
    import stratum.db as db
    import stratum.mcp_adapter as mcp_adapter
    import stratum.sourcing as sourcing
    import stratum.stages as stages
    import stratum.subsystems as subsystems
    import stratum.subsystems.event_thread as event_thread
    import stratum.subsystems.signal_awareness as signal_awareness
    import stratum.subsystems.story_tracking as story_tracking

    assert "source_trace" in capabilities.__all__
    assert "signal_bursts" in capabilities.__all__
    assert "signal_awareness" in capabilities.__all__
    assert "discovery_diagnostics" in capabilities.__all__
    assert "evaluate_reports" in capabilities.__all__
    assert "source_expansion" in capabilities.__all__
    assert "watch_queries" in capabilities.__all__
    assert "attach_signal" in capabilities.__all__
    assert "thread_timeline" in capabilities.__all__
    assert "thread_keywords" in capabilities.__all__
    assert "entity_timeline" in capabilities.__all__
    assert "technology_progress" in capabilities.__all__
    assert "trend_summary" in capabilities.__all__
    assert "key_events" in capabilities.__all__
    assert "key_timeline" in capabilities.__all__
    assert "judgment_status" in capabilities.__all__
    assert "due_judgments" in capabilities.__all__
    assert "active_queries" in capabilities.__all__
    assert "search_health_db" in capabilities.__all__
    assert "search_health" in capabilities.__all__
    assert "report_evidence" in capabilities.__all__
    assert "report_lineage" in capabilities.__all__
    assert "cascade_inputs" in capabilities.__all__
    assert "briefing_context" in capabilities.__all__
    assert "format_briefing" in capabilities.__all__
    assert "thread_lifecycle" in capabilities.__all__
    assert "synthesis_policy" in capabilities.__all__
    assert "report_context" in capabilities.__all__
    assert "story_context" in capabilities.__all__
    assert "awareness_config" in capabilities.__all__
    assert "list_capabilities" in capabilities.__all__
    assert "describe" in capabilities.__all__
    assert "list_calls" in capabilities.__all__
    assert "call" in capabilities.__all__
    assert "list_tasks" in capabilities.__all__
    assert "get_task" in capabilities.__all__
    assert "run_task" in capabilities.__all__

    assert "list_tools" in mcp_adapter.__all__
    assert "get_tool" in mcp_adapter.__all__
    assert "call_tool" in mcp_adapter.__all__
    assert all(not name.endswith("_capability") for name in capabilities.__all__)


def test_production_layers_do_not_depend_on_capability_or_mcp_adapter_layers():
    import stratum.db as db
    import stratum.sourcing as sourcing
    import stratum.stages as stages
    import stratum.subsystems as subsystems
    import stratum.subsystems.event_thread as event_thread
    import stratum.subsystems.signal_awareness as signal_awareness
    import stratum.subsystems.story_tracking as story_tracking

    forbidden_imports = (
        "stratum.capabilities",
        "stratum.mcp_adapter",
    )
    for base in (
        PROJECT_ROOT / "stratum" / "orchestrator",
        PROJECT_ROOT / "stratum" / "stages",
        PROJECT_ROOT / "stratum" / "temporal",
    ):
        for path in base.rglob("*.py"):
            text = path.read_text()
            for forbidden in forbidden_imports:
                assert forbidden not in text, f"{path.relative_to(PROJECT_ROOT)} depends on additive layer {forbidden}"

    assert "connection" in db.__all__
    assert "ingest" in db.__all__
    assert "service" in db.__all__
    assert "synthesis" in db.__all__

    assert "discovery" in sourcing.__all__
    assert "watchlist" in sourcing.__all__

    assert "acquisition" in stages.__all__
    assert "boilerplate" in stages.__all__
    assert "cluster" in stages.__all__
    assert "edit" in stages.__all__
    assert "enrich" in stages.__all__
    assert "normalize" in stages.__all__
    assert "render" in stages.__all__
    assert "search" in stages.__all__
    assert "validate" in stages.__all__
    assert "verify" in stages.__all__

    assert "event_thread" in subsystems.__all__
    assert "signal_awareness" in subsystems.__all__
    assert "monitoring" in subsystems.__all__
    assert "story_tracking" in subsystems.__all__

    assert "detect_signal_awareness" in signal_awareness.__all__
    assert "write_signal_awareness" in signal_awareness.__all__
    assert "build_activation_plan" in signal_awareness.__all__
    assert "normalize_anchor_registry" in signal_awareness.__all__

    assert "EventThread" in event_thread.__all__
    assert "generate_watch_queries" in event_thread.__all__
    assert "evolve_threads" in event_thread.__all__
    assert "register_appearance" in event_thread.__all__
    assert "ThreadLifecycleScorer" in event_thread.__all__

    assert "generate_context" in story_tracking.__all__
    assert "format_context_for_prompt" in story_tracking.__all__
    assert "ContextSelectionPolicy" in story_tracking.__all__
    assert "EventRecord" in story_tracking.__all__
    assert "BriefingContext" in story_tracking.__all__


def test_db_synthesis_uses_event_thread_package_surface():
    text = (PROJECT_ROOT / "stratum" / "db" / "synthesis" / "ranker.py").read_text()
    assert "from stratum.subsystems.event_thread import ThreadLifecycleScorer" in text
    assert "from stratum.subsystems.event_thread.lifecycle_policy import ThreadLifecycleScorer" not in text


def test_validate_uses_shared_stage_boilerplate_helper():
    text = (PROJECT_ROOT / "stratum" / "stages" / "validate" / "validate.py").read_text()
    assert "from stratum.stages.boilerplate import artifact_boilerplate_violations, build_boilerplate_rules" in text
    assert "from stratum.stages.edit.boilerplate import artifact_boilerplate_violations, build_boilerplate_rules" not in text


def test_source_trace_and_signal_bursts_packages_export_stable_surfaces():
    import stratum.signal_bursts as signal_bursts
    import stratum.source_trace as source_trace
    import stratum.sourcing.discovery as discovery
    import stratum.temporal as temporal

    assert "run_source_trace" in source_trace.__all__
    assert "build_outputs" in source_trace.__all__
    assert "load_inputs" in source_trace.__all__
    assert "build_funnel" in source_trace.__all__
    assert "score_sources" in source_trace.__all__
    assert "build_temporal_profile" in source_trace.__all__

    assert "detect_signal_bursts" in signal_bursts.__all__
    assert "normalize_terms" in signal_bursts.__all__
    assert "write_signal_bursts" in signal_bursts.__all__

    assert "Query" in discovery.__all__
    assert "QueryStats" in discovery.__all__
    assert "ResultSet" in discovery.__all__
    assert "SearchResult" in discovery.__all__
    assert "canonicalize_url" in discovery.__all__
    assert "normalize_include_domains" in discovery.__all__
    assert "source_pattern_matches" in discovery.__all__
    assert "QueryPlanner" in discovery.__all__
    assert "QueryPerformanceScorer" in discovery.__all__
    assert "SearchSupplementPolicy" in discovery.__all__
    assert "SearchResultScorer" in discovery.__all__
    assert "SearchDiversityRanker" in discovery.__all__
    assert "split_queries_by_coverage" in discovery.__all__

    assert "DAILY_STAGE_ORDER" in temporal.__all__
    assert "TemporalServices" in temporal.__all__
    assert "run_higher_scale_output" in temporal.__all__
    assert "get_timescale_profile" in temporal.__all__
    assert "run_exploring" in temporal.__all__
    assert "Integration" in temporal.__all__


def test_acquisition_uses_discovery_package_surface_for_query_planning():
    text = (PROJECT_ROOT / "stratum" / "stages" / "acquisition" / "acquisition.py").read_text()
    assert "from stratum.sourcing.discovery import (" in text
    assert "SearchSupplementPolicy" in text
    assert "split_queries_by_coverage" in text
    assert "from stratum.sourcing.discovery.query_planner import (" not in text


def test_orchestrator_uses_temporal_package_surface():
    pipeline_text = (PROJECT_ROOT / "stratum" / "orchestrator" / "pipeline.py").read_text()
    run_context_text = (PROJECT_ROOT / "stratum" / "orchestrator" / "run_context.py").read_text()

    assert "from stratum.temporal import TemporalServices, run_higher_scale_output" in pipeline_text
    assert "from stratum.temporal.timescale import TemporalServices, run_higher_scale_output" not in pipeline_text
    assert "from stratum.temporal import DAILY_STAGE_ORDER" in run_context_text
    assert "from stratum.temporal.profiles import DAILY_STAGE_ORDER" not in run_context_text


def test_codex_documentation_entrypoints_exist():
    assert (PROJECT_ROOT / "AGENTS.md").exists()
    assert (PROJECT_ROOT / "docs" / "README.md").exists()
    assert (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").exists()
    agents = (PROJECT_ROOT / "AGENTS.md").read_text()
    assert "Read Order" in agents
    assert "docs/CONTRACT_INVENTORY.yaml" in agents


def test_engineering_rules_require_necessary_documentation():
    text = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    normalized = " ".join(text.split())
    assert "Documentation must be necessary, not merely additive" in text
    assert "Do not update docs just because a discussion happened" in normalized
    assert "low-value notes" in text


def test_project_level_laws_are_concise_and_indexed_from_readme():
    rules = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    normalized_rules = " ".join(rules.split())
    readme = (PROJECT_ROOT / "README.md").read_text()
    laws = [
        "Preserve the working intelligence pipeline",
        "Keep ownership singular",
        "Make handoffs explicit",
        "Delegate by responsibility",
        "Keep evidence auditable",
        "Let documentation earn its place",
    ]

    assert "## Project Laws" in rules
    assert "This document holds project-level rules only" in normalized_rules
    assert "[Engineering Rules](docs/ENGINEERING_RULES.md)" in readme
    for law in laws:
        assert law in rules
        assert law in readme


def test_public_github_files_are_english_first_except_product_assets():
    docs_rule = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    agents_rule = (PROJECT_ROOT / "AGENTS.md").read_text()
    assert "Engineering docs, code comments, config examples" in docs_rule
    assert "product output" in docs_rule
    assert "requirements may arrive in Chinese" in agents_rule
    assert "Translate" in agents_rule

    offenders = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in HAN_SCANNED_SUFFIXES:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if any(part in HAN_IGNORED_DIRS for part in path.parts):
            continue
        if rel in HAN_ALLOWED_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in HAN_ALLOWED_PATH_PREFIXES):
            continue

        text = path.read_text()
        if HAN_RE.search(text):
            offenders.append(rel)

    assert not offenders, "Unexpected non-English engineering text in: " + ", ".join(offenders)


def test_root_markdown_stays_minimal_for_codex():
    root_markdown = {
        path.name
        for path in PROJECT_ROOT.glob("*.md")
    }
    assert root_markdown == ROOT_MARKDOWN_FILES


def test_docs_readme_indexes_active_docs():
    text = (PROJECT_ROOT / "docs" / "README.md").read_text()
    for filename in ACTIVE_DOC_FILES:
        assert f"`{filename}`" in text, f"docs/README.md does not index {filename}"
    assert "`archive/PROJECT_REVIEW.md`" in text


def test_todo_contains_only_unfinished_items():
    text = (PROJECT_ROOT / "docs" / "TODO.md").read_text()
    lower_text = text.lower()
    forbidden = [
        "status:",
        "done",
        "implemented",
        "completed",
        "current baseline",
    ]
    for phrase in forbidden:
        assert phrase not in lower_text, f"docs/TODO.md should not track completed work via {phrase!r}"

    rules = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    normalized_rules = " ".join(rules.split())
    assert "`docs/TODO.md` must only contain unfinished items" in normalized_rules
    assert "concrete next action and an acceptance signal" in normalized_rules
    numbered_items = re.findall(r"(?m)^\d+\.\s+", text)
    if numbered_items:
        assert text.count("Next:") == len(numbered_items)
        assert text.count("Acceptance:") == len(numbered_items)


def test_historical_review_log_lives_in_docs_archive():
    assert not (PROJECT_ROOT / "PROJECT_REVIEW.md").exists()
    archived = PROJECT_ROOT / "docs" / "archive" / "PROJECT_REVIEW.md"
    assert archived.exists()
    assert archived.read_text().startswith("# Stratum module review")


def test_scope_files_do_not_reference_removed_modules():
    for rel_path in REQUIRED_SCOPE_FILES:
        text = (PROJECT_ROOT / rel_path).read_text()
        for stale in STALE_DOC_REFERENCES:
            assert stale not in text, f"{rel_path} references removed module {stale}"


def test_top_level_docs_do_not_reference_removed_modules():
    for rel_path in TOP_LEVEL_DOC_FILES:
        text = (PROJECT_ROOT / rel_path).read_text()
        for stale in STALE_DOC_REFERENCES:
            assert stale not in text, f"{rel_path} references removed module {stale}"


def test_importable_python_paths_use_snake_case():
    rules = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    normalized = " ".join(rules.split())
    assert "Importable Python source paths must use lowercase `snake_case`" in rules
    assert "Do not use hyphens" in normalized

    for path in (PROJECT_ROOT / "stratum").rglob("*"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if "__pycache__" in rel:
            continue
        if path.is_dir():
            assert "-" not in path.name, f"{rel} is an importable package path; use snake_case"
        elif path.suffix == ".py":
            assert "-" not in path.stem, f"{rel} is an importable module path; use snake_case"


def test_stage_scope_documents_all_pipeline_stages():
    text = (PROJECT_ROOT / "stratum/stages/SCOPE.md").read_text()
    for stage in STAGE_NAMES:
        assert f"`{stage}`" in text, f"stage docs omit {stage}"
    assert "watchlist sidecar" in text


def test_framework_scope_documents_current_analysis_layers():
    text = (PROJECT_ROOT / "stratum/SCOPE.md").read_text()
    for module in ("`source_trace/`", "`signal_bursts/`"):
        assert module in text, f"stratum/SCOPE.md omits {module}"


def test_temporal_scope_keeps_exploring_as_orchestration_boundary():
    text = (PROJECT_ROOT / "stratum/temporal/SCOPE.md").read_text()
    normalized = " ".join(text.split())
    assert "Exploring owns why and when same-scale fresh evidence is needed" in text
    assert "delegate evidence acquisition to the shared sourcing/acquisition path" in text
    assert "instead of owning RSS parsing" in normalized


def test_contract_scope_lists_current_json_schemas_once():
    text = (PROJECT_ROOT / "stratum/contracts/SCOPE.md").read_text()
    listed = re.findall(r"\|\s*`([^`]+\.json)`\s*\|", text)
    assert sorted(listed) == sorted(CONTRACT_SCHEMA_FILES)
    for schema in CONTRACT_SCHEMA_FILES:
        assert listed.count(schema) == 1, f"duplicate or missing contract doc entry for {schema}"


def test_contract_scope_lists_current_python_contracts_once():
    text = (PROJECT_ROOT / "stratum/contracts/SCOPE.md").read_text()
    listed = re.findall(r"\|\s*`([^`]+\.py)`\s*\|", text)
    for contract in PYTHON_CONTRACT_FILES:
        assert listed.count(contract) == 1, f"duplicate or missing contract doc entry for {contract}"


def test_domain_prompt_overrides_are_not_documented_as_active_assets():
    docs = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "domains/storage/SCOPE.md",
        PROJECT_ROOT / "stratum/orchestrator/SCOPE.md",
        PROJECT_ROOT / "stratum/stages/SCOPE.md",
    ]
    for path in docs:
        text = path.read_text()
        assert "prompts/daily.md" not in text, f"{path} should not document removed domain prompt override files"


def test_orchestrator_paths_do_not_expose_unused_domain_prompt_dir():
    from stratum.orchestrator.pipeline import resolve_paths

    paths = resolve_paths("storage", "2026-05-30", "/tmp/stratum")
    assert "prompts_dir" not in paths


def test_version_register_tracks_project_and_module_versions():
    version_config = yaml.safe_load((PROJECT_ROOT / "VERSION.yaml").read_text())
    project_version = str(version_config["project"]["version"])
    release_policy = version_config["project"]["release_policy"]
    modules = version_config["modules"]

    assert project_version == "0.1.0"
    assert "1.0" in version_config["project"]["rule"]
    assert release_policy["current_line"] == "0.1"
    assert str(release_policy["next_deployment_release"]) == "0.1.1"
    assert "deployments are key releases" in release_policy["deployment_rule"]
    assert "0.1.01" in release_policy["development_iteration_examples"]
    assert set(modules) == VERSIONED_MODULES
    for name, module in modules.items():
        version = str(module["version"])
        assert version == "0.1.0", name
        assert module["reason"].strip(), name


def test_engineering_rules_cover_contract_boundaries():
    text = " ".join((PROJECT_ROOT / "docs/ENGINEERING_RULES.md").read_text().split())
    required_phrases = [
        "structured data exchanged across a dependency boundary",
        "The carrier can be JSON, JSONL, SQLite records",
        "named owner, consumers, invariants, tests",
        "docs/CONTRACT_INVENTORY.yaml",
        "versioned migrations",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_engineering_rules_separate_stages_from_algorithms():
    rules = (PROJECT_ROOT / "docs" / "ENGINEERING_RULES.md").read_text()
    normalized_rules = " ".join(rules.split())
    algorithm_architecture = (PROJECT_ROOT / "docs" / "ALGORITHM_ARCHITECTURE.md").read_text()
    normalized_algorithm_architecture = " ".join(algorithm_architecture.split())

    required_phrases = [
        "Algorithms must not grow directly inside pipeline stages",
        "A stage owns orchestration and contract handoff",
        "algorithm modules own scoring",
    ]
    for phrase in required_phrases:
        assert phrase in normalized_rules
    assert "Algorithms should not grow directly inside stages" in normalized_algorithm_architecture


def test_algorithm_architecture_tracks_stage_algorithm_split():
    text = (PROJECT_ROOT / "docs" / "ALGORITHM_ARCHITECTURE.md").read_text()
    required_phrases = [
        "Algorithm Architecture",
        "This document maps current algorithm ownership",
        "not a backlog",
        "Stages own orchestration and contract handoff",
        "AcquisitionPolicy",
        "QueryPlanner",
        "SearchSupplementPolicy",
        "admit_results_with_candidates",
        "discovery observations",
        "EvidenceAcceptancePolicy",
        "ThreadLifecycleScorer",
        "ThemeRanker",
        "ClaimValidator",
        "EvaluationRunner",
        "source-trace outputs",
        "contract handoff",
    ]
    for phrase in required_phrases:
        assert phrase in text
    assert "in_progress" not in text
    assert "implemented" not in text


def test_database_architecture_documents_replayable_cascade_test_database():
    text = (PROJECT_ROOT / "stratum" / "db" / "ARCHITECTURE.md").read_text()
    required_phrases = [
        "Cascade Test Database Contract",
        "replayable history system",
        "persist daily history",
        "synthesize and persist weekly",
        "same temporary SQLite database",
        "weekly consumes daily reports/events/judgments",
        "yearly consumes daily, weekly, monthly, and quarterly state",
        "stratum/db/cascade_fixture.py",
        "tests/test_cascade.py",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_storage_daily_architecture_documents_module_stage_data_flow():
    text = (PROJECT_ROOT / "docs" / "STORAGE_ARCHITECTURE.md").read_text()
    required_phrases = [
        "Module Relationships",
        "Daily Stage Flow",
        "Key Data Flow",
        "domains/storage",
        "stratum/orchestrator",
        "stratum/sourcing/discovery",
        "story_context.json",
        "event-threads.json",
        "thread_keywords.json",
        "What It Contains",
        "Used By",
        "run_manifest.json",
        "SQLite feedback for the next run",
        "docs/CONTRACT_INVENTORY.yaml",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_storage_baseline_documents_explicit_zero_point_one_release_checklist():
    text = (PROJECT_ROOT / "docs" / "STORAGE_BASELINE.md").read_text()
    required_phrases = [
        "explicit `0.1` baseline",
        "Canonical Run Commands",
        "Required Artifacts",
        "Validate And Repair Expectations",
        "Deployment Path",
        "Rollback Rule",
        "make daily DOMAIN=storage DATE=2026-05-30",
        "make run-deployed-daily",
        "run_manifest.json",
        "validate_report.json",
        "repair_report.json",
        "Storage_Daily_Briefing_{date}.md",
        "Storage_Daily_Briefing_{date}.html",
        "Storage_Daily_Briefing_{date}.pdf",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_active_runtime_docs_reference_storage_baseline():
    deployment = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
    orchestrator = (PROJECT_ROOT / "stratum" / "orchestrator" / "SCOPE.md").read_text()
    docs_map = (PROJECT_ROOT / "docs" / "README.md").read_text()

    assert "`STORAGE_BASELINE.md`" in docs_map
    assert "STORAGE_BASELINE.md" in deployment
    assert "docs/STORAGE_BASELINE.md" in orchestrator


def test_deployment_docs_separate_report_artifacts_from_database_state():
    deployment = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
    orchestrator = (PROJECT_ROOT / "stratum" / "orchestrator" / "SCOPE.md").read_text()
    db_scope = (PROJECT_ROOT / "stratum" / "db" / "SCOPE.md").read_text()

    for text in (deployment, orchestrator, db_scope):
        assert "reports_dir" in text
        assert "db_dir" in text
    assert "artifact store" in deployment
    assert "state store" in deployment
    assert "`reports_dir` and `db_dir` are separate runtime roots" in orchestrator
    assert "database root is a state store" in db_scope


def test_pipeline_artifact_contract_matches_orchestrator_paths(tmp_path):
    from stratum.contracts.pipeline_artifacts import DATA_DIR_ARTIFACTS, THREAD_KEYWORDS
    from stratum.orchestrator.pipeline import resolve_paths

    paths = resolve_paths("storage", "2026-05-31", str(tmp_path))

    for spec in DATA_DIR_ARTIFACTS:
        assert paths[spec.key].endswith(f"/{spec.filename}"), spec.key
    assert paths["thread_keywords"].endswith(f"/{THREAD_KEYWORDS.filename}")


def test_contract_inventory_has_required_structure_and_coverage():
    from stratum.contracts.pipeline_artifacts import DATA_DIR_ARTIFACTS

    inventory = yaml.safe_load((PROJECT_ROOT / "docs/CONTRACT_INVENTORY.yaml").read_text())
    contracts = inventory["contracts"]
    ids = {contract["id"] for contract in contracts}

    assert inventory["version"] == "0.1"
    assert INVENTORY_REQUIRED_CONTRACT_IDS.issubset(ids)
    for contract in contracts:
        for field in ("id", "boundary", "producer", "consumers", "carrier", "data_shape", "owner", "validation"):
            assert contract.get(field), f"{contract.get('id')} missing {field}"
        assert isinstance(contract["consumers"], list), contract["id"]

    artifact_keys = {
        contract.get("artifact_key")
        for contract in contracts
        if contract.get("artifact_key")
    }
    for spec in DATA_DIR_ARTIFACTS:
        assert spec.key in artifact_keys, f"inventory missing artifact key {spec.key}"


def test_contract_inventory_covers_current_top_level_modules():
    inventory = yaml.safe_load((PROJECT_ROOT / "docs/CONTRACT_INVENTORY.yaml").read_text())
    searchable = "\n".join(
        " ".join([
            str(contract.get("producer", "")),
            str(contract.get("owner", "")),
            " ".join(str(consumer) for consumer in contract.get("consumers", [])),
        ])
        for contract in inventory["contracts"]
    )

    for module in INVENTORY_REQUIRED_MODULES:
        assert module in searchable, f"contract inventory does not cover {module}"


def test_stage_outputs_are_represented_in_contract_inventory():
    inventory = yaml.safe_load((PROJECT_ROOT / "docs/CONTRACT_INVENTORY.yaml").read_text())
    searchable = "\n".join(
        " ".join([
            str(contract.get("producer", "")),
            " ".join(str(consumer) for consumer in contract.get("consumers", [])),
            str(contract.get("artifact", "")),
        ])
        for contract in inventory["contracts"]
    )

    for stage in STAGE_NAMES:
        assert f"stages.{stage}" in searchable or f"stages/{stage}" in searchable, stage


def test_orchestrator_does_not_embed_database_sql():
    forbidden = [
        "sqlite3.connect",
        "conn.execute",
        ".execute(",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "PRAGMA ",
    ]
    for path in (PROJECT_ROOT / "stratum" / "orchestrator").glob("*.py"):
        text = path.read_text()
        for phrase in forbidden:
            assert phrase not in text, f"{path.name} embeds DB SQL via {phrase}"


def test_non_db_runtime_modules_do_not_embed_database_sql():
    forbidden = [
        "sqlite3.connect",
        "conn.execute",
        ".execute(",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "PRAGMA ",
    ]
    allowed_parts = {
        "stratum/db",
        "/test_",
        "/tests/",
    }
    for path in (PROJECT_ROOT / "stratum").rglob("*.py"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if any(part in rel for part in allowed_parts):
            continue
        text = path.read_text()
        for phrase in forbidden:
            assert phrase not in text, f"{rel} embeds DB SQL via {phrase}"
