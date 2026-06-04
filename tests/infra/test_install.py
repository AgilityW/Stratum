"""Layer 3: Install flow verification — config, install.sh, current project shape.

Validates that the project is in a deployable state:
  - config.example.yaml is valid YAML with required sections
  - install.sh exists and is executable
"""

import re
import subprocess
import sqlite3
import importlib.util
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"
DEPLOYMENT_SCRIPTS = [
    "scripts/release.sh",
    "scripts/deploy.sh",
    "scripts/run_daily.sh",
    "scripts/healthcheck.sh",
    "scripts/rollback.sh",
]


# ── config.example.yaml ────────────────────────────────────

class TestConfigExample:
    """config.example.yaml is valid and complete."""

    @pytest.fixture
    def config(self):
        path = PROJECT_ROOT / "config.example.yaml"
        assert path.exists(), "config.example.yaml not found"
        with open(path) as f:
            return yaml.safe_load(f)

    def test_is_valid_yaml(self, config):
        """Parses without error."""
        assert isinstance(config, dict)

    def test_has_source_languages(self, config):
        assert "source_languages" in config
        assert isinstance(config["source_languages"], list)
        assert len(config["source_languages"]) > 0

    def test_has_output_languages(self, config):
        assert "output_languages" in config
        assert isinstance(config["output_languages"], list)

    def test_has_engines(self, config):
        assert "engines" in config
        engines = config["engines"]
        assert isinstance(engines, dict)
        for name, eng in engines.items():
            assert "languages" in eng, f"Engine '{name}' missing 'languages'"
            assert "endpoint" in eng, f"Engine '{name}' missing 'endpoint'"
            assert "auth" in eng, f"Engine '{name}' missing 'auth'"

    def test_has_output_dir(self, config):
        assert "output_dir" in config, "config.example.yaml must define output_dir"

    def test_reports_and_database_roots_are_separate(self, config):
        assert "reports_dir" in config, "config.example.yaml must define reports_dir"
        assert "db_dir" in config, "config.example.yaml must define db_dir"
        assert config["reports_dir"] != config["db_dir"]
        assert config["reports_dir"].endswith("/reports")
        assert config["db_dir"].endswith("/db")

    def test_example_roots_use_neutral_home_paths(self, config):
        assert config["output_dir"] == "$HOME/stratum"
        assert config["reports_dir"] == "$HOME/stratum/reports"
        assert config["db_dir"] == "$HOME/stratum/db"
        assert config["health_data_dir"] == "$HOME/stratum/health"
        assert config["deployment"]["root"] == "$HOME/stratum/deployments"

    def test_has_chrome_path(self, config):
        assert "chrome_path" in config, "config.example.yaml must define chrome_path"

    def test_has_deployment_defaults(self, config):
        assert config["deployment"]["root"]
        assert config["deployment"]["environment"] == "production"

    def test_no_real_secrets_leaked(self, config):
        """config.example.yaml uses ${ENV_VAR} placeholders, not real keys."""
        yaml_str = (PROJECT_ROOT / "config.example.yaml").read_text()
        # Should reference env vars, not contain literal keys
        assert "${BOCHA_API_KEY}" in yaml_str or "BOCHA_API_KEY" in yaml_str
        assert "${TAVILY_API_KEY}" in yaml_str or "TAVILY_API_KEY" in yaml_str

    def test_env_example_uses_non_secret_placeholders(self):
        env_text = (PROJECT_ROOT / ".env.example").read_text()
        assert "sk-" not in env_text
        assert "tvly-" not in env_text

    def test_output_format_uses_current_daily_chunks(self, config):
        template = config["output_format"]["zh-CN"]
        for chunk in ("今日要点", "行业要点", "产业信号", "特别关注", "反向信号"):
            assert f"## {chunk}" in template
        assert "### 关注" not in template
        assert "{{ARTICLES}}" not in template
        assert "{{WATCH}}" not in template
        assert "{{CONTRARIAN}}" not in template

    def test_storage_has_weekly_render_template(self):
        template_path = PROJECT_ROOT / "domains" / "storage" / "templates" / "weekly.html"
        assert template_path.exists()
        text = template_path.read_text()
        assert "{title}" in text
        assert "{date_str}" in text
        assert "{body}" in text
        assert "早报" not in text


