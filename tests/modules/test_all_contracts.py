"""Contract validation for EVERY SKILL module.

Each SKILL.md must have:
1. Valid YAML frontmatter
2. A 'contract' field that is a dict with 'input' and 'output'

stratum-deployment is the sole exception (infrastructure, not pipeline).
"""
import pytest
from .conftest import discover_modules, load_skill_md

EXEMPT_MODULES = {"stratum-deployment"}  # infrastructure, not in pipeline


def skill_modules():
    """Parametrize: all skill modules with valid frontmatter."""
    modules = discover_modules()
    params = []
    for m in modules:
        if m["type"] != "skill":
            continue
        parsed = load_skill_md(m["path"])
        if "error" in parsed:
            # Still test it — error should be reported
            params.append(pytest.param(m, parsed, id=m["name"]))
        else:
            params.append(pytest.param(m, parsed, id=m["name"]))
    return params


@pytest.mark.parametrize("module,parsed", skill_modules())
class TestContractExists:
    """Every skill module must have a contract field (or be exempt)."""

    def test_frontmatter_parses(self, module, parsed):
        """Frontmatter must be valid YAML."""
        if "error" in parsed:
            pytest.fail(f"Frontmatter error: {parsed['error']}")

    def test_has_contract_field(self, module, parsed):
        """Must have 'contract' in frontmatter."""
        if module["name"] in EXEMPT_MODULES:
            pytest.skip("exempt: infrastructure module")
        fm = parsed["frontmatter"]
        assert "contract" in fm, (
            f"Missing 'contract' field in frontmatter. "
            f"Expected: {{ input: ..., output: ... }}"
        )

    def test_contract_is_dict(self, module, parsed):
        """Contract must be a dict, not a string or null."""
        if module["name"] in EXEMPT_MODULES:
            pytest.skip("exempt: infrastructure module")
        contract = parsed["frontmatter"].get("contract", {})
        assert isinstance(contract, dict), (
            f"Contract must be a dict, got {type(contract).__name__}. "
            f"Expected: {{ input: '...', output: '...' }}"
        )

    def test_contract_has_input(self, module, parsed):
        """Contract must specify input."""
        if module["name"] in EXEMPT_MODULES:
            pytest.skip("exempt: infrastructure module")
        contract = parsed["frontmatter"].get("contract", {})
        assert "input" in contract, (
            f"Contract missing 'input' field. Describe what data this module consumes."
        )

    def test_contract_has_output(self, module, parsed):
        """Contract must specify output."""
        if module["name"] in EXEMPT_MODULES:
            pytest.skip("exempt: infrastructure module")
        contract = parsed["frontmatter"].get("contract", {})
        assert "output" in contract, (
            f"Contract missing 'output' field. Describe what data this module produces."
        )

    def test_version_is_semver(self, module, parsed):
        """Version string should look like semver (X.Y or X.Y.Z)."""
        if module["name"] in EXEMPT_MODULES:
            pytest.skip("exempt")
        import re
        version = str(parsed["frontmatter"].get("version", ""))
        assert re.match(r'^\d+\.\d+(\.\d+)?$', version), (
            f"Version '{version}' is not semver-like. Expected: X.Y or X.Y.Z"
        )

    def test_name_field_present(self, module, parsed):
        """Must have a 'name' field matching directory name."""
        assert "name" in parsed["frontmatter"], "Missing 'name' in frontmatter"
        expected_name = module["name"]
        actual_name = parsed["frontmatter"]["name"]
        assert actual_name == expected_name, (
            f"Name mismatch: dir='{expected_name}' but name='{actual_name}'"
        )
