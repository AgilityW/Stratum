"""Documentation coverage for current Stratum modules."""

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SCOPE_FILES = [
    "stratum/SCOPE.md",
    "stratum/collectors/SCOPE.md",
    "stratum/contracts/SCOPE.md",
    "stratum/db/SCOPE.md",
    "stratum/orchestrator/SCOPE.md",
    "stratum/stages/SCOPE.md",
    "stratum/subsystems/event-thread/SCOPE.md",
    "stratum/subsystems/monitoring/SCOPE.md",
    "stratum/subsystems/search/SCOPE.md",
    "stratum/subsystems/story-tracking/SCOPE.md",
    "domains/storage/SCOPE.md",
]

TOP_LEVEL_DOC_FILES = [
    "README.md",
    "CONTRIBUTING.md",
]

STAGE_NAMES = [
    "search",
    "enrich",
    "verify",
    "normalize",
    "cluster",
    "edit",
    "validate",
    "render",
]

CONTRACT_SCHEMA_FILES = [
    "article_record.json",
    "collector_stats.json",
    "raw_search_result.json",
    "raw_search_stats.json",
    "story_cluster.json",
    "verified_article.json",
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


def test_required_scope_files_exist():
    for rel_path in REQUIRED_SCOPE_FILES:
        path = PROJECT_ROOT / rel_path
        assert path.exists(), rel_path
        assert path.read_text().strip(), f"{rel_path} is empty"


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


def test_stage_scope_documents_all_pipeline_stages():
    text = (PROJECT_ROOT / "stratum/stages/SCOPE.md").read_text()
    for stage in STAGE_NAMES:
        assert f"`{stage}`" in text, f"stage docs omit {stage}"
    assert "collectors sidecar" in text


def test_contract_scope_lists_current_json_schemas_once():
    text = (PROJECT_ROOT / "stratum/contracts/SCOPE.md").read_text()
    listed = re.findall(r"\|\s*`([^`]+\.json)`\s*\|", text)
    assert sorted(listed) == sorted(CONTRACT_SCHEMA_FILES)
    for schema in CONTRACT_SCHEMA_FILES:
        assert listed.count(schema) == 1, f"duplicate or missing contract doc entry for {schema}"


def test_domain_prompts_are_documented_as_reserved_assets():
    docs = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "domains/storage/SCOPE.md",
        PROJECT_ROOT / "stratum/orchestrator/SCOPE.md",
        PROJECT_ROOT / "stratum/stages/SCOPE.md",
    ]
    for path in docs:
        text = path.read_text()
        assert "reserved" in text.lower(), f"{path} should document domain prompt boundary"


def test_orchestrator_paths_do_not_expose_unused_domain_prompt_dir():
    from stratum.orchestrator.pipeline import resolve_paths

    paths = resolve_paths("storage", "2026-05-30", "/tmp/stratum")
    assert "prompts_dir" not in paths