# ── install.sh ─────────────────────────────────────────────

class TestInstallSh:
    """install.sh is present and executable."""

    def test_install_sh_exists(self):
        path = PROJECT_ROOT / "install.sh"
        assert path.exists(), "install.sh not found"

    def test_install_sh_is_executable(self):
        path = PROJECT_ROOT / "install.sh"
        assert path.stat().st_mode & 0o111, "install.sh is not executable (chmod +x)"

    def test_install_sh_is_valid_bash(self):
        path = PROJECT_ROOT / "install.sh"
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"bash -n install.sh failed:\n{result.stderr}"


class TestDeploymentScripts:
    """Deployment scripts are first-class executable entrypoints."""

    def test_scripts_exist_and_are_executable(self):
        for rel_path in DEPLOYMENT_SCRIPTS:
            path = PROJECT_ROOT / rel_path
            assert path.exists(), rel_path
            assert path.stat().st_mode & 0o111, f"{rel_path} is not executable"

    def test_scripts_are_valid_bash(self):
        for rel_path in DEPLOYMENT_SCRIPTS:
            path = PROJECT_ROOT / rel_path
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            assert result.returncode == 0, f"bash -n {rel_path} failed:\n{result.stderr}"

    def test_deploy_script_requires_tag_version(self):
        text = (PROJECT_ROOT / "scripts" / "deploy.sh").read_text()
        assert "refs/tags/$VERSION" in text
        assert "git archive \"$VERSION\"" in text


# ── Project structure ──────────────────────────────────────

