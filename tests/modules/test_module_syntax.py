"""Embedded code syntax validation for EVERY skill module with code blocks.

Any Python/bash/shell code embedded in SKILL.md must be syntactically valid.
"""
import ast
import subprocess
import tempfile
import os
import pytest
from .conftest import discover_modules, load_skill_md, extract_code_blocks


def skill_modules_with_code():
    """Parametrize: all skill modules that have embedded code blocks."""
    modules = discover_modules()
    params = []
    for m in modules:
        if m["type"] != "skill":
            continue
        parsed = load_skill_md(m["path"])
        if "error" in parsed:
            continue
        blocks = extract_code_blocks(parsed.get("body", ""))
        params.append(pytest.param(m, blocks, id=m["name"]))
    return params


@pytest.mark.parametrize("module,blocks", skill_modules_with_code())
class TestEmbeddedCodeSyntax:
    """All embedded code blocks must be syntactically valid."""

    PYTHON_LANGS = {"python", "py"}
    SHELL_LANGS = {"bash", "shell", "sh"}

    def test_python_blocks_syntax(self, module, blocks):
        """Every Python code block compiles without syntax errors."""
        py_blocks = [b for b in blocks if b["lang"] in self.PYTHON_LANGS]
        for i, block in enumerate(py_blocks):
            code = block["code"]
            try:
                compile(code, f"<{module['name']}:block{i}>", "exec")
            except SyntaxError as e:
                pytest.fail(
                    f"Python block {i} in {module['name']} has syntax error: {e}\n"
                    f"Code:\n{code[:500]}"
                )

    def test_python_blocks_ast_valid(self, module, blocks):
        """Every Python code block parses to a valid AST."""
        py_blocks = [b for b in blocks if b["lang"] in self.PYTHON_LANGS]
        for i, block in enumerate(py_blocks):
            code = block["code"]
            try:
                ast.parse(code)
            except SyntaxError as e:
                pytest.fail(
                    f"Python block {i} in {module['name']} AST parse failed: {e}"
                )

    def test_shell_blocks_syntax(self, module, blocks):
        """Every shell/bash code block passes 'bash -n' syntax check."""
        sh_blocks = [b for b in blocks if b["lang"] in self.SHELL_LANGS]
        for i, block in enumerate(sh_blocks):
            code = block["code"]
            if not code.strip():
                continue  # empty blocks are fine

            # Write to temp file and check with bash -n
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False
            ) as f:
                f.write(code)
                tmp_path = f.name

            try:
                result = subprocess.run(
                    ["bash", "-n", tmp_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0:
                    pytest.fail(
                        f"Shell block {i} in {module['name']} has syntax error:\n"
                        f"{result.stderr}\nCode:\n{code[:500]}"
                    )
            finally:
                os.unlink(tmp_path)

    def test_no_line_numbers_in_code_blocks(self, module, blocks):
        """Code blocks must not have line number prefixes.

        Rejects patterns like '42|    code' that come from SKILL.md files
        opened with line numbers.
        """
        import re
        for i, block in enumerate(blocks):
            lines = block["code"].split("\n")
            for lineno, line in enumerate(lines):
                if re.match(r'^\s*\d+\|', line):
                    pytest.fail(
                        f"Line number prefix found in {module['name']} "
                        f"block {i}, line {lineno+1}: '{line[:80]}'"
                    )
