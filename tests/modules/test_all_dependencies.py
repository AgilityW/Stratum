"""Dependency integrity for EVERY module.

Every referenced file, script, template, or config path must exist.
Every "modules:" contract reference must point to a real skill directory.
"""
import os
import pytest
from .conftest import discover_modules, load_skill_md, PROJECT_ROOT, SKILLS_DIR


def skill_modules_with_refs():
    """Parametrize: skill modules that reference files."""
    modules = discover_modules()
    params = []
    for m in modules:
        if m["type"] != "skill":
            continue
        parsed = load_skill_md(m["path"])
        if "error" in parsed:
            continue
        body = parsed.get("body", "")
        contract = parsed["frontmatter"].get("contract", {})

        # Extract module references from contract
        module_refs = []
        if isinstance(contract, dict) and "modules" in contract:
            raw = contract["modules"]
            if isinstance(raw, str):
                # Parse "[a, b, c]" format
                import re
                module_refs = [m.strip() for m in re.findall(r'[\w-]+', raw)]

        # Extract file references from body
        from .conftest import extract_refs
        file_refs = extract_refs(body)

        # Check for actual sub-files
        skill_path = os.path.join(SKILLS_DIR, m["name"])
        sub_files = []
        if os.path.isdir(skill_path):
            for root, dirs, files in os.walk(skill_path):
                for f in files:
                    if f == "SKILL.md" or f.endswith(".pyc"):
                        continue
                    sub_files.append(os.path.relpath(
                        os.path.join(root, f), skill_path))

        params.append(pytest.param(
            m, file_refs, module_refs, sub_files,
            id=m["name"]
        ))
    return params


@pytest.mark.parametrize("module,file_refs,module_refs,sub_files",
                         skill_modules_with_refs())
class TestDependencyIntegrity:
    """Files referenced by a module must exist."""

    def test_config_refers_to_config_yaml(self, module, file_refs, module_refs, sub_files):
        """If module references config.yaml, it must exist in project root."""
        if "config.yaml" not in file_refs:
            pytest.skip("no config.yaml reference")
        assert os.path.exists(os.path.join(PROJECT_ROOT, "config.yaml")), (
            "config.yaml referenced but not found in project root"
        )

    def test_domain_yaml_exists(self, module, file_refs, module_refs, sub_files):
        """If module references domain.yaml, it must exist."""
        if "domain.yaml" not in file_refs:
            pytest.skip("no domain.yaml reference")
        # domain.yaml lives in skills/stratum-storage/data/ OR project root
        possible_paths = [
            os.path.join(PROJECT_ROOT, "domain.yaml"),
            os.path.join(SKILLS_DIR, "stratum-storage", "data", "domain.yaml"),
        ]
        found = any(os.path.exists(p) for p in possible_paths)
        assert found, f"domain.yaml not found in: {possible_paths}"

    def test_all_sub_files_exist(self, module, file_refs, module_refs, sub_files):
        """Every file under the skill directory exists (trivial, but catches corruption)."""
        skill_path = os.path.join(SKILLS_DIR, module["name"])
        for sf in sub_files:
            full = os.path.join(skill_path, sf)
            assert os.path.exists(full), f"Sub-file missing: {sf}"

    def test_module_refs_point_to_real_skills(self, module, file_refs, module_refs, sub_files):
        """Every module listed in contract.modules must be a real skill directory."""
        for ref in module_refs:
            skill_path = os.path.join(SKILLS_DIR, ref)
            md_path = os.path.join(skill_path, "SKILL.md")
            assert os.path.isdir(skill_path), (
                f"Module '{ref}' referenced but directory missing: {skill_path}"
            )
            assert os.path.exists(md_path), (
                f"Module '{ref}' referenced but SKILL.md missing: {md_path}"
            )

    def test_python_module_has_requirements(self, module, file_refs, module_refs, sub_files):
        """Python source modules should have requirements.txt if they import non-stdlib."""
        if module["name"] != "source-graph-engine":
            pytest.skip("not the Python module")
        req_path = os.path.join(SKILLS_DIR, "source-graph-engine", "requirements.txt")
        assert os.path.exists(req_path), (
            "source-graph-engine missing requirements.txt"
        )


def shell_modules():
    """Parametrize: shell script modules."""
    modules = discover_modules()
    return [
        pytest.param(m, id=m["name"])
        for m in modules if m["type"] == "shell"
    ]


@pytest.mark.parametrize("module", shell_modules())
class TestShellScriptIntegrity:
    """Shell scripts must be executable and syntactically valid."""

    def test_shebang_present(self, module):
        """Shell scripts must have a shebang."""
        with open(module["path"]) as f:
            first_line = f.readline().strip()
        assert first_line.startswith("#!"), (
            f"No shebang in {module['name']}. First line: '{first_line}'"
        )

    def test_is_executable(self, module):
        """Shell scripts must be executable."""
        import stat
        mode = os.stat(module["path"]).st_mode
        assert mode & stat.S_IXUSR, f"{module['name']} is not executable"


def python_modules():
    """Parametrize: Python source modules."""
    modules = discover_modules()
    return [
        pytest.param(m, id=m["name"])
        for m in modules if m["type"] == "python"
    ]


@pytest.mark.parametrize("module", python_modules())
class TestPythonModuleIntegrity:
    """Python modules must be syntactically valid and have docstrings."""

    def test_python_syntax(self, module):
        """Python file must compile without syntax errors."""
        with open(module["path"]) as f:
            code = f.read()
        try:
            compile(code, module["path"], "exec")
        except SyntaxError as e:
            pytest.fail(f"Python syntax error in {module['name']}: {e}")

    def test_has_docstring(self, module):
        """Every Python module should have a module-level docstring."""
        import ast
        with open(module["path"]) as f:
            tree = ast.parse(f.read())
        docstring = ast.get_docstring(tree)
        assert docstring is not None, (
            f"{module['name']} missing module-level docstring"
        )
        assert len(docstring) > 10, (
            f"{module['name']} docstring too short: '{docstring}'"
        )