class TestProjectStructure:
    """Key files and directories exist."""

    ACTIVE_DOCS = (
        [Path("README.md"), Path("CONTRIBUTING.md")]
        + sorted(Path("docs").glob("*.md"))
        + sorted(Path("stratum").glob("*/SCOPE.md"))
        + sorted(Path("stratum").glob("*/*/SCOPE.md"))
    )

    def test_readme_exists(self):
        assert (PROJECT_ROOT / "README.md").exists()

    def test_license_exists(self):
        assert (PROJECT_ROOT / "LICENSE").exists()

    def test_contributing_exists(self):
        assert (PROJECT_ROOT / "CONTRIBUTING.md").exists()

    def test_makefile_exists(self):
        assert (PROJECT_ROOT / "Makefile").exists()

    def test_contracts_dir_exists(self):
        assert (PROJECT_ROOT / "stratum" / "contracts").is_dir()

    def test_db_schema_executes_on_empty_sqlite(self):
        schema = (PROJECT_ROOT / "stratum" / "db" / "schema.sql").read_text()
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(schema)
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(queries)").fetchall()
            }
        finally:
            conn.close()
        assert "dimension" in columns

    def test_legacy_skills_dir_absent_or_empty(self):
        """The current project is pipeline-code based, not Hermes-skill based."""
        if not SKILLS_DIR.exists():
            return
        visible_entries = [
            p for p in SKILLS_DIR.iterdir()
            if not p.name.startswith(".") and p.name != "__pycache__"
        ]
        assert visible_entries == []

    def test_makefile_pytest_paths_exist(self):
        """Makefile focused test targets should not point at removed test files."""
        makefile = (PROJECT_ROOT / "Makefile").read_text()
        known_options = {
            "-m", "-v", "--cov", "--cov-report=term-missing", "--cov-report=html",
            "$(PYTHON)", "pytest", "$(FILE)",
        }

        for line in makefile.splitlines():
            stripped = line.strip()
            if not stripped.startswith("$(PYTHON) -m pytest "):
                continue
            for token in stripped.split()[3:]:
                if token in known_options or token.startswith("--"):
                    continue
                if token.endswith("/") or token.endswith(".py"):
                    assert (PROJECT_ROOT / token).exists(), token

    def test_pyproject_default_pytest_paths_cover_registered_analysis_modules(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        assert 'stratum/source_trace' in pyproject
        assert 'stratum/signal_bursts' in pyproject

    def test_makefile_pipeline_targets_are_repo_local(self):
        """Pipeline shortcuts should not depend on private external cron ids."""
        makefile = (PROJECT_ROOT / "Makefile").read_text()
        assert "hermes cron run" not in makefile
        assert "stratum/orchestrator/pipeline.py" in makefile

    def test_makefile_higher_scale_targets_use_timescale_pipeline(self):
        makefile = (PROJECT_ROOT / "Makefile").read_text()
        assert "$(TIMESCALE_CMD) weekly" in makefile
        assert "$(TIMESCALE_CMD) monthly" in makefile
        assert "$(TIMESCALE_CMD) quarterly" in makefile
        assert "$(TIMESCALE_CMD) yearly" in makefile
        assert "daily-only orchestrator" not in makefile

    def test_project_metadata_matches_readme_version(self):
        import yaml

        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        version_line = next(
            line for line in pyproject.splitlines()
            if line.startswith("version = ")
        )
        version = version_line.split("=", 1)[1].strip().strip('"')
        readme = (PROJECT_ROOT / "README.md").read_text()
        version_config = yaml.safe_load((PROJECT_ROOT / "VERSION.yaml").read_text())

        assert version_config["project"]["version"] == version
        assert readme.startswith("# Stratum")
        assert f"v{version}" in readme

    def test_readme_architecture_tree_uses_current_stage_names(self):
        readme = (PROJECT_ROOT / "README.md").read_text()
        assert "├── acquisition/" in readme or "│   │   ├── acquisition/" in readme
        assert "│   │   ├── sourcing/" not in readme

    def test_readme_documents_current_higher_scale_entrypoints(self):
        readme = (PROJECT_ROOT / "README.md").read_text()
        assert "make weekly DOMAIN=storage DATE=2026-W22" in readme
        assert "--timescale weekly --date 2026-W22" in readme
        assert "DB-native timescale temporal runner" in readme

    def test_storage_daily_architecture_documents_canonical_delivery_names(self):
        text = (PROJECT_ROOT / "docs" / "STORAGE_ARCHITECTURE.md").read_text()
        assert "Storage_Daily_Briefing_{date}.md" in text
        assert "Storage_Daily_Briefing_{date}.html" in text
        assert "Storage_Daily_Briefing_{date}.pdf" in text

    def test_active_docs_use_canonical_briefing_artifact_names(self):
        readme = (PROJECT_ROOT / "README.md").read_text()
        orchestrator_scope = (PROJECT_ROOT / "stratum" / "orchestrator" / "SCOPE.md").read_text()
        stages_scope = (PROJECT_ROOT / "stratum" / "stages" / "SCOPE.md").read_text()

        assert "{Domain}_{Timescale}_Briefing_{Period}.md" in readme
        assert "Stage 6:    Edit       → briefing.md" not in readme
        assert "| briefing | `{Domain}_{Timescale}_Briefing_{period}.md`, `{Domain}_{Timescale}_Briefing_{period}.html`, `{Domain}_{Timescale}_Briefing_{period}.pdf` |" in orchestrator_scope
        assert "story_context.json -> edit -> {Domain}_{Timescale}_Briefing_{period}.md" in orchestrator_scope
        assert "{Domain}_{Timescale}_Briefing_{period}.html" in stages_scope
        assert "{Domain}_{Timescale}_Briefing_{period}.pdf" in stages_scope

    def test_active_docs_use_story_tracking_package_name_for_modules(self):
        storage_arch = (PROJECT_ROOT / "docs" / "STORAGE_ARCHITECTURE.md").read_text()
        db_scope = (PROJECT_ROOT / "stratum" / "db" / "SCOPE.md").read_text()
        contracts_scope = (PROJECT_ROOT / "stratum" / "contracts" / "SCOPE.md").read_text()

        assert "`stratum.subsystems.story_tracking`" in storage_arch
        assert "| Story context | `orchestrator.story_runtime`, `db`, `story-tracking` |" not in storage_arch
        assert "`stratum.subsystems.story_tracking` + DB reads" in storage_arch
        assert "`stratum.subsystems.story_tracking`" in db_scope
        assert "story-tracking prompt context" not in db_scope
        assert "`stratum.subsystems.story_tracking` contract for now" in contracts_scope

    def test_active_docs_do_not_reference_removed_or_renamed_modules(self):
        db_scope = (PROJECT_ROOT / "stratum" / "db" / "SCOPE.md").read_text()
        validate_scope = (PROJECT_ROOT / "stratum" / "stages" / "validate" / "SCOPE.md").read_text()

        assert "stratum/cascade.py" not in db_scope
        assert "overclaim_policy.py" not in validate_scope
        assert "claim_validator.py" in validate_scope

    def test_active_docs_repo_relative_paths_exist(self):
        pattern = re.compile(r"`((?:stratum|domains|docs|tests)/[^`\s]+)`")
        skip_tokens = ("{", "}", "<", ">", "*", "...")
        failures = []

        for rel_path in self.ACTIVE_DOCS:
            text = (PROJECT_ROOT / rel_path).read_text()
            for match in pattern.finditer(text):
                raw = match.group(1).rstrip(".,:;)")
                if any(token in raw for token in skip_tokens):
                    continue
                if not (PROJECT_ROOT / raw).exists():
                    failures.append(f"{rel_path}: {raw}")

        assert failures == []

    def test_active_scope_docs_local_source_file_references_exist(self):
        pattern = re.compile(r"`([^`\s]+)`")
        skip_literals = {"config.yaml", "domain.yaml", "queries.yaml"}
        source_exts = (".py", ".yaml", ".sql", ".html")
        failures = []

        for rel_path in [p for p in self.ACTIVE_DOCS if p.name == "SCOPE.md"]:
            scope_dir = (PROJECT_ROOT / rel_path).parent
            text = (PROJECT_ROOT / rel_path).read_text()
            for match in pattern.finditer(text):
                raw = match.group(1).rstrip(".,:;)")
                if "/" in raw or raw in skip_literals or raw.startswith("--"):
                    continue
                if any(token in raw for token in ("{", "}", "<", ">", "*", "...", " ")):
                    continue
                if raw.endswith(source_exts) and not (scope_dir / raw).exists():
                    failures.append(f"{rel_path}: {raw}")

        assert failures == []

    def test_active_docs_python_module_paths_resolve(self):
        pattern = re.compile(r"`(stratum(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`")
        failures = []

        def resolve_module_path(ref: str) -> str | None:
            parts = ref.split(".")
            for end in range(len(parts), 1, -1):
                candidate = ".".join(parts[:end])
                try:
                    spec = importlib.util.find_spec(candidate)
                except Exception:
                    spec = None
                if spec is not None:
                    return candidate
            return None

        for rel_path in self.ACTIVE_DOCS:
            text = (PROJECT_ROOT / rel_path).read_text()
            for match in pattern.finditer(text):
                ref = match.group(1)
                if resolve_module_path(ref) is None:
                    failures.append(f"{rel_path}: {ref}")

        assert failures == []

    def test_active_docs_prefer_discovery_package_surface_over_models_path(self):
        watchlist_scope = (PROJECT_ROOT / "stratum" / "sourcing" / "watchlist" / "SCOPE.md").read_text()
        assert "stratum.sourcing.discovery.models.SearchResult" not in watchlist_scope
        assert "stratum.sourcing.discovery.SearchResult" in watchlist_scope
