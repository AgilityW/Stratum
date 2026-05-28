"""Shared fixtures for module-level tests."""
import os
import re
import yaml
import pytest
from pathlib import Path

PROJECT_ROOT = os.path.expanduser("~/ProjectSpace/Stratum")
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")


def discover_modules():
    """Discover all Stratum modules: SKILL.md + Python + shell scripts."""
    modules = []

    # SKILL modules
    for d in sorted(os.listdir(SKILLS_DIR)):
        md_path = os.path.join(SKILLS_DIR, d, "SKILL.md")
        if os.path.exists(md_path):
            modules.append({"type": "skill", "name": d, "path": md_path})

    # Python modules
    py_dir = os.path.join(SKILLS_DIR, "source-graph-engine")
    if os.path.isdir(py_dir):
        for f in sorted(os.listdir(py_dir)):
            if f.endswith(".py") and not f.startswith("__"):
                modules.append({
                    "type": "python",
                    "name": f"source-graph-engine/{f}",
                    "path": os.path.join(py_dir, f),
                })

    # Shell scripts
    for root, dirs, files in os.walk(SKILLS_DIR):
        for f in files:
            if f.endswith(".sh"):
                modules.append({
                    "type": "shell",
                    "name": f"{os.path.relpath(root, SKILLS_DIR)}/{f}",
                    "path": os.path.join(root, f),
                })

    return modules


def load_skill_md(path):
    """Parse a SKILL.md YAML frontmatter + markdown body."""
    with open(path) as f:
        content = f.read()

    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return {"error": "no frontmatter", "raw": content}

    try:
        fm = yaml.safe_load(fm_match.group(1))
    except Exception as e:
        return {"error": f"yaml parse: {e}", "raw": content}

    body = content[fm_match.end():]
    return {"frontmatter": fm, "body": body, "raw": content}


def extract_code_blocks(body):
    """Extract embedded code blocks with language."""
    blocks = []
    for m in re.finditer(r'```(\w+)\n(.*?)```', body, re.DOTALL):
        blocks.append({"lang": m.group(1).lower(), "code": m.group(2)})
    return blocks


def extract_refs(body):
    """Extract all file/config references from markdown body."""
    refs = set()
    for pattern in [
        r'`([^`]+\.(?:py|sh|yaml|yml|json|html|css|js|md))`',
        r'`(\$\{[A-Z_]+\}/[^\s,)}]+)`',
        r'(config\.yaml)',
        r'(domain\.yaml)',
        r'(runtime-config\.json)',
        r'(install\.sh)',
    ]:
        for m in re.finditer(pattern, body):
            refs.add(m.group(1))
    return sorted(refs)


# --- Fixtures ---

@pytest.fixture(scope="module")
def all_modules():
    """All discoverable modules in the project."""
    return discover_modules()


@pytest.fixture(scope="module")
def modules_by_type():
    """Group modules by type."""
    modules = discover_modules()
    return {
        "skill": [m for m in modules if m["type"] == "skill"],
        "python": [m for m in modules if m["type"] == "python"],
        "shell": [m for m in modules if m["type"] == "shell"],
    }
