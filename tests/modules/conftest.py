"""Shared fixtures for module-level tests."""
import os
import re
import yaml
import pytest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
SUBSYSTEMS_DIR = os.path.join(PROJECT_ROOT, "stratum", "subsystems")


def discover_modules():
    """Discover all Stratum modules: SKILL.md + Python + shell scripts.
    Scans skills/ and stratum/subsystems/."""
    modules = []

    # SKILL modules — scan skills/ + subsystems/
    for base_dir in (SKILLS_DIR, SUBSYSTEMS_DIR):
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f == "SKILL.md":
                    # Leaf directory name as module name
                    name = os.path.basename(root)
                    modules.append({
                        "type": "skill",
                        "name": name,
                        "path": os.path.join(root, f),
                    })

    # Python modules — scan source-graph
    py_dir = os.path.join(SUBSYSTEMS_DIR, "source-graph")
    if os.path.isdir(py_dir):
        for f in sorted(os.listdir(py_dir)):
            if f.endswith(".py") and not f.startswith("__"):
                modules.append({
                    "type": "python",
                    "name": f"source-graph/{f}",
                    "path": os.path.join(py_dir, f),
                })

    # Shell scripts
    for base_dir in (SKILLS_DIR, SUBSYSTEMS_DIR):
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".sh"):
                    modules.append({
                        "type": "shell",
                        "name": f"{os.path.relpath(root, base_dir)}/{f}",
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
