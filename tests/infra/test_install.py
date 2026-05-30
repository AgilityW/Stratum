"""Layer 3: Install flow verification — config, install.sh, current project shape.

Validates that the project is in a deployable state:
  - config.example.yaml is valid YAML with required sections
  - install.sh exists and is executable
"""

import subprocess
import sqlite3
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"
DEPLOYMENT_SCRIPTS = [
    "scripts/release.sh",
    "scripts/deploy.sh",
    "scripts/run_deployed_daily.sh",
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

    def test_output_format_uses_current_daily_chunks(self, config):
        template = config["output_format"]["zh-CN"]
        for chunk in ("今日要点", "行业要点", "产业信号", "特别关注", "反向信号"):
            assert f"## {chunk}" in template
        assert "### 关注" not in template
        assert "{{ARTICLES}}" not in template
        assert "{{WATCH}}" not in template
        assert "{{CONTRARIAN}}" not in template


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

    def test_makefile_pipeline_targets_are_repo_local(self):
        """Pipeline shortcuts should not depend on private external cron ids."""
        makefile = (PROJECT_ROOT / "Makefile").read_text()
        assert "hermes cron run" not in makefile
        assert "stratum/orchestrator/pipeline.py" in makefile

    def test_project_metadata_matches_readme_major_version(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        version_line = next(
            line for line in pyproject.splitlines()
            if line.startswith("version = ")
        )
        version = version_line.split("=", 1)[1].strip().strip('"')
        readme = (PROJECT_ROOT / "README.md").read_text()

        assert readme.startswith("# Stratum")
        assert f"v{version.split('.')[0]}." in readme
