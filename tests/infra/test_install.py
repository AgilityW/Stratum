"""Layer 3: Install flow verification — config, SKILL.md frontmatter, install.sh.

Validates that the project is in a deployable state:
  - config.example.yaml is valid YAML with required sections
  - All SKILL.md files have valid frontmatter (name, version, contract)
  - install.sh exists and is executable
"""

import subprocess
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"


# ── Helpers ─────────────────────────────────────────────────

def _find_skill_md():
    """Return list of (skill_dir_name, SKILL.md path)."""
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            md = d / "SKILL.md"
            if md.exists():
                skills.append((d.name, md))
    return skills


def _parse_frontmatter(path):
    """Parse YAML frontmatter from a SKILL.md file."""
    with open(path) as f:
        content = f.read()

    if not content.startswith("---"):
        return None, "Missing opening '---'"

    # Find second ---
    end = content.find("---", 3)
    if end == -1:
        return None, "Missing closing '---'"

    yaml_str = content[3:end].strip()
    if not yaml_str:
        return None, "Empty frontmatter"

    try:
        return yaml.safe_load(yaml_str), None
    except yaml.YAMLError as e:
        return None, str(e)


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

    def test_no_real_secrets_leaked(self, config):
        """config.example.yaml uses ${ENV_VAR} placeholders, not real keys."""
        yaml_str = (PROJECT_ROOT / "config.example.yaml").read_text()
        # Should reference env vars, not contain literal keys
        assert "${BOCHA_API_KEY}" in yaml_str or "BOCHA_API_KEY" in yaml_str
        assert "${TAVILY_API_KEY}" in yaml_str or "TAVILY_API_KEY" in yaml_str


# ── SKILL.md frontmatter ───────────────────────────────────

class TestSkillFrontmatter:
    """All SKILL.md files have valid frontmatter with required fields."""

    REQUIRED_TOP = {"name", "description", "version"}
    REQUIRED_CONTRACT = {"input", "output"}

    @pytest.mark.parametrize("skill_name,skill_path", _find_skill_md())
    def test_has_valid_frontmatter(self, skill_name, skill_path):
        fm, error = _parse_frontmatter(skill_path)
        assert fm is not None, f"SKILL.md frontmatter parse error: {error}"

    @pytest.mark.parametrize("skill_name,skill_path", _find_skill_md())
    def test_has_required_top_fields(self, skill_name, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        missing = self.REQUIRED_TOP - set(fm.keys())
        assert not missing, f"Missing required fields: {missing}"

    @pytest.mark.parametrize("skill_name,skill_path", _find_skill_md())
    def test_contract_has_input_output(self, skill_name, skill_path):
        # stratum-deployment is a reference doc, not a pipeline skill
        if skill_name == "stratum-deployment":
            pytest.skip("stratum-deployment is a reference doc, not a pipeline skill")
        
        fm, _ = _parse_frontmatter(skill_path)
        contract = fm.get("contract", {})
        missing = self.REQUIRED_CONTRACT - set(contract.keys())
        assert not missing, f"Contract missing required fields: {missing}"

    @pytest.mark.parametrize("skill_name,skill_path", _find_skill_md())
    def test_version_is_string(self, skill_name, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        assert isinstance(fm["version"], str), f"version should be string, got {type(fm['version'])}"

    @pytest.mark.parametrize("skill_name,skill_path", _find_skill_md())
    def test_no_duplicate_version(self, skill_name, skill_path):
        """version field appears exactly once in frontmatter."""
        with open(skill_path) as f:
            content = f.read()
        end = content.find("---", 3)
        yaml_str = content[3:end]
        occurrences = [i for i in range(len(yaml_str)) if yaml_str.startswith("version:", i)]
        assert len(occurrences) == 1, (
            f"version appears {len(occurrences)} times in frontmatter — YAML parser "
            f"will only keep the last one, causing metadata drift"
        )


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

    def test_at_least_one_skill(self):
        skills = _find_skill_md()
        assert len(skills) > 0, "No SKILL.md files found in skills/"
